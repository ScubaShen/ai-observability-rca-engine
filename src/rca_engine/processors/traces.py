from __future__ import annotations

from rca_engine.hash_utils import stable_id
from rca_engine.models import NormalizedEvent


def extract_trace_events(event: NormalizedEvent, slow_threshold_ms: float = 1000.0) -> list[NormalizedEvent]:
    outputs: list[NormalizedEvent] = []
    duration_ms = _as_float(event.attributes.get("duration_ms"))
    status_code = str(event.attributes.get("status_code") or "").upper()
    span_name = str(event.attributes.get("span_name") or event.summary or "unknown span")

    if duration_ms is not None and duration_ms >= slow_threshold_ms:
        payload = {
            "source_event_id": event.event_id,
            "span_id": event.span_id,
            "duration_ms": duration_ms,
        }
        outputs.append(
            event.model_copy(
                update={
                    "event_id": stable_id("trace_slow", payload),
                    "event_type": "trace.slow_span",
                    "severity": "warning" if event.severity in {"debug", "info"} else event.severity,
                    "summary": f"Slow span detected in {event.service}: {span_name} took {duration_ms:.2f}ms",
                    "attributes": {
                        **event.attributes,
                        "source_event_id": event.event_id,
                        "duration_ms": duration_ms,
                        "slow_threshold_ms": slow_threshold_ms,
                    },
                }
            )
        )

    if status_code in {"ERROR", "STATUS_CODE_ERROR", "2"} or event.severity in {"error", "critical"}:
        payload = {
            "source_event_id": event.event_id,
            "span_id": event.span_id,
            "status_code": status_code,
        }
        outputs.append(
            event.model_copy(
                update={
                    "event_id": stable_id("trace_error", payload),
                    "event_type": "trace.error",
                    "severity": "error" if event.severity != "critical" else "critical",
                    "summary": f"Trace error detected in {event.service}: {span_name}",
                    "attributes": {
                        **event.attributes,
                        "source_event_id": event.event_id,
                        "status_code": status_code or event.severity,
                    },
                }
            )
        )

    return outputs


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
