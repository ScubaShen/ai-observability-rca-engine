from __future__ import annotations

from rca_engine.models import NormalizedEvent, TimelineEntry
from rca_engine.timeutils import parse_iso


class TimelineBuilder:
    def build(self, events: list[NormalizedEvent]) -> list[TimelineEntry]:
        return [
            TimelineEntry(
                event_id=event.event_id,
                event_time=event.event_time,
                event_type=event.event_type,
                service=event.service,
                severity=event.severity,
                summary=event.summary,
                trace_id=event.trace_id,
                span_id=event.span_id,
                attributes={
                    key: value
                    for key, value in event.attributes.items()
                    if key
                    in {
                        "metric_name",
                        "value",
                        "duration_ms",
                        "span_name",
                        "status_code",
                        "error_pattern",
                        "matched_patterns",
                    }
                },
            )
            for event in sorted(events, key=lambda item: parse_iso(item.event_time))
        ]
