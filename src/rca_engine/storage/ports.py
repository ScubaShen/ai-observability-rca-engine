from __future__ import annotations

from typing import Protocol

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


class EvidenceRepository(Protocol):
    def save_event(self, event: NormalizedEvent) -> None: ...

    def latest_events(self, limit: int = 50) -> list[dict]: ...


class IncidentRepository(Protocol):
    def save_candidate(self, candidate: IncidentCandidate) -> None: ...

    def latest_candidates(self, limit: int = 50) -> list[dict]: ...


class RCAResultRepository(Protocol):
    def save_rca_result(self, result: RCAResult) -> None: ...

    def latest_rca_results(self, limit: int = 20) -> list[dict]: ...

    def get_rca_result(self, incident_id: str) -> dict | None: ...


class AgentReportRepository(Protocol):
    def save_agent_report(self, report: RCAAgentReport) -> None: ...

    def latest_agent_reports(self, limit: int = 20) -> list[dict]: ...

    def get_agent_report(self, incident_id: str) -> dict | None: ...


class RunbookRepository(Protocol):
    def list_runbooks(self) -> list[dict]: ...

    def get_runbook(self, runbook_id: str) -> dict | None: ...


class RAGRepository(Protocol):
    def save_rag_documents(self, documents: list[RAGDocument]) -> None: ...

    def save_historical_incident(self, incident: HistoricalIncident) -> None: ...

    def search_rag_documents(
        self,
        query: str,
        embedding: list[float],
        incident_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]: ...

    def save_rag_query_trace(self, trace: RAGQueryTrace) -> None: ...

    def latest_rag_query_traces(self, limit: int = 50) -> list[dict]: ...

    def save_copilot_feedback(self, feedback: CopilotFeedback) -> None: ...

    def latest_copilot_feedback(self, limit: int = 50) -> list[dict]: ...


class GraphRepository(Protocol):
    def sync_rca_result(self, result: RCAResult) -> None: ...

    def get_incident_graph(self, incident_id: str) -> dict: ...

    def health(self) -> dict: ...
