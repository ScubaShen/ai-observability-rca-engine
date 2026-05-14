from __future__ import annotations

from typing import Any

from rca_engine.hash_utils import stable_id
from rca_engine.models import RCAAgentReport, RCAResult, TypedEvidenceChunk


def chunks_from_rca_result(result: RCAResult) -> list[TypedEvidenceChunk]:
    chunks: list[TypedEvidenceChunk] = []
    for item in result.evidence:
        source_type = _source_type_for_event(item.event_type, item.signal_type)
        chunks.append(
            TypedEvidenceChunk(
                chunk_id=stable_id(
                    "typed_evidence_chunk",
                    {
                        "incident_id": result.incident_id,
                        "source_type": source_type,
                        "event_id": item.event_id,
                    },
                ),
                source_type=source_type,
                title=f"{item.signal_type} evidence for {result.incident_id}",
                content=_join_parts(
                    item.event_type,
                    item.signal_type,
                    item.category,
                    item.service,
                    item.severity,
                    item.summary,
                ),
                incident_id=result.incident_id,
                service=item.service or result.service,
                env=result.env,
                severity=item.severity,
                evidence_ids=[item.event_id],
                metadata={
                    "category": item.category,
                    "signal_type": item.signal_type,
                    "confidence": item.confidence,
                    "strength": item.strength,
                    "scoring_factors": item.scoring_factors,
                    **item.attributes,
                },
            )
        )

    for item in result.timeline:
        chunks.append(
            TypedEvidenceChunk(
                chunk_id=stable_id(
                    "typed_evidence_chunk",
                    {
                        "incident_id": result.incident_id,
                        "source_type": "timeline_event",
                        "event_id": item.event_id,
                    },
                ),
                source_type="timeline_event",
                title=f"Timeline event {item.event_id}",
                content=_join_parts(
                    item.event_time,
                    item.event_type,
                    item.service,
                    item.severity,
                    item.summary,
                    item.trace_id,
                    item.span_id,
                ),
                incident_id=result.incident_id,
                service=item.service or result.service,
                env=result.env,
                severity=item.severity,
                evidence_ids=[item.event_id],
                time_range={"start": item.event_time, "end": item.event_time},
                metadata={
                    "event_type": item.event_type,
                    "trace_id": item.trace_id,
                    "span_id": item.span_id,
                    **item.attributes,
                },
            )
        )

    for item in result.dependency_insights:
        chunks.append(
            TypedEvidenceChunk(
                chunk_id=stable_id(
                    "typed_evidence_chunk",
                    {
                        "incident_id": result.incident_id,
                        "source_type": "graph_edge",
                        "source": item.source_service,
                        "target": item.target,
                        "relation": item.relation,
                    },
                ),
                source_type="graph_edge",
                title=f"{item.source_service} {item.relation} {item.target}",
                content=_join_parts(
                    item.source_service,
                    item.relation,
                    item.target,
                    item.summary,
                    "suspect" if item.is_suspect else "",
                ),
                incident_id=result.incident_id,
                service=item.source_service or result.service,
                env=result.env,
                severity=result.severity,
                evidence_ids=item.evidence_event_ids,
                metadata={
                    "target": item.target,
                    "relation": item.relation,
                    "is_suspect": item.is_suspect,
                },
            )
        )

    return chunks


def chunks_from_runbook(runbook: dict[str, Any]) -> list[TypedEvidenceChunk]:
    chunks: list[TypedEvidenceChunk] = []
    runbook_id = str(runbook.get("runbook_id") or runbook.get("id") or "runbook")
    title = str(runbook.get("title") or runbook_id)
    steps = runbook.get("steps") or []
    for index, step in enumerate(steps, start=1):
        chunks.append(
            TypedEvidenceChunk(
                chunk_id=stable_id(
                    "typed_evidence_chunk",
                    {"runbook_id": runbook_id, "step": index, "title": title},
                ),
                source_type="runbook_step",
                title=f"{title} step {index}",
                content=_join_parts(
                    title,
                    " ".join(str(item) for item in runbook.get("categories", [])),
                    " ".join(str(item) for item in runbook.get("keywords", [])),
                    step,
                ),
                metadata={
                    "runbook_id": runbook_id,
                    "step_index": index,
                    "categories": runbook.get("categories", []),
                    "keywords": runbook.get("keywords", []),
                },
            )
        )
    return chunks


def chunks_from_agent_report(report: RCAAgentReport) -> list[TypedEvidenceChunk]:
    chunks: list[TypedEvidenceChunk] = []
    for index, finding in enumerate(report.agent_findings, start=1):
        chunks.append(
            TypedEvidenceChunk(
                chunk_id=stable_id(
                    "typed_evidence_chunk",
                    {
                        "incident_id": report.incident_id,
                        "source_type": "agent_finding",
                        "index": index,
                        "summary": finding.summary,
                    },
                ),
                source_type="agent_finding",
                title=f"{finding.finding_type} finding for {report.incident_id}",
                content=_join_parts(finding.finding_type, finding.summary),
                incident_id=report.incident_id,
                service=report.service,
                env=report.env,
                severity=report.severity,
                metadata=finding.model_dump(mode="json"),
            )
        )
    return chunks


def _source_type_for_event(event_type: str, signal_type: str) -> str:
    value = f"{event_type} {signal_type}".lower()
    if "metric" in value:
        return "evidence_metric"
    if "trace" in value or "span" in value:
        return "evidence_trace"
    return "evidence_log"


def _join_parts(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part not in {None, ""})
