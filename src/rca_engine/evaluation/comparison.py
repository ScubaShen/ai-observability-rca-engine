from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rca_engine.evaluation.metrics import metric_delta
from rca_engine.evaluation.schemas import (
    AcceptanceReport,
    AcceptanceVerdict,
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
DEFAULT_FOCUS_SLICES = (
    "semantic_gap",
    "noisy_query",
    "runbook_discrimination",
    "cross_incident",
    "evidence_support",
)
SLICE_GATE_RAG_METRICS = ("recall_at_5", "mrr", "ndcg_at_5")


def compare_reports(
    baseline_path: Path,
    candidate_path: Path,
    output: Path | None = None,
    *,
    focus_slices: Sequence[str] | None = None,
) -> ComparisonReport:
    baseline = EvaluationReport.model_validate(json.loads(baseline_path.read_text(encoding="utf-8")))
    candidate = EvaluationReport.model_validate(json.loads(candidate_path.read_text(encoding="utf-8")))
    report = compare_evaluation_reports(
        baseline,
        candidate,
        focus_slices=focus_slices,
    )
    report.metadata = {
        **report.metadata,
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        output.with_suffix(".md").write_text(render_comparison_markdown(report), encoding="utf-8")
    return report


def compare_evaluation_reports(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    *,
    focus_slices: Sequence[str] | None = None,
) -> ComparisonReport:
    overall_delta = _overall_delta(baseline, candidate)
    slice_delta = _slice_delta(baseline.slices, candidate.slices)
    regressions: list[CaseComparison] = []
    improvements: list[CaseComparison] = []
    regressions.extend(_rag_regressions(baseline.queries, candidate.queries))
    improvements.extend(_rag_improvements(baseline.queries, candidate.queries))
    regressions.extend(_rca_regressions(baseline.rca_cases, candidate.rca_cases))
    improvements.extend(_rca_improvements(baseline.rca_cases, candidate.rca_cases))

    acceptance = _advanced_rag_acceptance(overall_delta, slice_delta, focus_slices)
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
        acceptance=acceptance,
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


def _advanced_rag_acceptance(
    overall_delta: dict[str, dict[str, Any]],
    slice_delta: dict[str, dict[str, dict[str, Any]]],
    focus_slices: Sequence[str] | None,
) -> AcceptanceReport:
    slices = tuple(focus_slices or DEFAULT_FOCUS_SLICES)
    regressions: list[str] = []
    improvements: list[str] = []
    guardrails: list[str] = []
    missing = [name for name in slices if name not in slice_delta]

    for name in slices:
        metrics = slice_delta.get(name)
        if not metrics:
            continue
        for metric in SLICE_GATE_RAG_METRICS:
            key = f"rag.{metric}"
            delta = metrics.get(key)
            if not delta:
                continue
            formatted = _format_delta(name, key, delta)
            value = delta.get("delta")
            if value is not None and value < 0:
                regressions.append(formatted)
            elif value is not None and value > 0:
                improvements.append(formatted)

        unsupported = metrics.get("rag.unsupported_answer_rate")
        if unsupported and unsupported.get("delta") is not None and unsupported["delta"] > 0:
            guardrails.append(_format_delta(name, "rag.unsupported_answer_rate", unsupported))

        evidence = metrics.get("rca.evidence_support")
        if evidence and evidence.get("delta") is not None and evidence["delta"] < 0:
            guardrails.append(_format_delta(name, "rca.evidence_support", evidence))

    for key in ("rag.citation_coverage", "rag.unsupported_answer_rate", "rca.evidence_support"):
        delta = overall_delta.get(key)
        if not delta or delta.get("delta") is None:
            continue
        value = delta["delta"]
        if key == "rag.unsupported_answer_rate" and value > 0:
            guardrails.append(_format_delta("overall", key, delta))
        elif key != "rag.unsupported_answer_rate" and value < 0:
            guardrails.append(_format_delta("overall", key, delta))

    verdict = _acceptance_verdict(
        regressions,
        improvements,
        guardrails,
        missing,
    )
    return AcceptanceReport(
        verdict=verdict,
        focus_slices=list(slices),
        improvements=improvements,
        regressions=regressions,
        guardrails=guardrails,
        missing_slices=missing,
    )


def _acceptance_verdict(
    regressions: list[str],
    improvements: list[str],
    guardrails: list[str],
    missing_slices: list[str],
) -> AcceptanceVerdict:
    if regressions or any("unsupported_answer_rate" in item for item in guardrails):
        return "failed"
    if guardrails or missing_slices or not improvements:
        return "needs_review"
    return "passed"


def _format_delta(scope: str, metric: str, delta: dict[str, Any]) -> str:
    baseline = delta.get("baseline")
    candidate = delta.get("candidate")
    value = delta.get("delta")
    return f"{scope}.{metric}: {baseline} -> {candidate} ({value:+.4f})"


def render_comparison_markdown(report: ComparisonReport) -> str:
    lines = [
        "# Evaluation Compare Report",
        "",
        f"- Verdict: `{report.verdict}`",
        f"- Advanced RAG acceptance: `{report.acceptance.verdict}`",
        f"- Acceptance profile: `{report.acceptance.profile}`",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in (
        "rag.recall_at_5",
        "rag.recall_at_10",
        "rag.mrr",
        "rag.ndcg_at_5",
        "rag.citation_coverage",
        "rag.unsupported_answer_rate",
        "rca.root_cause_at_1",
        "rca.root_cause_at_3",
        "rca.evidence_support",
        "rca.unsupported_root_cause_rate",
    ):
        delta = report.overall_delta.get(key)
        if not delta:
            continue
        lines.append(
            f"| `{key}` | {_display(delta.baseline)} | {_display(delta.candidate)} | {_display_delta(delta.delta)} |"
        )

    lines.extend(
        [
            "",
            "## Advanced RAG Acceptance",
            "",
            f"Focus slices: {', '.join(f'`{item}`' for item in report.acceptance.focus_slices)}",
            "",
        ]
    )
    _append_items(lines, "Improvements", report.acceptance.improvements)
    _append_items(lines, "Regressions", report.acceptance.regressions)
    _append_items(lines, "Guardrails", report.acceptance.guardrails)
    _append_items(lines, "Missing Slices", report.acceptance.missing_slices)

    lines.extend(["", "## Case-Level Changes", ""])
    _append_case_summary(lines, "Regressions", report.regressions)
    _append_case_summary(lines, "Improvements", report.improvements)

    lines.extend(["", "## Metadata", ""])
    for key, value in sorted(report.metadata.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def _append_items(lines: list[str], title: str, values: list[str]) -> None:
    lines.extend([f"### {title}", ""])
    if not values:
        lines.append("- None")
    else:
        lines.extend(f"- {item}" for item in values)
    lines.append("")


def _append_case_summary(lines: list[str], title: str, values: list[CaseComparison]) -> None:
    lines.extend([f"### {title}", ""])
    if not values:
        lines.append("- None")
    else:
        for item in values[:10]:
            incident = f", incident `{item.incident_id}`" if item.incident_id else ""
            lines.append(f"- `{item.kind}` `{item.case_id}`{incident}: {item.reason}")
        if len(values) > 10:
            lines.append(f"- ... {len(values) - 10} more")
    lines.append("")


def _display(value: float | int | bool | None) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None:
        return "-"
    return str(value)


def _display_delta(value: float | int | None) -> str:
    if isinstance(value, float):
        return f"{value:+.4f}"
    if isinstance(value, int):
        return f"{value:+d}"
    return "-"


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
