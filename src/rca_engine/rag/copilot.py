from __future__ import annotations

import time

from rca_engine.hash_utils import stable_id
from rca_engine.models import (
    CopilotRequest,
    CopilotResponse,
    KnowledgeMatch,
    PostmortemDraft,
    RAGQueryTrace,
)
from rca_engine.rag.context import ContextBuilder
from rca_engine.rag.embedding import EmbeddingProvider
from rca_engine.rag.llm import LLMProvider, LLMResult, LLMSettings, build_llm_provider
from rca_engine.rag.llm_reranker import LLMReranker
from rca_engine.rag.retriever import KnowledgeRetriever
from rca_engine.rag.verification import apply_claim_guardrail, verify_answer


class RCACopilot:
    def __init__(
        self,
        store,
        llm_settings: LLMSettings | None = None,
        cache_ttl_seconds: int = 300,
        embedding_provider: EmbeddingProvider | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.store = store
        self.retriever = KnowledgeRetriever(store, embedding_provider=embedding_provider)
        self.llm_settings = llm_settings or LLMSettings()
        self.llm = llm_provider or build_llm_provider(self.llm_settings)
        self.llm_reranker = LLMReranker(self.llm, enabled=self.llm_settings.rerank_enabled)
        self.context_builder = ContextBuilder()
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, CopilotResponse]] = {}

    def answer(self, request: CopilotRequest) -> CopilotResponse:
        started = time.monotonic()
        cache_key = stable_id("copilot_cache", request.model_dump(mode="json"))
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] <= self.cache_ttl_seconds:
            cached_response = cached[1].model_copy(update={"cache_hit": True, "latency_ms": 0})
            self._record_trace(request, "cache", cached_response, 0)
            return cached_response

        intent, matches, pipeline_trace = self.retriever.search_with_pipeline(
            query=request.question,
            incident_id=request.incident_id,
            limit=request.limit,
        )
        response_path = _response_path(request.mode, intent.needs_llm, self.llm.available())
        rerank_strategy = "deterministic"
        if response_path == "deep":
            reranked = self.llm_reranker.rerank(request.question, matches)
            if [item.ref_id for item in reranked] != [item.ref_id for item in matches]:
                rerank_strategy = "llm"
                matches = reranked
        pipeline_trace["optional_reranker"] = {
            "strategy": rerank_strategy,
            "enabled": response_path == "deep" and self.llm_settings.rerank_enabled,
        }

        llm_result: LLMResult | None = None
        fallback_reason: str | None = None
        answer: str | None = None
        if response_path == "deep":
            llm_result = self.llm.complete(question=request.question, context=matches[:8])
            if llm_result and llm_result.answer:
                answer = llm_result.answer
            elif llm_result and llm_result.fallback_reason:
                fallback_reason = llm_result.fallback_reason

        if not answer:
            response_path = "fast" if matches else "fallback"
            answer = _compose_answer(request.question, matches)
            fallback_reason = fallback_reason or "llm_unavailable_or_empty"

        built_context = self.context_builder.build(matches, query=request.question)
        citations = built_context.citations
        pipeline_trace["context_builder"] = built_context.trace
        answer, claim_guard_notes = apply_claim_guardrail(answer, citations)
        verification = verify_answer(answer, matches, citations)
        if verification.blocked_terms:
            response_path = "fallback"
            answer = _compose_answer(request.question, matches)
            answer += "\n\nAutomatic execution is out of scope. Use manual investigation and runbook steps only."
            answer, claim_guard_notes = apply_claim_guardrail(answer, citations)
            verification = verify_answer(answer, matches, citations)
            fallback_reason = "forbidden_automation_language"
        pipeline_trace["answer_generator"] = {"response_path": response_path}
        pipeline_trace["verifier"] = {
            "status": verification.status,
            "citation_coverage": verification.citation_coverage,
            "hallucination_risk": verification.hallucination_risk,
            "blocked_terms": verification.blocked_terms,
            "claim_guard_notes": claim_guard_notes,
        }

        structured = llm_result.structured if llm_result else {}
        latency_ms = int((time.monotonic() - started) * 1000)
        response = CopilotResponse(
            question=request.question,
            incident_id=request.incident_id,
            answer=answer,
            confidence=_confidence(matches, verification.status),
            root_cause_summary=_optional_string(structured.get("root_cause_summary")),
            missing_evidence=_string_list(structured.get("missing_evidence")),
            recommended_manual_runbooks=_string_list(structured.get("recommended_manual_runbooks")),
            confidence_rationale=_optional_string(structured.get("confidence_rationale")),
            matches=matches,
            citations=citations,
            verification=verification,
            suggested_followups=_string_list(structured.get("follow_up_questions")) or _followups(matches),
            latency_ms=latency_ms,
            cache_hit=False,
            response_path=response_path,
        )
        self._cache[cache_key] = (time.monotonic(), response)
        self._record_trace(
            request,
            intent.intent,
            response,
            latency_ms,
            llm_result=llm_result,
            rerank_strategy=rerank_strategy,
            fallback_reason=fallback_reason,
            pipeline_trace=pipeline_trace,
        )
        return response

    def stream_answer(self, request: CopilotRequest):
        if request.mode != "deep" or not self.llm.available() or not self.llm_settings.streaming_enabled:
            response = self.answer(request)
            yield "event: metadata\n"
            yield f"data: {response.model_dump_json(exclude={'answer'})}\n\n"
            yield "event: answer\n"
            yield f"data: {response.answer}\n\n"
            return

        started = time.monotonic()
        intent, matches, pipeline_trace = self.retriever.search_with_pipeline(
            query=request.question,
            incident_id=request.incident_id,
            limit=request.limit,
        )
        rerank_strategy = "deterministic"
        reranked = self.llm_reranker.rerank(request.question, matches)
        if [item.ref_id for item in reranked] != [item.ref_id for item in matches]:
            rerank_strategy = "llm"
            matches = reranked
        pipeline_trace["optional_reranker"] = {
            "strategy": rerank_strategy,
            "enabled": self.llm_settings.rerank_enabled,
        }
        built_context = self.context_builder.build(matches, query=request.question)
        citations = built_context.citations
        pipeline_trace["context_builder"] = built_context.trace
        metadata = {
            "question": request.question,
            "incident_id": request.incident_id,
            "matches": [item.model_dump(mode="json") for item in matches],
            "citations": [item.model_dump(mode="json") for item in citations],
            "response_path": "deep_stream",
            "cache_hit": False,
        }
        yield "event: metadata\n"
        yield f"data: {CopilotResponse(answer='', confidence=0.0, **metadata).model_dump_json(exclude={'answer'})}\n\n"

        chunks: list[str] = []
        for chunk in self.llm.stream(question=request.question, context=matches[:8]):
            if not chunk:
                continue
            chunks.append(str(chunk))
            yield "event: answer\n"
            yield f"data: {str(chunk)}\n\n"

        answer = "".join(chunks).strip()
        fallback_reason = None
        if not answer:
            answer = _compose_answer(request.question, matches)
            fallback_reason = "stream_empty"
            yield "event: answer\n"
            yield f"data: {answer}\n\n"
        answer, claim_guard_notes = apply_claim_guardrail(answer, citations)
        verification = verify_answer(answer, matches, citations)
        if verification.blocked_terms:
            answer = _compose_answer(request.question, matches)
            answer += "\n\nAutomatic execution is out of scope. Use manual investigation and runbook steps only."
            answer, claim_guard_notes = apply_claim_guardrail(answer, citations)
            verification = verify_answer(answer, matches, citations)
            fallback_reason = "forbidden_automation_language"
            yield "event: answer\n"
            yield f"data: \n\n{answer}\n\n"
        pipeline_trace["answer_generator"] = {
            "response_path": "deep_stream" if not fallback_reason else "fallback"
        }
        pipeline_trace["verifier"] = {
            "status": verification.status,
            "citation_coverage": verification.citation_coverage,
            "hallucination_risk": verification.hallucination_risk,
            "blocked_terms": verification.blocked_terms,
            "claim_guard_notes": claim_guard_notes,
        }
        latency_ms = int((time.monotonic() - started) * 1000)
        response = CopilotResponse(
            question=request.question,
            incident_id=request.incident_id,
            answer=answer,
            confidence=_confidence(matches, verification.status),
            matches=matches,
            citations=citations,
            verification=verification,
            suggested_followups=_followups(matches),
            latency_ms=latency_ms,
            cache_hit=False,
            response_path="deep_stream" if not fallback_reason else "fallback",
        )
        self._record_trace(
            request,
            intent.intent,
            response,
            latency_ms,
            llm_result=LLMResult(
                answer=answer,
                provider=self.llm_settings.provider,
                model=self.llm_settings.model,
                reasoning_effort=self.llm_settings.reasoning_effort,
            ),
            rerank_strategy=rerank_strategy,
            fallback_reason=fallback_reason,
            pipeline_trace=pipeline_trace,
        )
        yield "event: final\n"
        yield f"data: {response.model_dump_json(exclude={'answer'})}\n\n"

    def postmortem_draft(self, incident_id: str) -> PostmortemDraft:
        result = self.store.get_rca_result(incident_id)
        if not result:
            return PostmortemDraft(
                incident_id=incident_id,
                title=f"Postmortem draft for {incident_id}",
                summary="RCA result is not available yet.",
                impact="Impact is not confirmed.",
                root_cause="Root cause is not confirmed.",
                detection="Detection details are not available.",
            )
        report = self.store.get_agent_report(incident_id) or {}
        matches = self.retriever.search(
            "postmortem root cause evidence runbook", incident_id=incident_id, limit=6
        )
        citations = self.context_builder.build(
            matches,
            query="postmortem root cause evidence runbook",
        ).citations
        return PostmortemDraft(
            incident_id=incident_id,
            title=f"{result.get('service', 'unknown')} incident postmortem draft",
            summary=result.get("summary", "No summary available."),
            impact=", ".join(result.get("impacted_services", [])) or "Impact scope is not confirmed.",
            timeline=[
                f"{item.get('event_time')}: {item.get('summary')}"
                for item in result.get("timeline", [])[:12]
            ],
            root_cause=_top_root_cause(result),
            contributing_factors=[
                item.get("summary", "")
                for item in result.get("dependency_insights", [])
                if item.get("summary")
            ][:8],
            detection=report.get("summary") or "Detected from correlated observability events.",
            manual_followups=report.get("follow_up_questions", [])[:8],
            citations=citations,
        )

    def _record_trace(
        self,
        request: CopilotRequest,
        intent: str,
        response: CopilotResponse,
        latency_ms: int,
        llm_result: LLMResult | None = None,
        rerank_strategy: str = "deterministic",
        fallback_reason: str | None = None,
        pipeline_trace: dict | None = None,
    ) -> None:
        if not hasattr(self.store, "save_rag_query_trace"):
            return
        query_id = stable_id(
            "rag_query",
            {
                "question": request.question,
                "incident_id": request.incident_id,
                "generated_at": response.generated_at,
            },
        )
        trace = RAGQueryTrace(
            query_id=query_id,
            question=request.question,
            incident_id=request.incident_id,
            intent=intent,
            retrieved_documents=response.matches,
            selected_context=response.citations,
            final_answer=response.answer,
            latency_ms=latency_ms,
            token_cost=llm_result.token_cost if llm_result else 0.0,
            cache_hit=response.cache_hit,
            response_path=response.response_path,
            verification=response.verification,
            llm_provider=llm_result.provider if llm_result else self.llm_settings.provider,
            llm_model=llm_result.model if llm_result else self.llm_settings.model,
            reasoning_effort=(
                llm_result.reasoning_effort if llm_result else self.llm_settings.reasoning_effort
            ),
            prompt_tokens=llm_result.prompt_tokens if llm_result else 0,
            completion_tokens=llm_result.completion_tokens if llm_result else 0,
            recall_source_counts=_recall_source_counts(response.matches),
            rerank_strategy=rerank_strategy,
            top_score_breakdown=response.matches[0].score_breakdown if response.matches else {},
            pipeline_trace=pipeline_trace or {},
            fallback_reason=fallback_reason,
        )
        self.store.save_rag_query_trace(trace)


def _compose_answer(question: str, matches: list[KnowledgeMatch]) -> str:
    if not matches:
        return (
            "No matching RCA evidence or runbooks were found yet. "
            "Check whether the incident has generated an RCA result and an operator report."
        )

    best = matches[0]
    lines = [
        f"Query: {question}",
        f"Primary source: {best.source} - {best.title} (score={best.score:.2f})",
        "",
        "Working summary:",
    ]

    if best.source == "runbook":
        lines.append("The closest runbook suggests the following manual investigation path:")
        lines.append(best.content)
    elif best.source == "rca_result":
        lines.append("The RCA result is the strongest context. Review the top hypothesis, timeline, and causal links:")
        lines.append(best.content[:1200])
    elif best.source == "agent_report":
        lines.append("The operator report provides specialist findings, runbook recommendations, and follow-up questions:")
        lines.append(best.content[:1200])
    else:
        lines.append(best.content[:1200])

    if len(matches) > 1:
        lines.append("")
        lines.append("Additional context:")
        for match in matches[1:4]:
            lines.append(f"- {match.source}: {match.title} (score={match.score:.2f})")
    return "\n".join(lines)


def _confidence(matches: list[KnowledgeMatch], verification_status: str = "weak") -> float:
    if not matches:
        return 0.0
    multiplier = {
        "confirmed": 1.0,
        "likely": 0.88,
        "weak": 0.65,
        "missing_evidence": 0.2,
    }.get(verification_status, 0.65)
    return round(min((0.35 + matches[0].score * 0.6) * multiplier, 0.95), 4)


def _followups(matches: list[KnowledgeMatch]) -> list[str]:
    questions = [
        "Show me the incident timeline.",
        "Which runbook should I follow first?",
        "What evidence supports the top root cause?",
    ]
    sources = {match.source for match in matches}
    if "agent_report" in sources:
        questions.append("What follow-up questions should the responder answer?")
    if "runbook" in sources:
        questions.append("List the manual runbook steps.")
    return questions


def _response_path(mode: str, needs_llm: bool, llm_available: bool) -> str:
    if mode == "fast":
        return "fast"
    if mode == "deep" and llm_available:
        return "deep"
    if mode == "auto" and needs_llm and llm_available:
        return "deep"
    return "fast"


def _top_root_cause(result: dict) -> str:
    root_causes = result.get("root_causes") or []
    if not root_causes:
        return "Root cause is not confirmed."
    top = root_causes[0]
    return f"{top.get('title')}: {top.get('description')}"


def _optional_string(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _recall_source_counts(matches: list[KnowledgeMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        for source in match.recall_sources:
            counts[source] = counts.get(source, 0) + 1
    return counts
