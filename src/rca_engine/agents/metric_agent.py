from __future__ import annotations

from rca_engine.models import AgentFinding, RCAResult


class MetricAgent:
    name = "metric-agent"

    def analyze(self, result: RCAResult) -> list[AgentFinding]:
        findings: list[AgentFinding] = []
        metric_findings = [item for item in result.evidence if item.event_type == "metric.anomaly"]
        for item in metric_findings:
            metric_name = item.attributes.get("metric_name") or item.signal_type
            value = item.attributes.get("value")
            findings.append(
                AgentFinding(
                    agent_name=self.name,
                    finding_type="metric_anomaly",
                    confidence=min(item.confidence + 0.06, 0.92),
                    summary=f"Metric anomaly detected: {metric_name}={value}.",
                    evidence_event_ids=[item.event_id],
                    recommended_actions=[
                        "Compare the anomalous metric with request rate, error rate, and JVM signals.",
                        "Check whether the metric spike starts before log or trace errors.",
                    ],
                    attributes={"metric_name": metric_name, "value": value},
                )
            )
        return findings
