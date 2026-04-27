from __future__ import annotations

from rca_engine.hash_utils import stable_id
from rca_engine.models import (
    CausalLink,
    EvidenceFinding,
    RootCauseHypothesis,
    ServiceDependencyInsight,
    TimelineEntry,
)


class HypothesisGenerator:
    def generate(
        self,
        timeline: list[TimelineEntry],
        evidence: list[EvidenceFinding],
        dependency_insights: list[ServiceDependencyInsight],
        causal_links: list[CausalLink],
    ) -> list[RootCauseHypothesis]:
        hypotheses: list[RootCauseHypothesis] = []
        hypotheses.extend(_dependency_latency_hypotheses(dependency_insights))
        hypotheses.extend(_application_error_hypotheses(evidence))
        hypotheses.extend(_metric_anomaly_hypotheses(evidence, timeline))

        if not hypotheses and timeline:
            first = timeline[0]
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=stable_id("hypothesis", {"kind": "first_signal", "event_id": first.event_id}),
                    title="First correlated signal in incident window",
                    description=f"The earliest correlated signal is {first.event_type}: {first.summary}",
                    category="correlated_signal",
                    confidence=0.42,
                    supporting_event_ids=[first.event_id],
                    causal_link_ids=_supporting_links(causal_links, [first.event_id]),
                    recommended_actions=[
                        "Inspect the earliest evidence item and compare it with nearby deploy/config changes.",
                    ],
                )
            )

        return hypotheses


def _dependency_latency_hypotheses(
    dependency_insights: list[ServiceDependencyInsight],
) -> list[RootCauseHypothesis]:
    hypotheses: list[RootCauseHypothesis] = []
    for insight in dependency_insights:
        if not insight.is_suspect:
            continue
        hypotheses.append(
            RootCauseHypothesis(
                hypothesis_id=stable_id(
                    "hypothesis",
                    {"kind": "dependency_latency", "target": insight.target, "events": insight.evidence_event_ids},
                ),
                title=f"Suspect dependency issue: {insight.target}",
                description=(
                    f"Trace evidence points to a slow or failing dependency call from "
                    f"{insight.source_service} to {insight.target}."
                ),
                category="dependency",
                confidence=0.74,
                supporting_event_ids=insight.evidence_event_ids,
                recommended_actions=[
                    f"Check dependency health and latency for {insight.target}.",
                    "Inspect Tempo trace details around the suspect span.",
                ],
            )
        )
    return hypotheses


def _application_error_hypotheses(evidence: list[EvidenceFinding]) -> list[RootCauseHypothesis]:
    log_errors = [item for item in evidence if item.event_type == "log.error_pattern"]
    trace_errors = [item for item in evidence if item.event_type == "trace.error"]
    if not log_errors and not trace_errors:
        return []

    supporting_ids = [item.event_id for item in [*log_errors, *trace_errors]]
    confidence = 0.82 if log_errors and trace_errors else 0.66
    return [
        RootCauseHypothesis(
            hypothesis_id=stable_id(
                "hypothesis",
                {"kind": "application_error", "events": supporting_ids},
            ),
            title="Application error or exception path",
            description="Log and trace signals indicate an application-level exception or failed request path.",
            category="application",
            confidence=confidence,
            supporting_event_ids=supporting_ids,
            recommended_actions=[
                "Inspect matching error logs in Loki.",
                "Open the related trace in Tempo and identify the failing span.",
            ],
        )
    ]


def _metric_anomaly_hypotheses(
    evidence: list[EvidenceFinding],
    timeline: list[TimelineEntry],
) -> list[RootCauseHypothesis]:
    metric_events = [item for item in evidence if item.event_type == "metric.anomaly"]
    if not metric_events:
        return []

    first_event_id = timeline[0].event_id if timeline else None
    supporting_ids = [item.event_id for item in metric_events]
    confidence = 0.76 if first_event_id in supporting_ids else 0.62
    return [
        RootCauseHypothesis(
            hypothesis_id=stable_id(
                "hypothesis",
                {"kind": "metric_anomaly", "events": supporting_ids},
            ),
            title="Metric anomaly may be driving the incident",
            description="A metric anomaly is correlated with the incident window and may indicate saturation or load shift.",
            category="resource_or_load",
            confidence=confidence,
            supporting_event_ids=supporting_ids,
            recommended_actions=[
                "Check Prometheus for the anomalous metric and compare with request/error rate.",
                "Inspect JVM, thread, memory, and latency dashboards for the same window.",
            ],
        )
    ]


def _supporting_links(causal_links: list[CausalLink], event_ids: list[str]) -> list[str]:
    event_id_set = set(event_ids)
    return [
        link.link_id
        or stable_id(
            "link",
            {
                "source_id": link.source_id,
                "target_id": link.target_id,
                "relation": link.relation,
            },
        )
        for link in causal_links
        if link.source_id in event_id_set or link.target_id in event_id_set
    ]
