from __future__ import annotations

import re
from typing import Any

from rca_engine.models import KnowledgeMatch
from rca_engine.rag.candidates import CandidateProcessor
from rca_engine.rag.embedding import HashEmbeddingProvider
from rca_engine.rag.preprocessor import ProcessedQuery, QueryPreprocessor
from rca_engine.rag.query import QueryIntent
from rca_engine.rag.ranker import rerank


class KnowledgeRetriever:
    def __init__(self, store, embedding_provider: HashEmbeddingProvider | None = None) -> None:
        self.store = store
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self.preprocessor = QueryPreprocessor()
        self.candidate_processor = CandidateProcessor()

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
        candidates: list[KnowledgeMatch] = []
        retrieval_query = processed.rewritten_query
        candidates.extend(self._rag_document_matches(retrieval_query, incident_id, limit=max(limit * 4, 20)))
        candidates.extend(self._runbook_matches(retrieval_query))
        if incident_id:
            candidates.extend(self._incident_matches(retrieval_query, incident_id))
            candidates.extend(self._event_matches(retrieval_query, incident_id))
            candidates.extend(self._graph_matches(retrieval_query, incident_id))
        else:
            candidates.extend(self._latest_incident_matches(retrieval_query))

        processed_candidates = self.candidate_processor.process(candidates)
        ranked = rerank(processed_candidates.matches, processed.intent)
        pipeline_trace = _pipeline_trace(processed, processed_candidates.trace, ranked, limit)
        return processed.intent, ranked[:limit], pipeline_trace

    def search_with_intent(
        self,
        query: str,
        incident_id: str | None = None,
        limit: int = 5,
    ) -> tuple[QueryIntent, list[KnowledgeMatch]]:
        intent, matches, _ = self.search_with_pipeline(query, incident_id=incident_id, limit=limit)
        return intent, matches

    def _rag_document_matches(
        self,
        query: str,
        incident_id: str | None,
        limit: int,
    ) -> list[KnowledgeMatch]:
        if not hasattr(self.store, "search_rag_documents"):
            return []
        embedding = self.embedding_provider.embed(query)
        rows = self.store.search_rag_documents(query, embedding, incident_id=incident_id, limit=limit)
        matches: list[KnowledgeMatch] = []
        for row in rows:
            matches.append(
                KnowledgeMatch(
                    source=str(row.get("source_type") or "rag_document"),
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
                    },
                    recall_sources=list(row.get("recall_sources") or ["semantic"]),
                )
            )
        return matches

    def _runbook_matches(self, query: str) -> list[KnowledgeMatch]:
        matches: list[KnowledgeMatch] = []
        for runbook in self.store.list_runbooks():
            text = " ".join(
                [
                    str(runbook.get("title", "")),
                    " ".join(runbook.get("categories", [])),
                    " ".join(runbook.get("keywords", [])),
                    " ".join(runbook.get("steps", [])),
                ]
            )
            score = _score(query, text)
            if score <= 0:
                continue
            matches.append(
                KnowledgeMatch(
                    source="runbook",
                    title=str(runbook.get("title") or runbook.get("runbook_id")),
                    score=score,
                    content=_runbook_content(runbook),
                    ref_id=runbook.get("runbook_id"),
                    attributes=runbook,
                    score_breakdown={"keyword_score": score},
                    recall_sources=["keyword", "runbook_catalog"],
                )
            )
        return matches

    def _incident_matches(self, query: str, incident_id: str) -> list[KnowledgeMatch]:
        matches: list[KnowledgeMatch] = []
        rca = self.store.get_rca_result(incident_id)
        if rca:
            matches.append(_incident_match(query, rca, "rca_result"))
        report = self.store.get_agent_report(incident_id)
        if report:
            matches.append(_incident_match(query, report, "agent_report"))
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
        event_ids = {item.get("event_id") for item in rca.get("timeline", []) if item.get("event_id")}
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


def _incident_match(query: str, item: dict[str, Any], source: str) -> KnowledgeMatch:
    title = str(item.get("summary") or item.get("incident_id") or source)
    text = _flatten(item)
    return KnowledgeMatch(
        source=source,
        title=title,
        score=_score(query, text),
        content=text[:2000],
        ref_id=item.get("incident_id"),
        attributes={"incident_id": item.get("incident_id"), "service": item.get("service")},
        score_breakdown={"keyword_score": _score(query, text), "exact_match_score": 0.12 if item.get("incident_id") else 0.0},
        recall_sources=["exact", "keyword"],
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
    candidate_trace: dict[str, Any],
    ranked: list[KnowledgeMatch],
    limit: int,
) -> dict[str, Any]:
    return {
        "preprocess": processed.trace(),
        "candidate_processing": candidate_trace,
        "ranker": {
            "strategy": "weighted_deterministic",
            "input_count": len(ranked),
            "output_limit": limit,
            "top_sources": [match.source for match in ranked[:limit]],
            "top_score_breakdown": ranked[0].score_breakdown if ranked else {},
        },
    }
