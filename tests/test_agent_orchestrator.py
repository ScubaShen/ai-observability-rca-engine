from rca_engine.agents.orchestrator import RCAAgentOrchestrator
from rca_engine.models import EvidenceFinding, RCAResult, RootCauseHypothesis


def test_agent_orchestrator_recommends_runbook_and_notification():
    result = RCAResult(
        incident_id="incident_1",
        service="checkout",
        env="dev",
        severity="error",
        summary="checkout incident analyzed: Application error or exception path",
        confidence=0.82,
        root_causes=[
            RootCauseHypothesis(
                hypothesis_id="hypothesis_1",
                title="Application error or exception path",
                description="Application-level exception path.",
                category="application",
                confidence=0.82,
                supporting_event_ids=["event_log", "event_trace"],
                recommended_actions=["Inspect matching error logs in Loki."],
            )
        ],
        evidence=[
            EvidenceFinding(
                event_id="event_log",
                event_type="log.error_pattern",
                category="symptom",
                signal_type="java_exception",
                service="checkout",
                severity="error",
                summary="Log error pattern detected",
                confidence=0.72,
                attributes={"error_pattern": "java_exception"},
            )
        ],
        recommended_actions=["Inspect matching error logs in Loki."],
    )

    report = RCAAgentOrchestrator().analyze(result)

    assert report.status == "agent_analyzed"
    assert report.runbook_recommendations[0].runbook_id == "rb-application-exception"
    assert "checkout" in report.notification_draft
    assert "Automation" not in report.notification_draft
