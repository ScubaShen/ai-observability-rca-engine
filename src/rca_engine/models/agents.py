from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rca_engine.models.common import Severity
from rca_engine.timeutils import now_utc_iso


class AgentFinding(BaseModel):
    agent_name: str
    finding_type: str
    confidence: float
    summary: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class RunbookRecommendation(BaseModel):
    runbook_id: str
    title: str
    match_reason: str
    confidence: float
    safety_level: str = "manual_runbook"
    steps: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)


class RCAAgentReport(BaseModel):
    incident_id: str
    schema_version: str = "1.0"
    status: str = "agent_analyzed"
    service: str
    env: str
    severity: Severity
    summary: str
    agent_findings: list[AgentFinding] = Field(default_factory=list)
    runbook_recommendations: list[RunbookRecommendation] = Field(default_factory=list)
    notification_draft: str
    follow_up_questions: list[str] = Field(default_factory=list)
    source_rca_confidence: float
    generated_at: str = Field(default_factory=now_utc_iso)
