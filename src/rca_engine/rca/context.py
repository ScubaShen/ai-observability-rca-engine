from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from rca_engine.models import IncidentCandidate, NormalizedEvent
from rca_engine.timeutils import parse_iso


@dataclass(frozen=True)
class IncidentContext:
    candidate: IncidentCandidate
    events: list[NormalizedEvent]


class IncidentContextLoader:
    def __init__(self, store) -> None:
        self.store = store

    def load(self, candidate: IncidentCandidate, limit: int = 1000) -> IncidentContext:
        if hasattr(self.store, "search_events"):
            rows = self.store.search_events(
                service=candidate.service,
                env=candidate.env,
                cursor=None,
                limit=limit,
            ).get("items", [])
        elif hasattr(self.store, "latest_events"):
            rows = self.store.latest_events(limit=limit)
        else:
            rows = self.store.latest("evidence.jsonl", limit=limit)
        events: list[NormalizedEvent] = []
        candidate_keys = set(candidate.correlation_keys)
        candidate_event_ids = set(candidate.event_ids)
        window_start = parse_iso(candidate.window_start)
        window_end = parse_iso(candidate.window_end)

        for row in rows:
            try:
                event = NormalizedEvent(**row)
            except ValidationError:
                continue
            event_time = parse_iso(event.event_time)
            same_service = event.service == candidate.service and event.env == candidate.env
            same_event = event.event_id in candidate_event_ids
            shared_key = bool(candidate_keys.intersection(event.correlation_keys))
            in_window = window_start <= event_time <= window_end
            if same_event or (same_service and in_window and shared_key):
                events.append(event)

        events.sort(key=lambda item: parse_iso(item.event_time))
        return IncidentContext(candidate=candidate, events=events)
