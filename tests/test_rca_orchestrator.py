from rca_engine.models import IncidentCandidate, NormalizedEvent
from rca_engine.rca.orchestrator import RCAOrchestrator
from rca_engine.storage.jsonl import JsonlStore


def test_rca_orchestrator_produces_ranked_result(tmp_path):
    store = JsonlStore(tmp_path)
    error_event = NormalizedEvent(
        event_id="event_log",
        event_type="log.error_pattern",
        source_topic="observability.logs",
        event_time="2026-04-25T00:01:00+00:00",
        service="checkout",
        env="dev",
        severity="error",
        trace_id="trace-1",
        span_id="span-1",
        correlation_keys=["service:checkout", "trace:trace-1"],
        summary="Log error pattern detected",
        attributes={"error_pattern": "java_exception"},
    )
    trace_event = NormalizedEvent(
        event_id="event_trace",
        event_type="trace.error",
        source_topic="observability.traces",
        event_time="2026-04-25T00:01:05+00:00",
        service="checkout",
        env="dev",
        severity="error",
        trace_id="trace-1",
        span_id="span-2",
        correlation_keys=["service:checkout", "trace:trace-1"],
        summary="Trace error detected",
        attributes={"span_name": "GET /api/demo/error", "status_code": "ERROR"},
    )
    store.append("evidence.jsonl", error_event)
    store.append("evidence.jsonl", trace_event)
    candidate = IncidentCandidate(
        incident_id="incident_1",
        service="checkout",
        env="dev",
        severity="error",
        window_start="2026-04-25T00:00:00+00:00",
        window_end="2026-04-25T00:05:00+00:00",
        score=0.7,
        summary="Potential incident",
        event_ids=["event_log", "event_trace"],
        event_types=["log.error_pattern", "trace.error"],
        correlation_keys=["service:checkout", "trace:trace-1"],
    )

    result = RCAOrchestrator(store).analyze(candidate)

    assert result.status == "analyzed"
    assert result.root_causes[0].category == "application"
    assert result.evidence_score > 0.8
    assert result.evidence_strength == "strong"
    assert result.reasoning_steps
    assert result.evidence[0].scoring_factors
    assert result.evidence[0].strength in {"medium", "strong"}
    assert len(result.timeline) == 2
