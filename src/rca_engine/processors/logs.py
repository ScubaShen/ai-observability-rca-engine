from __future__ import annotations

import re

from rca_engine.hash_utils import stable_id
from rca_engine.models import NormalizedEvent

ERROR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("java_exception", re.compile(r"\b[A-Za-z0-9_.]+Exception\b")),
    ("stack_trace", re.compile(r"\bat\s+[\w.$]+\(.*:\d+\)")),
    ("timeout", re.compile(r"\b(timeout|timed out|deadline exceeded)\b", re.IGNORECASE)),
    ("connection_error", re.compile(r"\b(connection refused|connection reset|broken pipe)\b", re.IGNORECASE)),
    ("http_5xx", re.compile(r"\b5\d{2}\b")),
    ("error_keyword", re.compile(r"\b(error|failed|failure|fatal)\b", re.IGNORECASE)),
)


def extract_log_error_patterns(event: NormalizedEvent) -> list[NormalizedEvent]:
    message = str(event.attributes.get("message") or event.summary or "")
    matches = [name for name, pattern in ERROR_PATTERNS if pattern.search(message)]
    if event.severity not in {"error", "critical"} and not matches:
        return []

    pattern_name = matches[0] if matches else "error_severity"
    payload = {
        "source_event_id": event.event_id,
        "pattern": pattern_name,
        "service": event.service,
        "event_time": event.event_time,
    }
    attributes = {
        **event.attributes,
        "source_event_id": event.event_id,
        "error_pattern": pattern_name,
        "matched_patterns": matches,
    }
    return [
        event.model_copy(
            update={
                "event_id": stable_id("log_error", payload),
                "event_type": "log.error_pattern",
                "severity": "error" if event.severity != "critical" else "critical",
                "summary": f"Log error pattern detected in {event.service}: {pattern_name}",
                "attributes": attributes,
            }
        )
    ]
