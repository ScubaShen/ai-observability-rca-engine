from rca_engine.models import NormalizedEvent
from rca_engine.storage.jsonl import JsonlStore


def test_jsonl_store_appends_and_reads_latest(tmp_path):
    store = JsonlStore(tmp_path)
    store.append(
        "evidence.jsonl",
        NormalizedEvent(
            event_id="event_1",
            event_type="log.error_pattern",
            source_topic="observability.logs",
            event_time="2026-04-25T00:00:00+00:00",
            service="checkout",
            env="dev",
            severity="error",
            summary="Log error",
        ),
    )

    rows = store.latest("evidence.jsonl")

    assert rows[0]["event_id"] == "event_1"
