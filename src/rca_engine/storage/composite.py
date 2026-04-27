from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from rca_engine.agents.runbook_catalog import RUNBOOKS
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
from rca_engine.rag.embedding import cosine_similarity
from rca_engine.storage.jsonl import JsonlStore
from rca_engine.storage.neo4j import Neo4jGraphStore
from rca_engine.storage.postgres import PostgresStore

logger = logging.getLogger(__name__)


class CompositeStorage:
    def __init__(
        self,
        jsonl: JsonlStore,
        postgres: PostgresStore | None = None,
        graph: Neo4jGraphStore | None = None,
    ) -> None:
        # JSONL is always present so the service can preserve inspectable local
        # artifacts even when structured stores are unavailable. PostgreSQL and
        # Neo4j are optional primary read paths, not peers in a multi-primary
        # replication design.
        self.jsonl = jsonl
        self.postgres = postgres
        self.graph = graph

    def save_event(self, event: NormalizedEvent) -> None:
        self._try_postgres("save_event", lambda store: store.save_event(event))
        self.jsonl.append("evidence.jsonl", event)

    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._try_postgres_read("latest_events", lambda store: store.latest_events(limit))
        return rows if rows is not None else self.jsonl.latest("evidence.jsonl", limit=limit)

    def save_candidate(self, candidate: IncidentCandidate) -> None:
        self._try_postgres("save_candidate", lambda store: store.save_candidate(candidate))
        self.jsonl.append("incident-candidates.jsonl", candidate)

    def latest_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._try_postgres_read("latest_candidates", lambda store: store.latest_candidates(limit))
        return rows if rows is not None else self.jsonl.latest("incident-candidates.jsonl", limit=limit)

    def save_rca_result(self, result: RCAResult) -> None:
        self._try_postgres("save_rca_result", lambda store: store.save_rca_result(result))
        self._try_graph("sync_rca_result", lambda graph: graph.sync_rca_result(result))
        self.jsonl.append("rca-results.jsonl", result)

    def latest_rca_results(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._try_postgres_read("latest_rca_results", lambda store: store.latest_rca_results(limit))
        return rows if rows is not None else self.jsonl.latest("rca-results.jsonl", limit=limit)

    def get_rca_result(self, incident_id: str) -> dict[str, Any] | None:
        row = self._try_postgres_read("get_rca_result", lambda store: store.get_rca_result(incident_id))
        if row is not None:
            return row
        for item in reversed(self.jsonl.latest("rca-results.jsonl", limit=1000)):
            if item.get("incident_id") == incident_id:
                return item
        return None

    def save_agent_report(self, report: RCAAgentReport) -> None:
        self._try_postgres("save_agent_report", lambda store: store.save_agent_report(report))
        self.jsonl.append("agent-reports.jsonl", report)

    def latest_agent_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._try_postgres_read("latest_agent_reports", lambda store: store.latest_agent_reports(limit))
        return rows if rows is not None else self.jsonl.latest("agent-reports.jsonl", limit=limit)

    def get_agent_report(self, incident_id: str) -> dict[str, Any] | None:
        row = self._try_postgres_read("get_agent_report", lambda store: store.get_agent_report(incident_id))
        if row is not None:
            return row
        for item in reversed(self.jsonl.latest("agent-reports.jsonl", limit=1000)):
            if item.get("incident_id") == incident_id:
                return item
        return None

    def list_runbooks(self) -> list[dict[str, Any]]:
        rows = self._try_postgres_read("list_runbooks", lambda store: store.list_runbooks())
        return rows if rows is not None else [_runbook_payload(runbook) for runbook in RUNBOOKS]

    def get_runbook(self, runbook_id: str) -> dict[str, Any] | None:
        row = self._try_postgres_read("get_runbook", lambda store: store.get_runbook(runbook_id))
        if row is not None:
            return row
        for runbook in RUNBOOKS:
            if runbook.runbook_id == runbook_id:
                return _runbook_payload(runbook)
        return None

    def save_rag_documents(self, documents: list[RAGDocument]) -> None:
        self._try_postgres("save_rag_documents", lambda store: store.save_rag_documents(documents))
        for document in documents:
            self.jsonl.append("rag-documents.jsonl", document)

    def save_historical_incident(self, incident: HistoricalIncident) -> None:
        self._try_postgres(
            "save_historical_incident",
            lambda store: store.save_historical_incident(incident),
        )
        self.jsonl.append("historical-incidents.jsonl", incident)

    def search_rag_documents(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = self._try_postgres_read(
            "search_rag_documents",
            lambda store: store.search_rag_documents(query, embedding, incident_id, limit),
        )
        if rows is not None:
            return rows
        return self._jsonl_rag_search(query, embedding, incident_id, limit)

    def save_rag_query_trace(self, trace: RAGQueryTrace) -> None:
        self._try_postgres("save_rag_query_trace", lambda store: store.save_rag_query_trace(trace))
        self.jsonl.append("rag-query-traces.jsonl", trace)

    def latest_rag_query_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._try_postgres_read(
            "latest_rag_query_traces",
            lambda store: store.latest_rag_query_traces(limit),
        )
        return rows if rows is not None else self.jsonl.latest("rag-query-traces.jsonl", limit=limit)

    def save_copilot_feedback(self, feedback: CopilotFeedback) -> None:
        self._try_postgres("save_copilot_feedback", lambda store: store.save_copilot_feedback(feedback))
        self.jsonl.append("copilot-feedback.jsonl", feedback)

    def latest_copilot_feedback(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._try_postgres_read(
            "latest_copilot_feedback",
            lambda store: store.latest_copilot_feedback(limit),
        )
        return rows if rows is not None else self.jsonl.latest("copilot-feedback.jsonl", limit=limit)

    def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        if self.graph and self.graph.available():
            try:
                return self.graph.get_incident_graph(incident_id)
            except Exception as exc:  # noqa: BLE001
                self._record_error("neo4j", "get_incident_graph", exc)
        return self._jsonl_graph(incident_id)

    def storage_health(self) -> dict[str, Any]:
        return {
            "jsonl": {"status": "ok", "output_dir": str(self.jsonl.output_dir)},
            "postgres": self.postgres.health() if self.postgres else {"status": "unavailable"},
            "neo4j": self.graph.health() if self.graph else {"status": "unavailable"},
        }

    def _try_postgres(self, operation: str, callback) -> None:
        if not self.postgres or not self.postgres.available():
            return
        try:
            callback(self.postgres)
        except Exception as exc:  # noqa: BLE001
            self._record_error("postgres", operation, exc)

    def _try_postgres_read(self, operation: str, callback):
        if not self.postgres or not self.postgres.available():
            return None
        try:
            return callback(self.postgres)
        except Exception as exc:  # noqa: BLE001
            self._record_error("postgres", operation, exc)
            return None

    def _try_graph(self, operation: str, callback) -> None:
        if not self.graph or not self.graph.available():
            return
        try:
            callback(self.graph)
        except Exception as exc:  # noqa: BLE001
            self._record_error("neo4j", operation, exc)

    def _record_error(self, component: str, operation: str, exc: Exception) -> None:
        logger.warning("%s storage operation failed during %s: %s", component, operation, exc)
        error_payload = {"component": component, "operation": operation, "error": str(exc)}
        self.jsonl.append("storage-errors.jsonl", error_payload)
        if self.postgres and component != "postgres":
            try:
                self.postgres.record_storage_error(component, operation, str(exc))
            except Exception:  # noqa: BLE001
                logger.debug("Failed to record storage error in PostgreSQL", exc_info=True)

    def _jsonl_graph(self, incident_id: str) -> dict[str, Any]:
        # The JSONL graph view is a degraded projection for inspection and basic
        # UI rendering when Neo4j is unavailable. It intentionally reconstructs a
        # minimal graph from stored RCA results instead of duplicating graph logic.
        result = self.get_rca_result(incident_id)
        if not result:
            return {"incident_id": incident_id, "nodes": [], "relationships": []}
        try:
            parsed = RCAResult(**result)
        except ValidationError:
            return {"incident_id": incident_id, "nodes": [], "relationships": []}

        nodes: dict[str, dict[str, Any]] = {
            parsed.incident_id: {
                "id": parsed.incident_id,
                "labels": ["Incident"],
                "properties": {
                    "service": parsed.service,
                    "env": parsed.env,
                    "severity": parsed.severity,
                    "summary": parsed.summary,
                },
            }
        }
        relationships: list[dict[str, Any]] = []
        for entry in parsed.timeline:
            nodes[entry.event_id] = {
                "id": entry.event_id,
                "labels": ["Event"],
                "properties": entry.model_dump(mode="json"),
            }
            relationships.append({"type": "HAS_EVIDENCE", "start": parsed.incident_id, "end": entry.event_id})
        for root in parsed.root_causes:
            nodes[root.hypothesis_id] = {
                "id": root.hypothesis_id,
                "labels": ["RootCause"],
                "properties": root.model_dump(mode="json"),
            }
            relationships.append({"type": "HAS_ROOT_CAUSE", "start": parsed.incident_id, "end": root.hypothesis_id})
        for link in parsed.causal_links:
            relationships.append(
                {
                    "type": link.relation,
                    "start": link.source_id,
                    "end": link.target_id,
                    "properties": link.model_dump(mode="json"),
                }
            )
        return {"incident_id": incident_id, "nodes": list(nodes.values()), "relationships": relationships}

    def _jsonl_rag_search(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query_terms = {term.lower() for term in query.split() if len(term) > 1}
        scored: list[dict[str, Any]] = []
        for document in self.jsonl.latest("rag-documents.jsonl", limit=5000):
            if incident_id and document.get("incident_id") != incident_id:
                continue
            scored.extend([_score_jsonl_document(document, query_terms, embedding)])
        if not incident_id:
            for incident in self.jsonl.latest("historical-incidents.jsonl", limit=5000):
                document = {
                    "document_id": f"historical:{incident.get('historical_incident_id')}",
                    "source_type": "historical_incident",
                    "ref_id": incident.get("historical_incident_id"),
                    "title": incident.get("summary"),
                    "content": incident.get("root_cause") or incident.get("summary"),
                    "service": incident.get("service"),
                    "env": incident.get("env"),
                    "severity": incident.get("severity"),
                    "embedding": incident.get("embedding", []),
                    "metadata": incident,
                }
                scored.extend([_score_jsonl_document(document, query_terms, embedding)])
        scored = [item for item in scored if item.get("score", 0) > 0]
        return sorted(scored, key=lambda row: row["score"], reverse=True)[:limit]


def _runbook_payload(runbook) -> dict[str, Any]:
    return {
        "runbook_id": runbook.runbook_id,
        "title": runbook.title,
        "categories": list(runbook.categories),
        "keywords": list(runbook.keywords),
        "steps": list(runbook.steps),
    }


def _score_jsonl_document(
    document: dict[str, Any],
    query_terms: set[str],
    embedding: list[float],
) -> dict[str, Any]:
    text = f"{document.get('title', '')} {document.get('content', '')}".lower()
    lexical = 0.0
    if query_terms:
        lexical = len([term for term in query_terms if term in text]) / len(query_terms)
    semantic = cosine_similarity(embedding, document.get("embedding", []))
    item = dict(document)
    item["score"] = round(max(lexical, semantic), 4)
    return item
