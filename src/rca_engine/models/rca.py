from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rca_engine.models.common import EvidenceRef, Severity
from rca_engine.timeutils import now_utc_iso


class TimelineEntry(BaseModel):
    event_id: str
    event_time: str
    event_type: str
    service: str
    severity: Severity
    summary: str
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvidenceFinding(BaseModel):
    event_id: str
    event_type: str
    category: str
    signal_type: str
    service: str
    severity: Severity
    summary: str
    confidence: float
    attributes: dict[str, Any] = Field(default_factory=dict)


class ServiceDependencyInsight(BaseModel):
    source_service: str
    target: str
    relation: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    is_suspect: bool = False
    summary: str


class CausalLink(BaseModel):
    link_id: str | None = None
    source_id: str
    target_id: str
    relation: str
    confidence: float
    reason: str


class RootCauseHypothesis(BaseModel):
    hypothesis_id: str
    title: str
    description: str
    category: str
    confidence: float
    supporting_event_ids: list[str] = Field(default_factory=list)
    causal_link_ids: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class RCAResult(BaseModel):
    incident_id: str
    schema_version: str = "1.0"
    status: str = "analyzed"
    service: str
    env: str
    severity: Severity
    summary: str
    confidence: float
    root_causes: list[RootCauseHypothesis] = Field(default_factory=list)
    causal_links: list[CausalLink] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    evidence: list[EvidenceFinding] = Field(default_factory=list)
    dependency_insights: list[ServiceDependencyInsight] = Field(default_factory=list)
    impacted_services: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_utc_iso)
