from __future__ import annotations

from rca_engine.models import NormalizedEvent, ServiceDependencyInsight


class ServiceDependencyAnalyzer:
    def analyze(self, events: list[NormalizedEvent]) -> list[ServiceDependencyInsight]:
        insights: dict[str, ServiceDependencyInsight] = {}
        for event in events:
            if not event.event_type.startswith("trace."):
                continue
            target = _dependency_target(event)
            if target == "unknown":
                continue
            relation = "calls"
            key = f"{event.service}->{target}:{relation}"
            existing = insights.get(key)
            evidence_ids = [event.event_id] if existing is None else [*existing.evidence_event_ids, event.event_id]
            is_suspect = event.event_type in {"trace.slow_span", "trace.error"}
            insights[key] = ServiceDependencyInsight(
                source_service=event.service,
                target=target,
                relation=relation,
                evidence_event_ids=evidence_ids,
                is_suspect=is_suspect or bool(existing and existing.is_suspect),
                summary=f"{event.service} {relation} {target}",
            )
        return list(insights.values())


def _dependency_target(event: NormalizedEvent) -> str:
    attributes = event.attributes
    for key in ("peer.service", "server.address", "net.peer.name", "db.system", "messaging.system"):
        value = attributes.get(key)
        if value:
            return str(value)

    span_name = str(attributes.get("span_name") or "").lower()
    if "redis" in span_name:
        return "redis"
    if "mysql" in span_name or "postgres" in span_name or "jdbc" in span_name or "select " in span_name:
        return "database"
    if "kafka" in span_name:
        return "kafka"
    if "http" in span_name or "get " in span_name or "post " in span_name:
        return "http_dependency"
    return "unknown"
