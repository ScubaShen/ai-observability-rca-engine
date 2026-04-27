from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rca_engine.models.common import EvidenceRef, Severity
from rca_engine.timeutils import now_utc_iso


class NormalizedEvent(BaseModel):
    event_id: str
    schema_version: str = "1.0"
    event_type: str
    source_topic: str
    event_time: str
    ingest_time: str = Field(default_factory=now_utc_iso)
    service: str = "unknown"
    env: str = "unknown"
    severity: Severity = "info"
    trace_id: str | None = None
    span_id: str | None = None
    correlation_keys: list[str] = Field(default_factory=list)
    summary: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class IncidentCandidate(BaseModel):
    incident_id: str
    schema_version: str = "1.0"
    status: str = "candidate"
    service: str
    env: str
    severity: Severity
    window_start: str
    window_end: str
    score: float
    summary: str
    event_ids: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    correlation_keys: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_utc_iso)
    updated_at: str = Field(default_factory=now_utc_iso)


class DeadLetterEvent(BaseModel):
    event_id: str
    schema_version: str = "1.0"
    source_topic: str
    ingest_time: str = Field(default_factory=now_utc_iso)
    reason: str
    payload_size_bytes: int
    attributes: dict[str, Any] = Field(default_factory=dict)
