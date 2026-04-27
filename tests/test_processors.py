from rca_engine.models import NormalizedEvent
from rca_engine.processors.logs import extract_log_error_patterns
from rca_engine.processors.metrics import MetricAnomalyDetector
from rca_engine.processors.traces import extract_trace_events


def event(**overrides):
    data = {
        "event_id": "event_1",
        "event_type": "log.raw",
        "source_topic": "observability.logs",
        "event_time": "2026-04-25T00:00:00+00:00",
        "service": "checkout",
        "env": "dev",
        "severity": "info",
        "summary": "ok",
        "attributes": {},
    }
    data.update(overrides)
    return NormalizedEvent(**data)


def test_extract_log_error_pattern_from_exception_message():
    source = event(
        severity="error",
        summary="java.lang.IllegalStateException: payment failed",
        attributes={"message": "java.lang.IllegalStateException: payment failed"},
    )

    extracted = extract_log_error_patterns(source)

    assert len(extracted) == 1
    assert extracted[0].event_type == "log.error_pattern"
    assert extracted[0].attributes["error_pattern"] == "java_exception"


def test_metric_anomaly_detector_uses_baseline():
    detector = MetricAnomalyDetector(min_samples=3, stddev_multiplier=2)
    for index, value in enumerate([10, 11, 9]):
        detector.process(
            event(
                event_id=f"metric_{index}",
                event_type="metric.raw",
                source_topic="observability.metrics",
                attributes={"metric_name": "http_errors_total", "value": value},
            )
        )

    extracted = detector.process(
        event(
            event_id="metric_spike",
            event_type="metric.raw",
            source_topic="observability.metrics",
            attributes={"metric_name": "http_errors_total", "value": 50},
        )
    )

    assert len(extracted) == 1
    assert extracted[0].event_type == "metric.anomaly"


def test_extract_trace_slow_and_error_span():
    source = event(
        event_type="trace.raw",
        source_topic="observability.traces",
        severity="error",
        trace_id="abc",
        span_id="def",
        attributes={"span_name": "GET /api/demo/error", "duration_ms": 1200, "status_code": "ERROR"},
    )

    extracted = extract_trace_events(source, slow_threshold_ms=1000)
    event_types = {item.event_type for item in extracted}

    assert event_types == {"trace.slow_span", "trace.error"}
