from __future__ import annotations

import re
from typing import Any

from rca_engine.models import (
    CopilotFeedback,
    HistoricalIncident,
    IncidentCandidate,
    NormalizedEvent,
    RAGDocument,
    RAGQueryTrace,
    RCAAgentReport,
    RCAResult,
)


class ReplayStore:
    def __init__(self, runbooks: list[dict[str, Any]] | None = None) -> None:
        self.runbooks = list(runbooks or [])
        self.events: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.rca_results: dict[str, dict[str, Any]] = {}
        self.agent_reports: dict[str, dict[str, Any]] = {}
        self.rag_documents: dict[str, dict[str, Any]] = {}
        self.historical_incidents: dict[str, dict[str, Any]] = {}
        self.query_traces: list[dict[str, Any]] = []
        self.feedback: list[dict[str, Any]] = []

    def save_event(self, event: NormalizedEvent) -> None:
        self.events[event.event_id] = event.model_dump(mode="json")

    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self.events.values())[-limit:]

    def search_events(
        self,
        *,
        q: str | None = None,
        service: str | None = None,
        env: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        event_time_from: str | None = None,
        event_time_to: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        page: int | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        del event_time_from, event_time_to, cursor, page, page_size
        rows = list(self.events.values())
        if service:
            rows = [item for item in rows if item.get("service") == service]
        if env:
            rows = [item for item in rows if item.get("env") == env]
        if severity:
            rows = [item for item in rows if item.get("severity") == severity]
        if event_type:
            rows = [item for item in rows if item.get("event_type") == event_type]
        if trace_id:
            rows = [item for item in rows if item.get("trace_id") == trace_id]
        if q:
            terms = set(_tokens(q))
            rows = [item for item in rows if terms.intersection(_tokens(_flatten(item)))]
        return {"items": rows[:limit], "next_cursor": None}

    def save_candidate(self, candidate: IncidentCandidate) -> None:
        self.candidates[candidate.incident_id] = candidate.model_dump(mode="json")

    def latest_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self.candidates.values())[-limit:]

    def save_rca_result(self, result: RCAResult) -> None:
        self.rca_results[result.incident_id] = result.model_dump(mode="json")

    def latest_rca_results(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self.rca_results.values())[-limit:]

    def get_rca_result(self, incident_id: str) -> dict[str, Any] | None:
        return self.rca_results.get(incident_id)

    def save_agent_report(self, report: RCAAgentReport) -> None:
        self.agent_reports[report.incident_id] = report.model_dump(mode="json")

    def latest_agent_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self.agent_reports.values())[-limit:]

    def get_agent_report(self, incident_id: str) -> dict[str, Any] | None:
        return self.agent_reports.get(incident_id)

    def list_runbooks(self) -> list[dict[str, Any]]:
        return list(self.runbooks)

    def get_runbook(self, runbook_id: str) -> dict[str, Any] | None:
        for runbook in self.runbooks:
            if runbook.get("runbook_id") == runbook_id:
                return runbook
        return None

    def save_rag_documents(self, documents: list[RAGDocument]) -> None:
        for document in documents:
            self.rag_documents[document.document_id] = document.model_dump(mode="json")

    def save_historical_incident(self, incident: HistoricalIncident) -> None:
        self.historical_incidents[incident.historical_incident_id] = incident.model_dump(mode="json")

    def search_rag_documents(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        keyword_rows = self.search_rag_documents_by_channel(
            query,
            embedding,
            incident_id=incident_id,
            limit=limit,
            channel="keyword",
        )
        semantic_rows = self.search_rag_documents_by_channel(
            query,
            embedding,
            incident_id=incident_id,
            limit=limit,
            channel="semantic",
        )
        historical_rows = self.search_rag_documents_by_channel(
            query,
            embedding,
            incident_id=None,
            limit=limit,
            channel="historical",
        )
        return _merge_search_rows([*keyword_rows, *semantic_rows, *historical_rows])[:limit]

    def search_rag_documents_by_channel(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None = None,
        limit: int = 10,
        channel: str = "semantic",
    ) -> list[dict[str, Any]]:
        del embedding
        rows: list[dict[str, Any]] = []
        if channel != "historical":
            for document in self.rag_documents.values():
                if incident_id and document.get("incident_id") not in {incident_id, None}:
                    continue
                keyword_score = (
                    _score(query, _document_text(document)) if channel == "keyword" else 0.0
                )
                semantic_score = (
                    _score(query, _document_text(document)) if channel != "keyword" else 0.0
                )
                if (
                    semantic_score <= 0
                    and incident_id
                    and document.get("incident_id") == incident_id
                ):
                    semantic_score = 0.2
                score = max(keyword_score, semantic_score)
                if score <= 0:
                    continue
                row = dict(document)
                row["keyword_score"] = keyword_score
                row["semantic_score"] = semantic_score
                row["score"] = score
                row["recall_sources"] = [
                    source
                    for source, value in {
                        "keyword": keyword_score,
                        "semantic": semantic_score,
                    }.items()
                    if value > 0
                ] or [channel]
                rows.append(row)
        if channel in {"historical", "semantic"}:
            for incident in self.historical_incidents.values():
                score = _score(query, _flatten(incident))
                if score <= 0:
                    continue
                rows.append(
                    {
                        "document_id": incident.get("historical_incident_id"),
                        "source_type": "historical_incident",
                        "ref_id": incident.get("historical_incident_id"),
                        "incident_id": incident.get("source_incident_id"),
                        "service": incident.get("service"),
                        "env": incident.get("env"),
                        "severity": incident.get("severity"),
                        "title": incident.get("summary"),
                        "content": incident.get("root_cause") or incident.get("summary"),
                        "metadata": {
                            **(incident.get("metadata") or {}),
                            "event_ids": incident.get("evidence_event_ids") or [],
                        },
                        "keyword_score": 0.0,
                        "semantic_score": score,
                        "score": score,
                        "recall_sources": ["historical_incident", "semantic"],
                    }
                )
        return sorted(rows, key=lambda item: item.get("score", 0), reverse=True)[:limit]

    def save_rag_query_trace(self, trace: RAGQueryTrace) -> None:
        self.query_traces.append(trace.model_dump(mode="json"))

    def latest_rag_query_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.query_traces[-limit:]

    def save_copilot_feedback(self, feedback: CopilotFeedback) -> None:
        self.feedback.append(feedback.model_dump(mode="json"))

    def latest_copilot_feedback(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.feedback[-limit:]

    def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        result = self.rca_results.get(incident_id)
        if not result:
            return {"incident_id": incident_id, "nodes": [], "relationships": []}
        nodes = [
            {"id": item.get("event_id"), "labels": ["Event"], "summary": item.get("summary")}
            for item in result.get("timeline", [])
        ]
        for root in result.get("root_causes", []):
            nodes.append(
                {
                    "id": root.get("hypothesis_id"),
                    "labels": ["RootCause"],
                    "category": root.get("category"),
                    "title": root.get("title"),
                }
            )
        relationships = [item for item in result.get("causal_links", [])]
        return {"incident_id": incident_id, "nodes": nodes, "relationships": relationships}


def _document_text(document: dict[str, Any]) -> str:
    metadata = document.get("metadata") or {}
    return " ".join(
        [
            str(document.get("title", "")),
            str(document.get("content", "")),
            str(document.get("source_type", "")),
            " ".join(str(value) for value in metadata.values() if not isinstance(value, list)),
            " ".join(
                str(item)
                for value in metadata.values()
                if isinstance(value, list)
                for item in value
            ),
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


def _merge_search_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("source_type") or "rag_document"),
            str(row.get("ref_id") or row.get("document_id") or row.get("title")),
        )
        existing = merged.get(key)
        if not existing:
            merged[key] = dict(row)
            continue
        existing["keyword_score"] = max(
            float(existing.get("keyword_score") or 0),
            float(row.get("keyword_score") or 0),
        )
        existing["semantic_score"] = max(
            float(existing.get("semantic_score") or 0),
            float(row.get("semantic_score") or 0),
        )
        existing["score"] = max(
            float(existing.get("score") or 0),
            float(row.get("score") or 0),
        )
        existing["recall_sources"] = sorted(
            set(existing.get("recall_sources") or []).union(row.get("recall_sources") or [])
        )
    return sorted(merged.values(), key=lambda item: item.get("score", 0), reverse=True)
