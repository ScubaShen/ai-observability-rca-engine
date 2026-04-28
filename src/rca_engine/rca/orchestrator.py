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
        evidence = self.evidence_classifier.classify(context.events, candidate)
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
        evidence_score = _evidence_score(evidence)
        summary = _summary(candidate, root_causes)

        return RCAResult(
            incident_id=candidate.incident_id,
            service=candidate.service,
            env=candidate.env,
            severity=candidate.severity,
            summary=summary,
            confidence=confidence,
            evidence_score=evidence_score,
            evidence_strength=_evidence_strength(evidence_score),
            missing_evidence=_missing_evidence(candidate, evidence),
            reasoning_steps=_reasoning_steps(candidate, evidence, root_causes),
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


def _evidence_score(evidence: list[EvidenceFinding]) -> float:
    if not evidence:
        return 0.0
    top = max(item.confidence for item in evidence)
    avg_top = sum(sorted((item.confidence for item in evidence), reverse=True)[:5]) / min(len(evidence), 5)
    type_coverage = min(len({item.event_type for item in evidence}) * 0.04, 0.16)
    strong_bonus = min(len([item for item in evidence if item.strength == "strong"]) * 0.03, 0.12)
    return round(min((top * 0.55) + (avg_top * 0.35) + type_coverage + strong_bonus, 0.98), 4)


def _evidence_strength(score: float) -> str:
    if score >= 0.82:
        return "strong"
    if score >= 0.65:
        return "medium"
    return "weak"


def _missing_evidence(candidate: IncidentCandidate, evidence: list[EvidenceFinding]) -> list[str]:
    event_types = {item.event_type for item in evidence}
    missing: list[str] = []
    if "trace.error" not in event_types and "trace.slow_span" not in event_types:
        missing.append("Trace evidence for the affected request path is missing.")
    if "log.error_pattern" not in event_types:
        missing.append("Correlated application error logs are missing.")
    if "metric.anomaly" not in event_types and candidate.severity in {"error", "critical"}:
        missing.append("Metric baseline or saturation evidence is missing.")
    if not any(item.event_type in {"deploy.change", "config.change"} for item in evidence):
        missing.append("Deploy/config change proximity has not been confirmed.")
    return missing[:4]


def _reasoning_steps(
    candidate: IncidentCandidate,
    evidence: list[EvidenceFinding],
    root_causes: list[RootCauseHypothesis],
) -> list[str]:
    steps = [
        f"Loaded incident-scoped evidence for service={candidate.service}, env={candidate.env}.",
        f"Scored {len(evidence)} evidence items using severity, event type, trace coherence, correlation keys, and first-signal position.",
    ]
    if root_causes:
        top = root_causes[0]
        steps.append(
            f"Ranked top hypothesis '{top.title}' with confidence={top.confidence:.2f} "
            f"and evidence_score={top.evidence_score:.2f}."
        )
    else:
        steps.append("No root-cause hypothesis met the minimum evidence threshold.")
    return steps
