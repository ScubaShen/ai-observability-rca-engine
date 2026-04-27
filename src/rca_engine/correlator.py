from __future__ import annotations

from rca_engine.hash_utils import stable_id
from rca_engine.models import EvidenceRef, IncidentCandidate, NormalizedEvent, Severity
from rca_engine.timeutils import floor_time_window, now_utc_iso

SEVERITY_RANK: dict[Severity, int] = {
    "debug": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}


class IncidentCandidateCorrelator:
    def __init__(self, window_seconds: int = 300) -> None:
        self.window_seconds = window_seconds
        self.candidates: dict[str, IncidentCandidate] = {}

    def process(self, event: NormalizedEvent) -> IncidentCandidate | None:
        if event.event_type not in {
            "metric.anomaly",
            "log.error_pattern",
            "trace.slow_span",
            "trace.error",
        }:
            return None

        window_start, window_end = floor_time_window(event.event_time, self.window_seconds)
        trace_key = event.trace_id or "no-trace"
        incident_id = stable_id(
            "incident",
            {
                "service": event.service,
                "env": event.env,
                "window_start": window_start,
                "trace_id": trace_key,
            },
        )
        existing = self.candidates.get(incident_id)
        if existing is None:
            existing = IncidentCandidate(
                incident_id=incident_id,
                service=event.service,
                env=event.env,
                severity=event.severity,
                window_start=window_start,
                window_end=window_end,
                score=_score([event]),
                summary=f"Potential incident affecting {event.service}: {event.event_type}",
                event_ids=[],
                event_types=[],
                correlation_keys=[],
                evidence_refs=[],
            )
            self.candidates[incident_id] = existing

        event_ids = _append_unique(existing.event_ids, event.event_id)
        event_types = _append_unique(existing.event_types, event.event_type)
        correlation_keys = _merge_unique(existing.correlation_keys, event.correlation_keys)
        evidence_refs = _merge_evidence(existing.evidence_refs, event.evidence_refs)
        severity = _max_severity(existing.severity, event.severity)
        updated = existing.model_copy(
            update={
                "severity": severity,
                "score": _score_for_values(event_types, severity),
                "summary": f"Potential incident affecting {event.service}: {', '.join(event_types)}",
                "event_ids": event_ids,
                "event_types": event_types,
                "correlation_keys": correlation_keys,
                "evidence_refs": evidence_refs,
                "updated_at": now_utc_iso(),
            }
        )
        self.candidates[incident_id] = updated
        return updated


def _append_unique(values: list[str], value: str) -> list[str]:
    return values if value in values else [*values, value]


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for value in right:
        if value not in merged:
            merged.append(value)
    return merged


def _merge_evidence(left: list[EvidenceRef], right: list[EvidenceRef]) -> list[EvidenceRef]:
    merged = list(left)
    seen = {(item.source, item.ref_type, item.ref_id, item.query) for item in merged}
    for item in right:
        key = (item.source, item.ref_type, item.ref_id, item.query)
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _max_severity(left: Severity, right: Severity) -> Severity:
    return left if SEVERITY_RANK[left] >= SEVERITY_RANK[right] else right


def _score(events: list[NormalizedEvent]) -> float:
    types = [event.event_type for event in events]
    severity = max((event.severity for event in events), key=lambda item: SEVERITY_RANK[item])
    return _score_for_values(types, severity)


def _score_for_values(event_types: list[str], severity: Severity) -> float:
    diversity_bonus = min(len(set(event_types)) * 0.15, 0.45)
    severity_bonus = SEVERITY_RANK[severity] * 0.12
    return min(0.1 + diversity_bonus + severity_bonus, 0.99)
