from __future__ import annotations

from rca_engine.models import EvidenceFinding, IncidentCandidate, RCAResult, RootCauseHypothesis
from rca_engine.rca.causal_graph import CausalGraphBuilder
from rca_engine.rca.context import IncidentContextLoader
from rca_engine.rca.dependency import ServiceDependencyAnalyzer
from rca_engine.rca.evidence import EvidenceClassifier
from rca_engine.rca.hypotheses import HypothesisGenerator
from rca_engine.rca.ranker import RootCauseRanker
from rca_engine.rca.timeline import TimelineBuilder


class RCAOrchestrator:
    def __init__(self, store) -> None:
        self.context_loader = IncidentContextLoader(store)
        self.timeline_builder = TimelineBuilder()
        self.evidence_classifier = EvidenceClassifier()
        self.dependency_analyzer = ServiceDependencyAnalyzer()
        self.causal_graph_builder = CausalGraphBuilder()
        self.hypothesis_generator = HypothesisGenerator()
        self.ranker = RootCauseRanker()

    def analyze(self, candidate: IncidentCandidate) -> RCAResult:
        # This orchestrator owns pipeline composition only. Each downstream
        # component encapsulates its own RCA heuristic so the flow stays readable
        # and individual reasoning steps can evolve independently.
        context = self.context_loader.load(candidate)
        timeline = self.timeline_builder.build(context.events)
        evidence = self.evidence_classifier.classify(context.events)
        dependency_insights = self.dependency_analyzer.analyze(context.events)
        causal_links = self.causal_graph_builder.build(context.events, dependency_insights)
        hypotheses = self.hypothesis_generator.generate(
            timeline=timeline,
            evidence=evidence,
            dependency_insights=dependency_insights,
            causal_links=causal_links,
        )
        root_causes = self.ranker.rank(hypotheses)
        confidence = root_causes[0].confidence if root_causes else candidate.score
        summary = _summary(candidate, root_causes)

        return RCAResult(
            incident_id=candidate.incident_id,
            service=candidate.service,
            env=candidate.env,
            severity=candidate.severity,
            summary=summary,
            confidence=confidence,
            root_causes=root_causes,
            causal_links=causal_links,
            timeline=timeline,
            evidence=evidence,
            dependency_insights=dependency_insights,
            impacted_services=_impacted_services(candidate.service, evidence),
            recommended_actions=_recommended_actions(root_causes),
            evidence_refs=candidate.evidence_refs,
        )


def _summary(candidate: IncidentCandidate, root_causes: list[RootCauseHypothesis]) -> str:
    if root_causes:
        return f"{candidate.service} incident analyzed: {root_causes[0].title}"
    return f"{candidate.service} incident analyzed with insufficient root-cause evidence."


def _impacted_services(default_service: str, evidence: list[EvidenceFinding]) -> list[str]:
    services = [default_service]
    for item in evidence:
        if item.service not in services:
            services.append(item.service)
    return services


def _recommended_actions(root_causes: list[RootCauseHypothesis]) -> list[str]:
    actions: list[str] = []
    for root_cause in root_causes:
        for action in root_cause.recommended_actions:
            if action not in actions:
                actions.append(action)
    return actions
