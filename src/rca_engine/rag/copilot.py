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
from rca_engine.rag.llm import LLMSettings, OpenAICompatibleLLM
from rca_engine.rag.embedding import HashEmbeddingProvider
from rca_engine.rag.retriever import KnowledgeRetriever
from rca_engine.rag.verification import citations_from_matches, verify_answer


class RCACopilot:
    def __init__(
        self,
        store,
        llm_settings: LLMSettings | None = None,
        cache_ttl_seconds: int = 300,
        embedding_provider: HashEmbeddingProvider | None = None,
    ) -> None:
        self.store = store
        self.retriever = KnowledgeRetriever(store, embedding_provider=embedding_provider)
        self.llm = OpenAICompatibleLLM(llm_settings or LLMSettings())
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, CopilotResponse]] = {}

    def answer(self, request: CopilotRequest) -> CopilotResponse:
        # The cache keeps repeated operator queries cheap, but the response still
        # goes through trace recording so evaluation views can reflect cache hits.
        started = time.monotonic()
        cache_key = stable_id("copilot_cache", request.model_dump(mode="json"))
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] <= self.cache_ttl_seconds:
            cached_response = cached[1].model_copy(update={"cache_hit": True, "latency_ms": 0})
            self._record_trace(request, "cache", cached_response, 0)
            return cached_response

        intent, matches = self.retriever.search_with_intent(
            query=request.question,
            incident_id=request.incident_id,
            limit=request.limit,
        )
        response_path = _response_path(request.mode, intent.needs_llm, self.llm.available())
        answer = None
        if response_path == "deep":
            answer = self.llm.complete(question=request.question, context=matches[:8])
        if not answer:
            # The deterministic path is the reliability baseline. Optional LLM
            # synthesis can improve phrasing, but must not be required to answer.
            response_path = "fast" if matches else "fallback"
            answer = _compose_answer(request.question, matches)
        citations = citations_from_matches(matches)
        verification = verify_answer(answer, matches, citations)
        if verification.blocked_terms:
            response_path = "fallback"
            answer = _compose_answer(request.question, matches)
            answer += "\n\nAutomatic execution is out of scope. Use manual investigation and runbook steps only."
            verification = verify_answer(answer, matches, citations)
        confidence = _confidence(matches, verification.status)
        latency_ms = int((time.monotonic() - started) * 1000)
        response = CopilotResponse(
            question=request.question,
            incident_id=request.incident_id,
            answer=answer,
            confidence=confidence,
            matches=matches,
            citations=citations,
            verification=verification,
            suggested_followups=_followups(matches),
            latency_ms=latency_ms,
            cache_hit=False,
            response_path=response_path,
        )
        self._cache[cache_key] = (time.monotonic(), response)
        self._record_trace(request, intent.intent, response, latency_ms)
        return response

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
        matches = self.retriever.search("postmortem root cause evidence runbook", incident_id=incident_id, limit=6)
        citations = citations_from_matches(matches)
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
            cache_hit=response.cache_hit,
            response_path=response.response_path,
            verification=response.verification,
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
