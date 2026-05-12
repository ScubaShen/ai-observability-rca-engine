from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rca_engine.evaluation.metrics import metric_delta
from rca_engine.evaluation.schemas import (
    CaseComparison,
    ComparisonReport,
    EvaluationReport,
    MetricDelta,
    QueryEvaluationResult,
    RCAEvaluationResult,
    SliceMetricBlock,
    Verdict,
)


RAG_PRIMARY_METRICS = ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_5")
RAG_GUARDRAILS = ("citation_coverage",)
RCA_PRIMARY_METRICS = ("root_cause_at_1", "root_cause_at_3", "category_accuracy", "evidence_support")


def compare_reports(
    baseline_path: Path,
    candidate_path: Path,
    output: Path | None = None,
) -> ComparisonReport:
    baseline = EvaluationReport.model_validate(json.loads(baseline_path.read_text(encoding="utf-8")))
    candidate = EvaluationReport.model_validate(json.loads(candidate_path.read_text(encoding="utf-8")))
    report = compare_evaluation_reports(baseline, candidate)
    report.metadata = {
        **report.metadata,
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def compare_evaluation_reports(baseline: EvaluationReport, candidate: EvaluationReport) -> ComparisonReport:
    overall_delta = _overall_delta(baseline, candidate)
    slice_delta = _slice_delta(baseline.slices, candidate.slices)
    regressions: list[CaseComparison] = []
    improvements: list[CaseComparison] = []
    regressions.extend(_rag_regressions(baseline.queries, candidate.queries))
    improvements.extend(_rag_improvements(baseline.queries, candidate.queries))
    regressions.extend(_rca_regressions(baseline.rca_cases, candidate.rca_cases))
    improvements.extend(_rca_improvements(baseline.rca_cases, candidate.rca_cases))

    verdict = _verdict(overall_delta, regressions, improvements)
    return ComparisonReport(
        verdict=verdict,
        overall_delta={
            key: MetricDelta.model_validate(value) for key, value in overall_delta.items()
        },
        slice_delta={
            slice_name: {key: MetricDelta.model_validate(value) for key, value in values.items()}
            for slice_name, values in slice_delta.items()
        },
        regressions=regressions,
        improvements=improvements,
        metadata={
            "baseline_mode": baseline.mode,
            "candidate_mode": candidate.mode,
        },
    )


def _overall_delta(baseline: EvaluationReport, candidate: EvaluationReport) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for metric in RAG_PRIMARY_METRICS + RAG_GUARDRAILS + ("unsupported_answer_rate",):
        result[f"rag.{metric}"] = metric_delta(getattr(baseline.rag, metric), getattr(candidate.rag, metric))
    for metric in RCA_PRIMARY_METRICS + ("unsupported_root_cause_rate",):
        result[f"rca.{metric}"] = metric_delta(getattr(baseline.rca, metric), getattr(candidate.rca, metric))
    return result


def _slice_delta(
    baseline: dict[str, SliceMetricBlock],
    candidate: dict[str, SliceMetricBlock],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for slice_name in sorted(set(baseline).intersection(candidate)):
        values: dict[str, dict[str, Any]] = {}
        for metric in ("recall_at_5", "mrr", "ndcg_at_5", "unsupported_answer_rate"):
            values[f"rag.{metric}"] = metric_delta(
                getattr(baseline[slice_name].rag, metric),
                getattr(candidate[slice_name].rag, metric),
            )
        for metric in ("root_cause_at_1", "root_cause_at_3", "evidence_support"):
            values[f"rca.{metric}"] = metric_delta(
                getattr(baseline[slice_name].rca, metric),
                getattr(candidate[slice_name].rca, metric),
            )
        result[slice_name] = values
    return result


def _rag_regressions(
    baseline: list[QueryEvaluationResult],
    candidate: list[QueryEvaluationResult],
) -> list[CaseComparison]:
    rows: list[CaseComparison] = []
    by_id = {item.query_id: item for item in candidate}
    for old in baseline:
        new = by_id.get(old.query_id)
        if not new:
            rows.append(_case("rag", old.query_id, old.incident_id, "candidate_missing_case", old, None))
            continue
        reasons = []
        for metric in RAG_PRIMARY_METRICS + RAG_GUARDRAILS:
            if getattr(new, metric) < getattr(old, metric):
                reasons.append(f"{metric}_decreased")
        if not old.unsupported and new.unsupported:
            reasons.append("unsupported_became_true")
        if set(old.retrieved_expected_ids) - set(new.retrieved_expected_ids):
            reasons.append("lost_expected_ids")
        if reasons:
            rows.append(_case("rag", old.query_id, old.incident_id, ",".join(reasons), old, new))
    return rows


def _rag_improvements(
    baseline: list[QueryEvaluationResult],
    candidate: list[QueryEvaluationResult],
) -> list[CaseComparison]:
    rows: list[CaseComparison] = []
    by_id = {item.query_id: item for item in candidate}
    for old in baseline:
        new = by_id.get(old.query_id)
        if not new:
            continue
        reasons = []
        for metric in RAG_PRIMARY_METRICS:
            if getattr(new, metric) > getattr(old, metric):
                reasons.append(f"{metric}_increased")
        if old.unsupported and not new.unsupported:
            reasons.append("unsupported_fixed")
        if set(new.retrieved_expected_ids) - set(old.retrieved_expected_ids):
            reasons.append("recovered_expected_ids")
        if reasons:
            rows.append(_case("rag", old.query_id, old.incident_id, ",".join(reasons), old, new))
    return rows


def _rca_regressions(
    baseline: list[RCAEvaluationResult],
    candidate: list[RCAEvaluationResult],
) -> list[CaseComparison]:
    rows: list[CaseComparison] = []
    by_id = {item.query_id: item for item in candidate}
    for old in baseline:
        new = by_id.get(old.query_id)
        if not new:
            rows.append(_case("rca", old.query_id, old.incident_id, "candidate_missing_case", old, None))
            continue
        reasons = []
        for metric in RCA_PRIMARY_METRICS:
            if getattr(new, metric) < getattr(old, metric):
                reasons.append(f"{metric}_decreased")
        if not old.unsupported_root_cause and new.unsupported_root_cause:
            reasons.append("unsupported_root_cause_became_true")
        if reasons:
            rows.append(_case("rca", old.query_id, old.incident_id, ",".join(reasons), old, new))
    return rows


def _rca_improvements(
    baseline: list[RCAEvaluationResult],
    candidate: list[RCAEvaluationResult],
) -> list[CaseComparison]:
    rows: list[CaseComparison] = []
    by_id = {item.query_id: item for item in candidate}
    for old in baseline:
        new = by_id.get(old.query_id)
        if not new:
            continue
        reasons = []
        for metric in RCA_PRIMARY_METRICS:
            if getattr(new, metric) > getattr(old, metric):
                reasons.append(f"{metric}_increased")
        if old.unsupported_root_cause and not new.unsupported_root_cause:
            reasons.append("unsupported_root_cause_fixed")
        if reasons:
            rows.append(_case("rca", old.query_id, old.incident_id, ",".join(reasons), old, new))
    return rows


def _case(
    kind: str,
    case_id: str,
    incident_id: str | None,
    reason: str,
    baseline: QueryEvaluationResult | RCAEvaluationResult,
    candidate: QueryEvaluationResult | RCAEvaluationResult | None,
) -> CaseComparison:
    return CaseComparison(
        kind=kind,  # type: ignore[arg-type]
        case_id=case_id,
        incident_id=incident_id,
        reason=reason,
        baseline=baseline.model_dump(mode="json"),
        candidate=candidate.model_dump(mode="json") if candidate else {},
    )


def _verdict(
    overall_delta: dict[str, dict[str, Any]],
    regressions: list[CaseComparison],
    improvements: list[CaseComparison],
) -> Verdict:
    if _has_hard_regression(overall_delta, regressions):
        if improvements:
            return "needs_review"
        return "regressed"
    if improvements and _has_primary_improvement(overall_delta):
        return "improved"
    if regressions and improvements:
        return "needs_review"
    return "neutral"


def _has_hard_regression(
    overall_delta: dict[str, dict[str, Any]],
    regressions: list[CaseComparison],
) -> bool:
    if regressions:
        return True
    for key, value in overall_delta.items():
        delta = value.get("delta")
        if delta is None:
            continue
        if key.endswith("unsupported_answer_rate") or key.endswith("unsupported_root_cause_rate"):
            if delta > 0:
                return True
        elif delta < 0:
            return True
    return False


def _has_primary_improvement(overall_delta: dict[str, dict[str, Any]]) -> bool:
    for key, value in overall_delta.items():
        if key.endswith("unsupported_answer_rate") or key.endswith("unsupported_root_cause_rate"):
            continue
        delta = value.get("delta")
        if delta is not None and delta > 0:
            return True
    return False
