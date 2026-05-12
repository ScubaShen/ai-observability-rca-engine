from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class EvaluationFixtureStore:
    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir
        self.runbooks = _load_json(fixture_dir / "runbooks.json")
        self.rag_documents = _load_json(fixture_dir / "rag_documents.json")
        self.rca_results = _load_json(fixture_dir / "rca_results.json")
        self.agent_reports = _load_json(fixture_dir / "agent_reports.json")
        self.incident_graphs = _load_json(fixture_dir / "incident_graphs.json")
        self.events = _load_json(fixture_dir / "events.json")
        self.traces: list[Any] = []

    def list_runbooks(self) -> list[dict[str, Any]]:
        return list(self.runbooks)

    def get_rca_result(self, incident_id: str) -> dict[str, Any] | None:
        return _by_incident_id(self.rca_results, incident_id)

    def get_agent_report(self, incident_id: str) -> dict[str, Any] | None:
        return _by_incident_id(self.agent_reports, incident_id)

    def latest_rca_results(self, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.rca_results)[-limit:]

    def latest_agent_reports(self, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.agent_reports)[-limit:]

    def latest_events(self, limit: int = 500) -> list[dict[str, Any]]:
        return list(self.events)[-limit:]

    def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        for graph in self.incident_graphs:
            if graph.get("incident_id") == incident_id:
                return graph
        return {"incident_id": incident_id, "nodes": [], "relationships": []}

    def search_rag_documents(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        del embedding
        rows: list[dict[str, Any]] = []
        for document in self.rag_documents:
            if incident_id and document.get("incident_id") not in {incident_id, None}:
                continue
            keyword_score = _score(query, _document_text(document))
            semantic_score = keyword_score
            if keyword_score <= 0 and incident_id and document.get("incident_id") == incident_id:
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
                for source, value in {"keyword": keyword_score, "semantic": semantic_score}.items()
                if value > 0
            ] or ["semantic"]
            rows.append(row)
        return sorted(rows, key=lambda item: item.get("score", 0), reverse=True)[:limit]

    def save_rag_query_trace(self, trace: Any) -> None:
        self.traces.append(trace)


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    return list(data.get("items", [])) if isinstance(data, dict) else []


def _by_incident_id(items: list[dict[str, Any]], incident_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("incident_id") == incident_id:
            return item
    return None


def _document_text(document: dict[str, Any]) -> str:
    metadata = document.get("metadata") or {}
    return " ".join(
        [
            str(document.get("title", "")),
            str(document.get("content", "")),
            str(document.get("source_type", "")),
            " ".join(str(value) for value in metadata.values() if not isinstance(value, list)),
            " ".join(str(item) for value in metadata.values() if isinstance(value, list) for item in value),
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
