from __future__ import annotations

from rca_engine.models import AgentFinding, RCAResult


class TraceAgent:
    name = "trace-agent"

    def analyze(self, result: RCAResult) -> list[AgentFinding]:
        findings: list[AgentFinding] = []
        trace_findings = [
            item
            for item in result.evidence
            if item.event_type in {"trace.slow_span", "trace.error"}
        ]
        for item in trace_findings:
            span_name = item.attributes.get("span_name") or "unknown span"
            duration_ms = item.attributes.get("duration_ms")
            findings.append(
                AgentFinding(
                    agent_name=self.name,
                    finding_type=item.event_type,
                    confidence=min(item.confidence + 0.07, 0.94),
                    summary=f"Trace evidence highlights {span_name} with duration={duration_ms}ms.",
                    evidence_event_ids=[item.event_id],
                    recommended_actions=[
                        "Open the related Tempo trace and inspect the critical path.",
                        "Check whether the slow or failing span belongs to this service or a dependency.",
                    ],
                    attributes={"span_name": span_name, "duration_ms": duration_ms},
                )
            )
        return findings
