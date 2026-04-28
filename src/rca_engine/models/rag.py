from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from rca_engine.models.common import Severity
from rca_engine.timeutils import now_utc_iso


class KnowledgeMatch(BaseModel):
    source: str
    title: str
    score: float
    content: str
    ref_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    recall_sources: list[str] = Field(default_factory=list)


class CopilotRequest(BaseModel):
    question: str
    incident_id: str | None = None
    limit: int = 5
    mode: Literal["auto", "fast", "deep"] = "auto"


class Citation(BaseModel):
    source: str
    ref_id: str | None = None
    title: str
    evidence_ids: list[str] = Field(default_factory=list)
    quote: str | None = None


class VerificationResult(BaseModel):
    status: Literal["confirmed", "likely", "weak", "missing_evidence"]
    citation_coverage: float
    hallucination_risk: Literal["low", "medium", "high"]
    blocked_terms: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CopilotResponse(BaseModel):
    question: str
    answer: str
    incident_id: str | None = None
    confidence: float
    root_cause_summary: str | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_manual_runbooks: list[str] = Field(default_factory=list)
    confidence_rationale: str | None = None
    matches: list[KnowledgeMatch] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    verification: VerificationResult | None = None
    suggested_followups: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    cache_hit: bool = False
    response_path: Literal["fast", "deep", "deep_stream", "fallback"] = "fallback"
    generated_at: str = Field(default_factory=now_utc_iso)


class RAGDocument(BaseModel):
    document_id: str
    source_type: str
    ref_id: str
    title: str
    content: str
    incident_id: str | None = None
    service: str | None = None
    env: str | None = None
    severity: Severity | None = None
    embedding_model: str = "hash-v1"
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=now_utc_iso)


class HistoricalIncident(BaseModel):
    historical_incident_id: str
    source_incident_id: str
    service: str
    env: str
    severity: Severity
    summary: str
    root_cause: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    embedding_model: str = "hash-v1"
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_utc_iso)


class HistoricalIncidentPromotionRequest(BaseModel):
    confirmed_root_cause: str | None = None
    notes: str | None = None


class RAGQueryTrace(BaseModel):
    query_id: str
    question: str
    incident_id: str | None = None
    intent: str = "general"
    retrieved_documents: list[KnowledgeMatch] = Field(default_factory=list)
    selected_context: list[Citation] = Field(default_factory=list)
    final_answer: str
    latency_ms: int
    token_cost: float = 0.0
    cache_hit: bool = False
    response_path: str = "fallback"
    verification: VerificationResult | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    reasoning_effort: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    recall_source_counts: dict[str, int] = Field(default_factory=dict)
    rerank_strategy: str = "deterministic"
    top_score_breakdown: dict[str, float] = Field(default_factory=dict)
    fallback_reason: str | None = None
    created_at: str = Field(default_factory=now_utc_iso)


class CopilotFeedback(BaseModel):
    feedback_id: str
    query_id: str | None = None
    incident_id: str | None = None
    rating: Literal["useful", "not_useful", "incorrect", "unsafe", "other"]
    comment: str | None = None
    correct_root_cause: str | None = None
    correct_runbook_id: str | None = None
    created_at: str = Field(default_factory=now_utc_iso)


class PostmortemDraft(BaseModel):
    incident_id: str
    title: str
    summary: str
    impact: str
    timeline: list[str] = Field(default_factory=list)
    root_cause: str
    contributing_factors: list[str] = Field(default_factory=list)
    detection: str
    manual_followups: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_utc_iso)
