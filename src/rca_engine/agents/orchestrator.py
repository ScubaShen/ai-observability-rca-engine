from __future__ import annotations

from rca_engine.agents.log_agent import LogAgent
from rca_engine.agents.metric_agent import MetricAgent
from rca_engine.agents.notification import NotificationComposer
from rca_engine.agents.runbook_catalog import RunbookRetriever
from rca_engine.agents.trace_agent import TraceAgent
from rca_engine.models import AgentFinding, RCAAgentReport, RCAResult


class RCAAgentOrchestrator:
    def __init__(self) -> None:
        self.specialist_agents = [LogAgent(), MetricAgent(), TraceAgent()]
        self.runbook_retriever = RunbookRetriever()
        self.notification_composer = NotificationComposer()

    def analyze(self, result: RCAResult) -> RCAAgentReport:
        findings = self._collect_findings(result)
        runbooks = self.runbook_retriever.recommend(result, findings)
        notification = self.notification_composer.compose(
            result,
            findings,
            runbooks,
        )
        return RCAAgentReport(
            incident_id=result.incident_id,
            service=result.service,
            env=result.env,
            severity=result.severity,
            summary=_summary(result, findings, runbooks),
            agent_findings=findings,
            runbook_recommendations=runbooks,
            notification_draft=notification,
            follow_up_questions=_follow_up_questions(result),
            source_rca_confidence=result.confidence,
        )

    def _collect_findings(self, result: RCAResult) -> list[AgentFinding]:
        findings: list[AgentFinding] = []
        for agent in self.specialist_agents:
            findings.extend(agent.analyze(result))
        return sorted(findings, key=lambda item: item.confidence, reverse=True)


def _summary(
    result: RCAResult,
    findings: list[AgentFinding],
    runbooks: list,
) -> str:
    root = result.root_causes[0].title if result.root_causes else "No confident root cause"
    runbook = runbooks[0].title if runbooks else "no matched runbook"
    return (
        f"Agent analysis for {result.service}: {root}; "
        f"{len(findings)} specialist findings; recommended runbook: {runbook}."
    )


def _follow_up_questions(result: RCAResult) -> list[str]:
    questions = [
        "Was there a deploy or config change before the first incident signal?",
        "Does the same error pattern appear in previous incidents?",
    ]
    categories = {root.category for root in result.root_causes}
    if "dependency" in categories:
        questions.append("Is the suspected dependency also showing elevated latency or errors?")
    if "resource_or_load" in categories:
        questions.append("Did traffic, JVM pressure, or queue depth change before the anomaly?")
    return questions
