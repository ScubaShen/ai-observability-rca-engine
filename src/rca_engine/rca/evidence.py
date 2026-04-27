from __future__ import annotations

from rca_engine.models import EvidenceFinding, NormalizedEvent


class EvidenceClassifier:
    def classify(self, events: list[NormalizedEvent]) -> list[EvidenceFinding]:
        return [self._classify_event(event) for event in events]

    def _classify_event(self, event: NormalizedEvent) -> EvidenceFinding:
        category = "signal"
        signal_type = event.event_type
        confidence = 0.55

        if event.event_type == "log.error_pattern":
            category = "symptom"
            signal_type = str(event.attributes.get("error_pattern") or "log_error")
            confidence = 0.72
        elif event.event_type == "metric.anomaly":
            category = "possible_cause"
            metric_name = str(event.attributes.get("metric_name") or "metric")
            signal_type = f"metric:{metric_name}"
            confidence = 0.68
        elif event.event_type == "trace.slow_span":
            category = "possible_cause"
            signal_type = "latency"
            confidence = 0.75
        elif event.event_type == "trace.error":
            category = "symptom"
            signal_type = "trace_error"
            confidence = 0.78

        return EvidenceFinding(
            event_id=event.event_id,
            event_type=event.event_type,
            category=category,
            signal_type=signal_type,
            service=event.service,
            severity=event.severity,
            summary=event.summary,
            confidence=confidence,
            attributes=event.attributes,
        )
