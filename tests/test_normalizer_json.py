import json

from rca_engine.normalizer import normalize_kafka_payload


def test_normalizer_accepts_json_payload_for_fixture_and_replay():
    payload = json.dumps(
        {
            "event_type": "log.raw",
            "event_time": "2026-04-25T00:00:00+00:00",
            "service": "checkout",
            "env": "dev",
            "severity": "error",
            "summary": "RuntimeException",
            "attributes": {"message": "RuntimeException"},
        }
    ).encode("utf-8")

    events = normalize_kafka_payload("observability.logs", payload)

    assert len(events) == 1
    assert events[0].event_type == "log.raw"
    assert events[0].service == "checkout"
