from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvaluationQuery(BaseModel):
    query_id: str
    query: str
    incident_id: str | None = None
    intent: str = "general"
    relevant_document_ids: list[str] = Field(default_factory=list)
    relevant_sources: list[str] = Field(default_factory=list)
    relevant_evidence_ids: list[str] = Field(default_factory=list)
    relevant_runbook_ids: list[str] = Field(default_factory=list)
    expected_root_cause_categories: list[str] = Field(default_factory=list)


class MetricBlock(BaseModel):
    query_count: int = 0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    citation_coverage: float = 0.0
    unsupported_answer_rate: float = 0.0
    p95_latency_ms: int = 0


class RCAMetricBlock(BaseModel):
    case_count: int = 0
    root_cause_at_3: float = 0.0


class QueryEvaluationResult(BaseModel):
    query_id: str
    top_refs: list[str] = Field(default_factory=list)
    top_sources: list[str] = Field(default_factory=list)
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    citation_coverage: float = 0.0
    unsupported: bool = False
    latency_ms: int = 0
    verification_status: str | None = None


class EvaluationReport(BaseModel):
    dataset_version: str = "v1-baseline"
    rag: MetricBlock = Field(default_factory=MetricBlock)
    rca: RCAMetricBlock = Field(default_factory=RCAMetricBlock)
    queries: list[QueryEvaluationResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
