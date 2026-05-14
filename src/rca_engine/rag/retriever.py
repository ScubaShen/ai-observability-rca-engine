from __future__ import annotations

import re
from typing import Any

from rca_engine.models import KnowledgeMatch
from rca_engine.rag.candidates import CandidateProcessor
from rca_engine.rag.embedding import EmbeddingProvider, HashEmbeddingProvider
from rca_engine.rag.planner import RetrievalPlan, RetrievalPlanner
from rca_engine.rag.preprocessor import ProcessedQuery, QueryPreprocessor
from rca_engine.rag.query import QueryIntent
from rca_engine.rag.ranker import RRFFusionRanker, rerank


CURRENT_EVIDENCE_SOURCES = {
    "evidence_summary",
    "evidence_log",
    "evidence_metric",
    "evidence_trace",
    "timeline_event",
    "graph_edge",
}


class KnowledgeRetriever:
    def __init__(self, store, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.store = store
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self.preprocessor = QueryPreprocessor()
        self.planner = RetrievalPlanner()
        self.candidate_processor = CandidateProcessor()
        self.fusion_ranker = RRFFusionRanker()

    def search(
        self,
        query: str,
        incident_id: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeMatch]:
        _, matches, _ = self.search_with_pipeline(query, incident_id=incident_id, limit=limit)
        return matches

    def search_with_pipeline(
        self,
        query: str,
        incident_id: str | None = None,
        limit: int = 5,
    ) -> tuple[QueryIntent, list[KnowledgeMatch], dict[str, Any]]:
        processed = self.preprocessor.process(query)
        plan = self.planner.build(processed, incident_id=incident_id, limit=limit)
        channel_matches = self._retrieve_channels(plan)
        processed_channels: dict[str, list[KnowledgeMatch]] = {}
        channel_traces: dict[str, Any] = {}
        for channel, matches in channel_matches.items():
            processed_candidates = self.candidate_processor.process(matches)
            processed_channels[channel] = processed_candidates.matches
            channel_traces[channel] = processed_candidates.trace

        ranked = self.fusion_ranker.rerank(processed_channels, plan)
        ranker_strategy = "rrf_hybrid_v1"
        if not ranked:
            fallback_candidates = [
                match for matches in processed_channels.values() for match in matches
            ]
            ranked = rerank(fallback_candidates, processed.intent)
            ranker_strategy = "weighted_deterministic_fallback"
        ranked = _ensure_auxiliary_diversity(ranked, window=5)
        pipeline_trace = _pipeline_trace(
            processed,
            plan,
            channel_traces,
            ranked,
            limit,
            ranker_strategy,
        )
        return processed.intent, ranked[:limit], pipeline_trace

    def search_with_intent(
        self,
        query: str,
        incident_id: str | None = None,
        limit: int = 5,
    ) -> tuple[QueryIntent, list[KnowledgeMatch]]:
        intent, matches, _ = self.search_with_pipeline(query, incident_id=incident_id, limit=limit)
        return intent, matches

    def _retrieve_channels(self, plan: RetrievalPlan) -> dict[str, list[KnowledgeMatch]]:
        channels: dict[str, list[KnowledgeMatch]] = {
            "exact": self._exact_matches(plan),
            "current_evidence": self._rag_document_matches(
                plan.keyword_query,
                plan.incident_id,
                limit=plan.source_budgets["current_evidence"],
                channel="current_evidence",
            ),
            "keyword": self._rag_document_matches(
                plan.keyword_query,
                plan.incident_id,
                limit=plan.source_budgets["keyword"],
                channel="keyword",
            ),
            "semantic": self._rag_document_matches(
                plan.semantic_query,
                plan.incident_id,
                limit=plan.source_budgets["semantic"],
                channel="semantic",
            ),
            "runbook": self._runbook_matches(
                plan.semantic_query,
                limit=plan.source_budgets["runbook"],
            ),
            "historical": self._rag_document_matches(
                plan.semantic_query,
                None,
                limit=plan.source_budgets["historical"],
                channel="historical",
            ),
            "artifact": self._artifact_matches(plan),
            "graph": [],
        }
        if plan.incident_id:
            channels["graph"].extend(self._graph_matches(plan.semantic_query, plan.incident_id))
            channels["artifact"].extend(self._event_matches(plan.semantic_query, plan.incident_id))
        return {
            name: _limit_channel(matches, plan.source_budgets.get(name, len(matches)))
            for name, matches in channels.items()
        }

    def _exact_matches(self, plan: RetrievalPlan) -> list[KnowledgeMatch]:
        matches: list[KnowledgeMatch] = []
        if plan.incident_id:
            matches.extend(self._incident_matches(plan.keyword_query, plan.incident_id, exact=True))
        for runbook_id in _runbook_ids(plan.original_query):
            if not hasattr(self.store, "get_runbook"):
                continue
            runbook = self.store.get_runbook(runbook_id)
            if runbook:
                matches.append(
                    _runbook_match(plan.keyword_query, runbook, score=1.0, recall_sources=["exact"])
                )
        return matches

    def _artifact_matches(self, plan: RetrievalPlan) -> list[KnowledgeMatch]:
        if plan.incident_id:
            return self._incident_matches(plan.semantic_query, plan.incident_id)
        return self._latest_incident_matches(plan.semantic_query)

    def _rag_document_matches(
        self,
        query: str,
        incident_id: str | None,
        limit: int,
        channel: str,
    ) -> list[KnowledgeMatch]:
        if not hasattr(self.store, "search_rag_documents"):
            return []
        embedding = self.embedding_provider.embed(query)
        if hasattr(self.store, "search_rag_documents_by_channel"):
            rows = self.store.search_rag_documents_by_channel(
                query,
                embedding,
                incident_id=incident_id,
                limit=limit,
                channel=channel,
            )
        else:
            rows = self.store.search_rag_documents(
                query,
                embedding,
                incident_id=incident_id,
                limit=limit,
            )
        matches: list[KnowledgeMatch] = []
        for row in rows:
            source_type = str(row.get("source_type") or "rag_document")
            if channel == "historical" and source_type != "historical_incident":
                continue
            if channel == "current_evidence" and source_type not in CURRENT_EVIDENCE_SOURCES:
                continue
            if channel in {"keyword", "semantic"} and source_type == "historical_incident":
                continue
            matches.append(
                KnowledgeMatch(
                    source=source_type,
                    title=str(row.get("title") or row.get("document_id")),
                    score=float(row.get("score") or 0),
                    content=str(row.get("content") or ""),
                    ref_id=row.get("ref_id"),
                    attributes={
                        **(row.get("metadata") or {}),
                        "incident_id": row.get("incident_id"),
                        "service": row.get("service"),
                        "env": row.get("env"),
                        "severity": row.get("severity"),
                        "document_id": row.get("document_id"),
                    },
                    score_breakdown={
                        "semantic_score": float(row.get("semantic_score") or 0),
                        "keyword_score": float(row.get("keyword_score") or 0),
                        f"{channel}_raw_score": float(row.get("score") or 0),
                    },
                    recall_sources=sorted(set(list(row.get("recall_sources") or []) + [channel])),
                )
            )
        return matches

    def _runbook_matches(self, query: str, limit: int | None = None) -> list[KnowledgeMatch]:
        matches: list[KnowledgeMatch] = []
        for runbook in self.store.list_runbooks():
            score = _score(query, _runbook_text(runbook))
            if score <= 0:
                continue
            matches.append(
                _runbook_match(query, runbook, score=score, recall_sources=["keyword", "runbook"])
            )
        matches = sorted(matches, key=lambda item: item.score, reverse=True)
        return matches[:limit] if limit else matches

    def _incident_matches(
        self,
        query: str,
        incident_id: str,
        exact: bool = False,
    ) -> list[KnowledgeMatch]:
        matches: list[KnowledgeMatch] = []
        rca = self.store.get_rca_result(incident_id)
        if rca:
            matches.append(_incident_match(query, rca, "rca_result", exact=exact))
        report = self.store.get_agent_report(incident_id)
        if report:
            matches.append(_incident_match(query, report, "agent_report", exact=exact))
        return [item for item in matches if item.score > 0]

    def _latest_incident_matches(self, query: str) -> list[KnowledgeMatch]:
        matches: list[KnowledgeMatch] = []
        for rca in self.store.latest_rca_results(limit=10):
            match = _incident_match(query, rca, "rca_result")
            if match.score > 0:
                matches.append(match)
        for report in self.store.latest_agent_reports(limit=10):
            match = _incident_match(query, report, "agent_report")
            if match.score > 0:
                matches.append(match)
        return matches

    def _event_matches(self, query: str, incident_id: str) -> list[KnowledgeMatch]:
        if not hasattr(self.store, "latest_events"):
            return []
        rca = self.store.get_rca_result(incident_id)
        if not rca:
            return []
        event_ids = {
            item.get("event_id")
            for item in rca.get("timeline", [])
            if item.get("event_id")
        }
        if not event_ids:
            return []
        matches: list[KnowledgeMatch] = []
        for event in self.store.latest_events(limit=500):
            if event.get("event_id") not in event_ids:
                continue
            match = _incident_match(query, event, "normalized_event")
            if match.score > 0:
                matches.append(match)
        return matches

    def _graph_matches(self, query: str, incident_id: str) -> list[KnowledgeMatch]:
        if not hasattr(self.store, "get_incident_graph"):
            return []
        graph = self.store.get_incident_graph(incident_id)
        text = _flatten(graph)
        score = _score(query, text)
        if score <= 0:
            return []
        return [
            KnowledgeMatch(
                source="graph",
                title=f"Incident graph {incident_id}",
                score=score,
                content=text[:2000],
                ref_id=incident_id,
                attributes={"incident_id": incident_id},
                score_breakdown={"keyword_score": score},
                recall_sources=["graph", "keyword"],
            )
        ]


def _incident_match(
    query: str,
    item: dict[str, Any],
    source: str,
    exact: bool = False,
) -> KnowledgeMatch:
    title = str(item.get("summary") or item.get("incident_id") or source)
    text = _flatten(item)
    score = 1.0 if exact else _score(query, text)
    return KnowledgeMatch(
        source=source,
        title=title,
        score=score,
        content=text[:2000],
        ref_id=item.get("incident_id"),
        attributes={
            "incident_id": item.get("incident_id"),
            "service": item.get("service"),
            "env": item.get("env"),
            "severity": item.get("severity"),
        },
        score_breakdown={
            "keyword_score": score if not exact else 0.0,
            "exact_match_score": 1.0 if exact else 0.12 if item.get("incident_id") else 0.0,
        },
        recall_sources=["exact"] if exact else ["artifact", "keyword"],
    )


def _runbook_match(
    query: str,
    runbook: dict[str, Any],
    *,
    score: float,
    recall_sources: list[str],
) -> KnowledgeMatch:
    return KnowledgeMatch(
        source="runbook",
        title=str(runbook.get("title") or runbook.get("runbook_id")),
        score=score,
        content=_runbook_content(runbook),
        ref_id=runbook.get("runbook_id"),
        attributes=runbook,
        score_breakdown={
            "keyword_score": _score(query, _runbook_text(runbook)),
            "exact_match_score": 1.0 if score >= 1 else 0.0,
        },
        recall_sources=recall_sources,
    )


def _runbook_text(runbook: dict[str, Any]) -> str:
    return " ".join(
        [
            str(runbook.get("title", "")),
            " ".join(runbook.get("categories", [])),
            " ".join(runbook.get("keywords", [])),
            " ".join(runbook.get("steps", [])),
        ]
    )


def _runbook_content(runbook: dict[str, Any]) -> str:
    steps = runbook.get("steps") or []
    return "\n".join(
        [
            f"Runbook: {runbook.get('title')}",
            f"Categories: {', '.join(runbook.get('categories', []))}",
            f"Keywords: {', '.join(runbook.get('keywords', []))}",
            "Steps:",
            *[f"- {step}" for step in steps],
        ]
    )


def _score(query: str, text: str) -> float:
    query_terms = set(_tokens(query))
    text_terms = set(_tokens(text))
    if not query_terms or not text_terms:
        return 0.0
    overlap = query_terms.intersection(text_terms)
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(query_terms)
    density = len(overlap) / max(len(text_terms), 1)
    return round(min(coverage * 0.85 + density * 0.15, 1.0), 4)


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9_.-]+", value.lower()) if len(token) > 1]


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key}: {_flatten(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def _pipeline_trace(
    processed: ProcessedQuery,
    plan: RetrievalPlan,
    channel_traces: dict[str, Any],
    ranked: list[KnowledgeMatch],
    limit: int,
    ranker_strategy: str,
) -> dict[str, Any]:
    return {
        "preprocess": processed.trace(),
        "retrieval_plan": plan.trace(),
        "candidate_processing": {
            "channels": channel_traces,
            "total_deduped_count": sum(
                item.get("deduped_count", 0) for item in channel_traces.values()
            ),
        },
        "ranker": {
            "strategy": ranker_strategy,
            "input_count": len(ranked),
            "output_limit": limit,
            "top_sources": [match.source for match in ranked[:limit]],
            "top_score_breakdown": ranked[0].score_breakdown if ranked else {},
            "top_channel_ranks": (
                ranked[0].attributes.get("retrieval_channel_ranks", {}) if ranked else {}
            ),
        },
    }


def _runbook_ids(query: str) -> list[str]:
    return re.findall(r"\brb-[a-zA-Z0-9_.-]+\b", query)


def _limit_channel(matches: list[KnowledgeMatch], limit: int) -> list[KnowledgeMatch]:
    return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]


def _ensure_auxiliary_diversity(
    matches: list[KnowledgeMatch],
    *,
    window: int,
) -> list[KnowledgeMatch]:
    if len(matches) <= window:
        return matches
    head = matches[:window]
    if any(match.source in {"runbook", "runbook_step"} for match in head):
        return matches
    runbook = next(
        (match for match in matches[window:] if match.source in {"runbook", "runbook_step"}),
        None,
    )
    if not runbook:
        return matches
    without_runbook = [match for match in matches if match is not runbook]
    return [*without_runbook[:3], runbook, *without_runbook[3:]]
