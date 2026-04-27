from __future__ import annotations

from dataclasses import dataclass

from rca_engine.models import AgentFinding, RCAResult, RunbookRecommendation


@dataclass(frozen=True)
class Runbook:
    runbook_id: str
    title: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...]
    steps: tuple[str, ...]


RUNBOOKS: tuple[Runbook, ...] = (
    Runbook(
        runbook_id="rb-application-exception",
        title="Application exception investigation",
        categories=("application",),
        keywords=("exception", "log_error_pattern", "trace.error"),
        steps=(
            "Open Loki around the incident window and inspect the exception stack.",
            "Open Tempo for the related trace and locate the failing span.",
            "Compare recent code/deploy/config changes for the service.",
            "If the exception is user-input related, capture request attributes and reproduce safely.",
        ),
    ),
    Runbook(
        runbook_id="rb-dependency-latency",
        title="Dependency latency or failure investigation",
        categories=("dependency",),
        keywords=("dependency", "latency", "trace.slow_span"),
        steps=(
            "Identify the dependency target from the slow or failing span.",
            "Check dependency latency, error rate, and saturation dashboards.",
            "Verify network, connection pool, and timeout configuration.",
            "Escalate to the dependency owner if the dependency is external to this service.",
        ),
    ),
    Runbook(
        runbook_id="rb-resource-load",
        title="Resource saturation or load anomaly investigation",
        categories=("resource_or_load",),
        keywords=("metric", "anomaly", "saturation", "load"),
        steps=(
            "Compare anomalous metric with request throughput and error rate.",
            "Inspect JVM memory, thread, GC, CPU, and queue depth metrics.",
            "Check whether horizontal scaling or traffic shaping is needed.",
            "Review recent traffic, batch jobs, and deploy changes.",
        ),
    ),
)


class RunbookRetriever:
    def recommend(
        self,
        result: RCAResult,
        findings: list[AgentFinding],
    ) -> list[RunbookRecommendation]:
        root_categories = {root.category for root in result.root_causes}
        text = " ".join(
            [
                result.summary,
                *[root.title for root in result.root_causes],
                *[finding.finding_type for finding in findings],
                *[finding.summary for finding in findings],
            ]
        ).lower()

        recommendations: list[RunbookRecommendation] = []
        for runbook in RUNBOOKS:
            category_match = bool(root_categories.intersection(runbook.categories))
            keyword_hits = [keyword for keyword in runbook.keywords if keyword.lower() in text]
            if not category_match and not keyword_hits:
                continue
            confidence = 0.78 if category_match else 0.62
            confidence = min(confidence + (len(keyword_hits) * 0.04), 0.94)
            evidence_ids = _evidence_ids_for_runbook(result, runbook)
            recommendations.append(
                RunbookRecommendation(
                    runbook_id=runbook.runbook_id,
                    title=runbook.title,
                    match_reason=_match_reason(category_match, keyword_hits),
                    confidence=confidence,
                    steps=list(runbook.steps),
                    evidence_event_ids=evidence_ids,
                )
            )

        return sorted(recommendations, key=lambda item: item.confidence, reverse=True)[:3]


def _match_reason(category_match: bool, keyword_hits: list[str]) -> str:
    if category_match and keyword_hits:
        return f"Matched root-cause category and keywords: {', '.join(keyword_hits)}"
    if category_match:
        return "Matched root-cause category."
    return f"Matched evidence keywords: {', '.join(keyword_hits)}"


def _evidence_ids_for_runbook(result: RCAResult, runbook: Runbook) -> list[str]:
    ids: list[str] = []
    for root in result.root_causes:
        if root.category in runbook.categories:
            ids.extend(root.supporting_event_ids)
    if ids:
        return list(dict.fromkeys(ids))
    return [item.event_id for item in result.evidence[:5]]
