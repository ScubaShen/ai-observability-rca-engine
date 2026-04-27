from __future__ import annotations

from rca_engine.models import AgentFinding, RCAResult, RunbookRecommendation


class NotificationComposer:
    def compose(
        self,
        result: RCAResult,
        findings: list[AgentFinding],
        runbooks: list[RunbookRecommendation],
    ) -> str:
        top_root = result.root_causes[0].title if result.root_causes else "No confident root cause yet"
        top_runbook = runbooks[0].title if runbooks else "No runbook matched"
        top_actions = "; ".join(result.recommended_actions[:2]) or "Collect more evidence"
        return (
            f"[RCA] {result.severity.upper()} incident on {result.service} ({result.env}). "
            f"Top hypothesis: {top_root}. Confidence: {result.confidence:.2f}. "
            f"Runbook: {top_runbook}. Suggested actions: {top_actions}. "
            f"Evidence findings: {len(findings)}."
        )
