from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

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

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - only relevant before container deps are installed.
    psycopg = None
    dict_row = None
    Jsonb = None

logger = logging.getLogger(__name__)


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def available(self) -> bool:
        return bool(self.dsn and psycopg is not None)

    def health(self) -> dict[str, object]:
        if not self.available():
            return {"status": "unavailable", "reason": "POSTGRES_DSN or psycopg is not configured"}
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1 as ok")
                    cur.fetchone()
            return {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": str(exc)}

    def save_event(self, event: NormalizedEvent) -> None:
        payload = _payload(event)
        self._execute(
            """
            insert into normalized_events (
                event_id, event_type, source_topic, event_time, service, env,
                severity, trace_id, span_id, correlation_keys, payload
            )
            values (
                %(event_id)s, %(event_type)s, %(source_topic)s, %(event_time)s,
                %(service)s, %(env)s, %(severity)s, %(trace_id)s, %(span_id)s,
                %(correlation_keys)s, %(payload)s
            )
            on conflict (event_id) do update set
                event_type = excluded.event_type,
                service = excluded.service,
                env = excluded.env,
                severity = excluded.severity,
                payload = excluded.payload
            """,
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "source_topic": event.source_topic,
                "event_time": event.event_time,
                "service": event.service,
                "env": event.env,
                "severity": event.severity,
                "trace_id": event.trace_id,
                "span_id": event.span_id,
                "correlation_keys": event.correlation_keys,
                "payload": payload,
            },
        )

    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._query_payloads("normalized_events", "received_at", limit)

    def save_candidate(self, candidate: IncidentCandidate) -> None:
        self._execute(
            """
            insert into incident_candidates (
                incident_id, status, service, env, severity, window_start,
                window_end, score, summary, payload
            )
            values (
                %(incident_id)s, %(status)s, %(service)s, %(env)s, %(severity)s,
                %(window_start)s, %(window_end)s, %(score)s, %(summary)s, %(payload)s
            )
            on conflict (incident_id) do update set
                status = excluded.status,
                severity = excluded.severity,
                score = excluded.score,
                summary = excluded.summary,
                payload = excluded.payload,
                updated_at = now()
            """,
            {
                "incident_id": candidate.incident_id,
                "status": candidate.status,
                "service": candidate.service,
                "env": candidate.env,
                "severity": candidate.severity,
                "window_start": candidate.window_start,
                "window_end": candidate.window_end,
                "score": candidate.score,
                "summary": candidate.summary,
                "payload": _payload(candidate),
            },
        )

    def latest_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._query_payloads("incident_candidates", "updated_at", limit)

    def save_rca_result(self, result: RCAResult) -> None:
        self._execute(
            """
            insert into rca_results (
                incident_id, service, env, severity, confidence, summary, payload
            )
            values (
                %(incident_id)s, %(service)s, %(env)s, %(severity)s,
                %(confidence)s, %(summary)s, %(payload)s
            )
            on conflict (incident_id) do update set
                service = excluded.service,
                env = excluded.env,
                severity = excluded.severity,
                confidence = excluded.confidence,
                summary = excluded.summary,
                payload = excluded.payload,
                updated_at = now()
            """,
            {
                "incident_id": result.incident_id,
                "service": result.service,
                "env": result.env,
                "severity": result.severity,
                "confidence": result.confidence,
                "summary": result.summary,
                "payload": _payload(result),
            },
        )

    def latest_rca_results(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._query_payloads("rca_results", "updated_at", limit)

    def get_rca_result(self, incident_id: str) -> dict[str, Any] | None:
        return self._query_one_payload("rca_results", "incident_id", incident_id)

    def save_agent_report(self, report: RCAAgentReport) -> None:
        self._execute(
            """
            insert into agent_reports (
                incident_id, service, env, severity, summary, payload
            )
            values (
                %(incident_id)s, %(service)s, %(env)s, %(severity)s,
                %(summary)s, %(payload)s
            )
            on conflict (incident_id) do update set
                service = excluded.service,
                env = excluded.env,
                severity = excluded.severity,
                summary = excluded.summary,
                payload = excluded.payload,
                updated_at = now()
            """,
            {
                "incident_id": report.incident_id,
                "service": report.service,
                "env": report.env,
                "severity": report.severity,
                "summary": report.summary,
                "payload": _payload(report),
            },
        )

    def latest_agent_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._query_payloads("agent_reports", "updated_at", limit)

    def get_agent_report(self, incident_id: str) -> dict[str, Any] | None:
        return self._query_one_payload("agent_reports", "incident_id", incident_id)

    def list_runbooks(self) -> list[dict[str, Any]]:
        rows = self._query_payloads("runbooks", "updated_at", 500)
        return rows or [_runbook_payload(runbook) for runbook in RUNBOOKS]

    def get_runbook(self, runbook_id: str) -> dict[str, Any] | None:
        row = self._query_one_payload("runbooks", "runbook_id", runbook_id)
        if row:
            return row
        for runbook in RUNBOOKS:
            if runbook.runbook_id == runbook_id:
                return _runbook_payload(runbook)
        return None

    def save_rag_documents(self, documents: list[RAGDocument]) -> None:
        for document in documents:
            self._execute(
                """
                insert into rag_documents (
                    document_id, source_type, ref_id, incident_id, service, env,
                    severity, title, content, embedding_model, embedding, metadata, payload
                )
                values (
                    %(document_id)s, %(source_type)s, %(ref_id)s, %(incident_id)s,
                    %(service)s, %(env)s, %(severity)s, %(title)s, %(content)s,
                    %(embedding_model)s, %(embedding)s::vector, %(metadata)s, %(payload)s
                )
                on conflict (document_id) do update set
                    source_type = excluded.source_type,
                    ref_id = excluded.ref_id,
                    incident_id = excluded.incident_id,
                    service = excluded.service,
                    env = excluded.env,
                    severity = excluded.severity,
                    title = excluded.title,
                    content = excluded.content,
                    embedding_model = excluded.embedding_model,
                    embedding = excluded.embedding,
                    metadata = excluded.metadata,
                    payload = excluded.payload,
                    updated_at = now()
                """,
                {
                    "document_id": document.document_id,
                    "source_type": document.source_type,
                    "ref_id": document.ref_id,
                    "incident_id": document.incident_id,
                    "service": document.service,
                    "env": document.env,
                    "severity": document.severity,
                    "title": document.title,
                    "content": document.content,
                    "embedding_model": document.embedding_model,
                    "embedding": _vector_literal(document.embedding),
                    "metadata": Jsonb(document.metadata) if Jsonb is not None else document.metadata,
                    "payload": _payload(document),
                },
            )

    def save_historical_incident(self, incident: HistoricalIncident) -> None:
        self._execute(
            """
            insert into historical_incidents (
                historical_incident_id, service, env, summary, root_cause, payload, embedding
            )
            values (
                %(historical_incident_id)s, %(service)s, %(env)s, %(summary)s,
                %(root_cause)s, %(payload)s, %(embedding)s::vector
            )
            on conflict (historical_incident_id) do update set
                service = excluded.service,
                env = excluded.env,
                summary = excluded.summary,
                root_cause = excluded.root_cause,
                payload = excluded.payload,
                embedding = excluded.embedding,
                updated_at = now()
            """,
            {
                "historical_incident_id": incident.historical_incident_id,
                "service": incident.service,
                "env": incident.env,
                "summary": incident.summary,
                "root_cause": incident.root_cause,
                "payload": _payload(incident),
                "embedding": _vector_literal(incident.embedding),
            },
        )

    def search_rag_documents(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        params = {
            "query": pattern,
            "embedding": _vector_literal(embedding),
            "incident_id": incident_id,
            "limit": limit,
        }
        incident_filter = "and (%(incident_id)s is null or incident_id = %(incident_id)s)"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    select payload,
                           greatest(
                             case when title ilike %(query)s or content ilike %(query)s then 0.72 else 0 end,
                             1 - (embedding <=> %(embedding)s::vector)
                           ) as score
                    from rag_documents
                    where embedding is not null
                    {incident_filter}
                    order by score desc, updated_at desc
                    limit %(limit)s
                    """,
                    params,
                )
                rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload"]
            payload["score"] = float(row["score"] or 0)
            results.append(payload)
        results.extend(self._search_historical_incidents(query, embedding, limit))
        results = sorted(results, key=lambda item: item.get("score", 0), reverse=True)
        return results[:limit]

    def _search_historical_incidents(
        self,
        query: str,
        embedding: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select historical_incident_id, service, env, summary, root_cause, payload,
                           greatest(
                             case when summary ilike %(query)s or coalesce(root_cause, '') ilike %(query)s then 0.72 else 0 end,
                             1 - (embedding <=> %(embedding)s::vector)
                           ) as score
                    from historical_incidents
                    where embedding is not null
                    order by score desc, updated_at desc
                    limit %(limit)s
                    """,
                    {
                        "query": pattern,
                        "embedding": _vector_literal(embedding),
                        "limit": limit,
                    },
                )
                rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload"]
            results.append(
                {
                    "document_id": f"historical:{row['historical_incident_id']}",
                    "source_type": "historical_incident",
                    "ref_id": row["historical_incident_id"],
                    "incident_id": None,
                    "service": row["service"],
                    "env": row["env"],
                    "severity": payload.get("severity"),
                    "title": row["summary"],
                    "content": row["root_cause"] or row["summary"],
                    "score": float(row["score"] or 0),
                    "metadata": payload,
                }
            )
        return results

    def save_rag_query_trace(self, trace: RAGQueryTrace) -> None:
        self._execute(
            """
            insert into rag_query_traces (
                query_id, incident_id, question, intent, final_answer, latency_ms,
                token_cost, cache_hit, response_path, payload
            )
            values (
                %(query_id)s, %(incident_id)s, %(question)s, %(intent)s,
                %(final_answer)s, %(latency_ms)s, %(token_cost)s,
                %(cache_hit)s, %(response_path)s, %(payload)s
            )
            on conflict (query_id) do update set
                payload = excluded.payload
            """,
            {
                "query_id": trace.query_id,
                "incident_id": trace.incident_id,
                "question": trace.question,
                "intent": trace.intent,
                "final_answer": trace.final_answer,
                "latency_ms": trace.latency_ms,
                "token_cost": trace.token_cost,
                "cache_hit": trace.cache_hit,
                "response_path": trace.response_path,
                "payload": _payload(trace),
            },
        )

    def latest_rag_query_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._query_payloads("rag_query_traces", "created_at", limit)

    def save_copilot_feedback(self, feedback: CopilotFeedback) -> None:
        self._execute(
            """
            insert into copilot_feedback (
                feedback_id, query_id, incident_id, rating, comment,
                correct_root_cause, correct_runbook_id, payload
            )
            values (
                %(feedback_id)s, %(query_id)s, %(incident_id)s, %(rating)s,
                %(comment)s, %(correct_root_cause)s, %(correct_runbook_id)s, %(payload)s
            )
            on conflict (feedback_id) do update set
                rating = excluded.rating,
                comment = excluded.comment,
                payload = excluded.payload
            """,
            {
                "feedback_id": feedback.feedback_id,
                "query_id": feedback.query_id,
                "incident_id": feedback.incident_id,
                "rating": feedback.rating,
                "comment": feedback.comment,
                "correct_root_cause": feedback.correct_root_cause,
                "correct_runbook_id": feedback.correct_runbook_id,
                "payload": _payload(feedback),
            },
        )

    def latest_copilot_feedback(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._query_payloads("copilot_feedback", "created_at", limit)

    def record_storage_error(self, component: str, operation: str, error: str) -> None:
        if not self.available():
            return
        try:
            self._execute(
                """
                insert into storage_errors (component, operation, error)
                values (%(component)s, %(operation)s, %(error)s)
                """,
                {"component": component, "operation": operation, "error": error},
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to record storage error", exc_info=True)

    def _connect(self):
        if not self.available():
            raise RuntimeError("PostgreSQL is not configured")
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _execute(self, sql: str, params: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    def _query_payloads(self, table: str, order_column: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"select payload from {table} order by {order_column} desc limit %(limit)s",
                    {"limit": limit},
                )
                rows = cur.fetchall()
        return [row["payload"] for row in reversed(rows)]

    def _query_one_payload(self, table: str, key_column: str, value: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"select payload from {table} where {key_column} = %(value)s order by updated_at desc limit 1",
                    {"value": value},
                )
                row = cur.fetchone()
        return row["payload"] if row else None


def _payload(item: BaseModel) -> Any:
    data = item.model_dump(mode="json")
    return Jsonb(data) if Jsonb is not None else data


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _runbook_payload(runbook) -> dict[str, Any]:
    return {
        "runbook_id": runbook.runbook_id,
        "title": runbook.title,
        "categories": list(runbook.categories),
        "keywords": list(runbook.keywords),
        "steps": list(runbook.steps),
    }
