from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Verdict = Literal["improved", "neutral", "regressed", "needs_review"]


class EvaluationCase(BaseModel):
    query_id: str
    query: str = ""
    incident_id: str | None = None
    intent: str = "general"
    relevant_document_ids: list[str] = Field(default_factory=list)
    relevant_sources: list[str] = Field(default_factory=list)
    relevant_evidence_ids: list[str] = Field(default_factory=list)
    relevant_runbook_ids: list[str] = Field(default_factory=list)
    expected_root_cause_categories: list[str] = Field(default_factory=list)
    expected_root_cause: str | None = None
    label_source: str = "manual"
    review_status: str = "reviewed"
    dataset_split: str = "smoke"
    metric_slices: list[str] = Field(default_factory=list)
    severity: str | None = None


class RAGMetricBlock(BaseModel):
    query_count: int = 0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    citation_coverage: float = 0.0
    unsupported_answer_rate: float = 0.0
    p95_latency_ms: int = 0


class RCAMetricBlock(BaseModel):
    case_count: int = 0
    root_cause_at_1: float = 0.0
    root_cause_at_3: float = 0.0
    category_accuracy: float = 0.0
    evidence_support: float = 0.0
    unsupported_root_cause_rate: float = 0.0


class SliceMetricBlock(BaseModel):
    rag: RAGMetricBlock = Field(default_factory=RAGMetricBlock)
    rca: RCAMetricBlock = Field(default_factory=RCAMetricBlock)


class QueryEvaluationResult(BaseModel):
    query_id: str
    incident_id: str | None = None
    intent: str = "general"
    metric_slices: list[str] = Field(default_factory=list)
    top_refs: list[str] = Field(default_factory=list)
    top_sources: list[str] = Field(default_factory=list)
    retrieved_expected_ids: list[str] = Field(default_factory=list)
    missed_expected_ids: list[str] = Field(default_factory=list)
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    citation_coverage: float = 0.0
    unsupported: bool = False
    latency_ms: int = 0
    verification_status: str | None = None


class RCAEvaluationResult(BaseModel):
    query_id: str
    incident_id: str | None = None
    metric_slices: list[str] = Field(default_factory=list)
    expected_categories: list[str] = Field(default_factory=list)
    top_categories: list[str] = Field(default_factory=list)
    top_hypotheses: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missed_evidence_ids: list[str] = Field(default_factory=list)
    root_cause_at_1: float = 0.0
    root_cause_at_3: float = 0.0
    category_accuracy: float = 0.0
    evidence_support: float = 0.0
    unsupported_root_cause: bool = False


class ReplaySummary(BaseModel):
    input_event_count: int = 0
    extracted_event_count: int = 0
    candidate_count: int = 0
    rca_result_count: int = 0
    rag_document_count: int = 0
    incident_ids: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    dataset_version: str = "replay-v1"
    mode: str = "replay"
    rag: RAGMetricBlock = Field(default_factory=RAGMetricBlock)
    rca: RCAMetricBlock = Field(default_factory=RCAMetricBlock)
    slices: dict[str, SliceMetricBlock] = Field(default_factory=dict)
    queries: list[QueryEvaluationResult] = Field(default_factory=list)
    rca_cases: list[RCAEvaluationResult] = Field(default_factory=list)
    replay: ReplaySummary = Field(default_factory=ReplaySummary)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricDelta(BaseModel):
    baseline: float | int | bool | None = None
    candidate: float | int | bool | None = None
    delta: float | int | None = None


class CaseComparison(BaseModel):
    case_id: str
    incident_id: str | None = None
    kind: Literal["rag", "rca"]
    reason: str
    baseline: dict[str, Any] = Field(default_factory=dict)
    candidate: dict[str, Any] = Field(default_factory=dict)


class ComparisonReport(BaseModel):
    verdict: Verdict
    overall_delta: dict[str, MetricDelta] = Field(default_factory=dict)
    slice_delta: dict[str, dict[str, MetricDelta]] = Field(default_factory=dict)
    regressions: list[CaseComparison] = Field(default_factory=list)
    improvements: list[CaseComparison] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
