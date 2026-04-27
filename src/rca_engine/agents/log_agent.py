from __future__ import annotations

from rca_engine.models import AgentFinding, RCAResult


class LogAgent:
    name = "log-agent"

    def analyze(self, result: RCAResult) -> list[AgentFinding]:
        findings: list[AgentFinding] = []
        log_findings = [item for item in result.evidence if item.event_type == "log.error_pattern"]
        for item in log_findings:
            pattern = item.attributes.get("error_pattern") or item.signal_type
            findings.append(
                AgentFinding(
                    agent_name=self.name,
                    finding_type="log_error_pattern",
                    confidence=min(item.confidence + 0.08, 0.95),
                    summary=f"Log evidence shows pattern `{pattern}` for {item.service}.",
                    evidence_event_ids=[item.event_id],
                    recommended_actions=[
                        "Open the related Loki query and inspect surrounding logs.",
                        "Search for the same exception pattern in the incident window.",
                    ],
                    attributes={"error_pattern": pattern},
                )
            )
        return findings
