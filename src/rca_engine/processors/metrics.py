from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean, pstdev

from rca_engine.hash_utils import stable_id
from rca_engine.models import NormalizedEvent


class MetricAnomalyDetector:
    def __init__(self, min_samples: int = 5, stddev_multiplier: float = 3.0) -> None:
        self.min_samples = min_samples
        self.stddev_multiplier = stddev_multiplier
        self.samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))

    def process(self, event: NormalizedEvent) -> list[NormalizedEvent]:
        metric_name = str(event.attributes.get("metric_name") or event.attributes.get("name") or "unknown")
        value = _as_float(event.attributes.get("value"))
        if value is None:
            return []

        key = f"{event.service}:{event.env}:{metric_name}"
        history = self.samples[key]
        is_forced = bool(event.attributes.get("is_anomaly"))
        baseline_mean = mean(history) if history else value
        baseline_stddev = pstdev(history) if len(history) > 1 else 0.0

        threshold = baseline_mean + (baseline_stddev * self.stddev_multiplier)
        enough_history = len(history) >= self.min_samples
        is_anomaly = is_forced or (enough_history and baseline_stddev > 0 and value > threshold)
        history.append(value)

        if not is_anomaly:
            return []

        payload = {
            "source_event_id": event.event_id,
            "metric_name": metric_name,
            "service": event.service,
            "event_time": event.event_time,
            "value": value,
        }
        attributes = {
            **event.attributes,
            "source_event_id": event.event_id,
            "metric_name": metric_name,
            "value": value,
            "baseline_mean": baseline_mean,
            "baseline_stddev": baseline_stddev,
            "threshold": threshold,
        }
        return [
            event.model_copy(
                update={
                    "event_id": stable_id("metric_anomaly", payload),
                    "event_type": "metric.anomaly",
                    "severity": "warning" if event.severity in {"debug", "info"} else event.severity,
                    "summary": f"Metric anomaly detected for {event.service}: {metric_name}={value}",
                    "attributes": attributes,
                }
            )
        ]


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
