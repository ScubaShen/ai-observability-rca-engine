from __future__ import annotations

from typing import Any

from rca_engine.hash_utils import stable_id
from rca_engine.models import (
    HistoricalIncident,
    RAGDocument,
    RCAAgentReport,
    RCAResult,
    TypedEvidenceChunk,
)
from rca_engine.rag.chunks import (
    chunks_from_agent_report,
    chunks_from_rca_result,
    chunks_from_runbook,
)
from rca_engine.rag.embedding import EmbeddingProvider, HashEmbeddingProvider, text_for_embedding


class RAGIndexer:
    def __init__(self, store, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.store = store
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()

    def index_runbooks(self) -> list[RAGDocument]:
        documents = []
        for runbook in self.store.list_runbooks():
            documents.append(self._runbook_document(runbook))
            documents.extend(self._chunk_documents(chunks_from_runbook(runbook), ref_id=str(runbook.get("runbook_id"))))
        self.store.save_rag_documents(documents)
        return documents

    def index_rca_result(self, result: RCAResult) -> list[RAGDocument]:
        documents = [
            self._rca_document(result),
            self._evidence_document(result),
        ]
        documents.extend(self._chunk_documents(chunks_from_rca_result(result), ref_id=result.incident_id))
        self.store.save_rag_documents(documents)
        return documents

    def index_agent_report(self, report: RCAAgentReport) -> list[RAGDocument]:
        documents = [self._agent_report_document(report)]
        documents.extend(self._chunk_documents(chunks_from_agent_report(report), ref_id=report.incident_id))
        self.store.save_rag_documents(documents)
        return documents

    def rebuild(self, limit: int = 200) -> dict[str, Any]:
        docs: list[RAGDocument] = []
        docs.extend(self.index_runbooks())
        for item in self.store.latest_rca_results(limit=limit):
            docs.extend(self.index_rca_result(RCAResult(**item)))
        for item in self.store.latest_agent_reports(limit=limit):
            docs.extend(self.index_agent_report(RCAAgentReport(**item)))
        return {"indexed_documents": len(docs), "embedding_model": self.embedding_provider.model_name}

    def promote_historical_incident(
        self,
        incident_id: str,
        confirmed_root_cause: str | None = None,
        notes: str | None = None,
    ) -> HistoricalIncident | None:
        row = self.store.get_rca_result(incident_id)
        if not row:
            return None
        result = RCAResult(**row)
        root_cause = confirmed_root_cause or _top_root_cause_text(result)
        evidence_ids = [item.event_id for item in result.evidence]
        content = text_for_embedding(
            result.summary,
            root_cause,
            " ".join(item.summary for item in result.evidence),
            " ".join(result.recommended_actions),
        )
        incident = HistoricalIncident(
            historical_incident_id=stable_id(
                "historical_incident",
                {"incident_id": incident_id, "root_cause": root_cause},
            ),
            source_incident_id=incident_id,
            service=result.service,
            env=result.env,
            severity=result.severity,
            summary=result.summary,
            root_cause=root_cause,
            evidence_event_ids=evidence_ids,
            embedding_model=self.embedding_provider.model_name,
            embedding=self.embedding_provider.embed(content),
            metadata={
                "source_incident_id": incident_id,
                "confidence": result.confidence,
                "notes": notes,
            },
        )
        self.store.save_historical_incident(incident)
        return incident

    def _runbook_document(self, runbook: dict[str, Any]) -> RAGDocument:
        content = text_for_embedding(
            runbook.get("title"),
            " ".join(runbook.get("categories", [])),
            " ".join(runbook.get("keywords", [])),
            " ".join(runbook.get("steps", [])),
        )
        return self._document(
            source_type="runbook",
            ref_id=str(runbook.get("runbook_id")),
            title=str(runbook.get("title")),
            content=content,
            metadata=runbook,
        )

    def _rca_document(self, result: RCAResult) -> RAGDocument:
        root_causes = " ".join(f"{root.title}: {root.description}" for root in result.root_causes)
        content = text_for_embedding(result.summary, root_causes, " ".join(result.recommended_actions))
        return self._document(
            source_type="rca_result",
            ref_id=result.incident_id,
            title=result.summary,
            content=content,
            incident_id=result.incident_id,
            service=result.service,
            env=result.env,
            severity=result.severity,
            metadata={
                "confidence": result.confidence,
                "evidence_event_ids": [item.event_id for item in result.evidence],
                "evidence_strength": "strong" if result.confidence >= 0.75 else "weak",
            },
        )

    def _evidence_document(self, result: RCAResult) -> RAGDocument:
        content = "\n".join(
            f"{item.event_type} {item.service} {item.severity}: {item.summary}"
            for item in result.evidence
        )
        return self._document(
            source_type="evidence_summary",
            ref_id=result.incident_id,
            title=f"Evidence for {result.incident_id}",
            content=content or result.summary,
            incident_id=result.incident_id,
            service=result.service,
            env=result.env,
            severity=result.severity,
            metadata={
                "event_ids": [item.event_id for item in result.evidence],
                "evidence_strength": "strong" if len(result.evidence) >= 2 else "weak",
            },
        )

    def _agent_report_document(self, report: RCAAgentReport) -> RAGDocument:
        findings = " ".join(f"{item.finding_type}: {item.summary}" for item in report.agent_findings)
        runbooks = " ".join(f"{item.title}: {' '.join(item.steps)}" for item in report.runbook_recommendations)
        content = text_for_embedding(report.summary, findings, runbooks, " ".join(report.follow_up_questions))
        return self._document(
            source_type="agent_report",
            ref_id=report.incident_id,
            title=report.summary,
            content=content,
            incident_id=report.incident_id,
            service=report.service,
            env=report.env,
            severity=report.severity,
            metadata={
                "source_rca_confidence": report.source_rca_confidence,
                "runbook_ids": [item.runbook_id for item in report.runbook_recommendations],
            },
        )

    def _document(
        self,
        *,
        source_type: str,
        ref_id: str,
        title: str,
        content: str,
        incident_id: str | None = None,
        service: str | None = None,
        env: str | None = None,
        severity: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RAGDocument:
        document_id = stable_id("rag_document", {"source_type": source_type, "ref_id": ref_id, "title": title})
        return RAGDocument(
            document_id=document_id,
            source_type=source_type,
            ref_id=ref_id,
            title=title,
            content=content,
            incident_id=incident_id,
            service=service,
            env=env,
            severity=severity,
            embedding_model=self.embedding_provider.model_name,
            embedding=self.embedding_provider.embed(content),
            metadata=metadata or {},
        )

    def _chunk_documents(
        self,
        chunks: list[TypedEvidenceChunk],
        *,
        ref_id: str,
    ) -> list[RAGDocument]:
        documents: list[RAGDocument] = []
        for chunk in chunks:
            metadata = {
                **chunk.metadata,
                "chunk_id": chunk.chunk_id,
                "chunk_kind": chunk.source_type,
                "evidence_event_ids": chunk.evidence_ids,
                "event_ids": chunk.evidence_ids,
                "time_range": chunk.time_range,
                "evidence_strength": "strong" if chunk.evidence_ids else "weak",
            }
            documents.append(
                self._document(
                    source_type=chunk.source_type,
                    ref_id=chunk.incident_id or ref_id,
                    title=chunk.title,
                    content=chunk.content,
                    incident_id=chunk.incident_id,
                    service=chunk.service,
                    env=chunk.env,
                    severity=chunk.severity,
                    metadata=metadata,
                )
            )
        return documents


def _top_root_cause_text(result: RCAResult) -> str:
    if not result.root_causes:
        return "Root cause is not confirmed."
    top = result.root_causes[0]
    return f"{top.title}: {top.description}"
