from __future__ import annotations

from collections import Counter

from rca_engine.models import EvidenceFinding, IncidentCandidate, NormalizedEvent
from rca_engine.timeutils import parse_iso

SEVERITY_WEIGHT = {"debug": 0.0, "info": 0.02, "warn": 0.08, "error": 0.16, "critical": 0.22}
TYPE_WEIGHT = {
    "log.error_pattern": 0.2,
    "metric.anomaly": 0.16,
    "trace.slow_span": 0.18,
    "trace.error": 0.22,
    "deploy.change": 0.2,
    "config.change": 0.18,
}


class EvidenceClassifier:
    def classify(
        self,
        events: list[NormalizedEvent],
        candidate: IncidentCandidate | None = None,
    ) -> list[EvidenceFinding]:
        context = _EvidenceContext(events=events, candidate=candidate)
        return [self._classify_event(event, context) for event in events]

    def _classify_event(self, event: NormalizedEvent, context: "_EvidenceContext") -> EvidenceFinding:
        category = "signal"
        signal_type = event.event_type
        base_confidence = 0.45

        if event.event_type == "log.error_pattern":
            category = "symptom"
            signal_type = str(event.attributes.get("error_pattern") or "log_error")
            base_confidence = 0.58
        elif event.event_type == "metric.anomaly":
            category = "possible_cause"
            metric_name = str(event.attributes.get("metric_name") or "metric")
            signal_type = f"metric:{metric_name}"
            base_confidence = 0.54
        elif event.event_type == "trace.slow_span":
            category = "possible_cause"
            signal_type = "latency"
            base_confidence = 0.6
        elif event.event_type == "trace.error":
            category = "symptom"
            signal_type = "trace_error"
            base_confidence = 0.62
        elif event.event_type == "deploy.change":
            category = "possible_cause"
            signal_type = "deploy_change"
            base_confidence = 0.56
        elif event.event_type == "config.change":
            category = "possible_cause"
            signal_type = "config_change"
            base_confidence = 0.54

        scoring_factors = context.scoring_factors(event, base_confidence)
        confidence = round(min(sum(scoring_factors.values()), 0.98), 4)

        return EvidenceFinding(
            event_id=event.event_id,
            event_type=event.event_type,
            category=category,
            signal_type=signal_type,
            service=event.service,
            severity=event.severity,
            summary=event.summary,
            confidence=confidence,
            scoring_factors=scoring_factors,
            strength=_strength(confidence),
            attributes=event.attributes,
        )


class _EvidenceContext:
    def __init__(self, events: list[NormalizedEvent], candidate: IncidentCandidate | None) -> None:
        self.events = events
        self.event_ids = set(candidate.event_ids if candidate else [])
        self.correlation_keys = set(candidate.correlation_keys if candidate else [])
        self.type_counts = Counter(event.event_type for event in events)
        self.trace_counts = Counter(event.trace_id for event in events if event.trace_id)
        self.first_event_id = _first_event_id(events)

    def scoring_factors(self, event: NormalizedEvent, base_confidence: float) -> dict[str, float]:
        factors = {
            "base": base_confidence,
            "severity": SEVERITY_WEIGHT.get(event.severity, 0.04),
            "event_type": TYPE_WEIGHT.get(event.event_type, 0.06),
        }
        if event.event_id in self.event_ids:
            factors["candidate_event"] = 0.1
        if self.correlation_keys.intersection(event.correlation_keys):
            factors["correlation_key"] = 0.08
        if event.trace_id and self.trace_counts[event.trace_id] > 1:
            factors["trace_coherence"] = 0.08
        if event.event_id == self.first_event_id:
            factors["first_signal"] = 0.06
        if self.type_counts["log.error_pattern"] and self.type_counts["trace.error"]:
            factors["log_trace_agreement"] = 0.1
        if self.type_counts["metric.anomaly"] and self.type_counts["trace.slow_span"]:
            factors["metric_trace_agreement"] = 0.08
        if event.event_type in {"deploy.change", "config.change"}:
            factors["change_proximity"] = 0.1
        return {key: round(value, 4) for key, value in factors.items() if value > 0}


def _first_event_id(events: list[NormalizedEvent]) -> str | None:
    if not events:
        return None
    return min(events, key=lambda event: parse_iso(event.event_time)).event_id


def _strength(confidence: float) -> str:
    if confidence >= 0.82:
        return "strong"
    if confidence >= 0.68:
        return "medium"
    return "weak"
