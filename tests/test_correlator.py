from rca_engine.correlator import IncidentCandidateCorrelator
from rca_engine.models import NormalizedEvent


def test_correlator_groups_high_value_events_by_service_trace_and_window():
    correlator = IncidentCandidateCorrelator(window_seconds=300)
    first = NormalizedEvent(
        event_id="event_1",
        event_type="log.error_pattern",
        source_topic="observability.logs",
        event_time="2026-04-25T00:01:00+00:00",
        service="checkout",
        env="dev",
        severity="error",
        trace_id="trace-1",
        span_id="span-1",
        correlation_keys=["service:checkout", "trace:trace-1"],
        summary="Log error",
    )
    second = first.model_copy(
        update={
            "event_id": "event_2",
            "event_type": "trace.error",
            "span_id": "span-2",
            "summary": "Trace error",
        }
    )

    candidate = correlator.process(first)
    updated = correlator.process(second)

    assert candidate is not None
    assert updated is not None
    assert updated.incident_id == candidate.incident_id
    assert set(updated.event_types) == {"log.error_pattern", "trace.error"}
    assert updated.severity == "error"
