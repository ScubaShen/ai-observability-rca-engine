from rca_engine.models import IncidentCandidate, NormalizedEvent
from rca_engine.storage.composite import CompositeStorage
from rca_engine.storage.jsonl import JsonlStore


def test_composite_search_events_filters_and_cursor_paginates(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path))
    for index in range(3):
        storage.save_event(
            NormalizedEvent(
                event_id=f"event_{index}",
                event_type="log.error_pattern",
                source_topic="observability.logs",
                event_time=f"2026-04-25T00:0{index}:00+00:00",
                service="checkout",
                env="prod",
                severity="error",
                summary=f"Checkout exception {index}",
            )
        )

    first_page = storage.search_events(q="exception", service="checkout", limit=2)
    second_page = storage.search_events(q="exception", service="checkout", limit=2, cursor=first_page["next_cursor"])

    assert [item["event_id"] for item in first_page["items"]] == ["event_2", "event_1"]
    assert [item["event_id"] for item in second_page["items"]] == ["event_0"]


def test_composite_search_events_filters_by_time_range_and_page(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path))
    for index in range(5):
        storage.save_event(
            NormalizedEvent(
                event_id=f"event_{index}",
                event_type="log.error_pattern",
                source_topic="observability.logs",
                event_time=f"2026-04-25T00:0{index}:00+00:00",
                service="checkout",
                env="prod",
                severity="error",
                summary=f"Checkout exception {index}",
            )
        )

    first_page = storage.search_events(
        service="checkout",
        event_time_from="2026-04-25T00:01:00Z",
        event_time_to="2026-04-25T00:04:00Z",
        page=1,
        page_size=2,
    )
    second_page = storage.search_events(
        service="checkout",
        event_time_from="2026-04-25T00:01:00Z",
        event_time_to="2026-04-25T00:04:00Z",
        page=2,
        page_size=2,
    )

    assert [item["event_id"] for item in first_page["items"]] == ["event_4", "event_3"]
    assert [item["event_id"] for item in second_page["items"]] == ["event_2", "event_1"]
    assert first_page["total"] == 4
    assert first_page["total_pages"] == 2
    assert first_page["has_next"] is True
    assert first_page["has_prev"] is False
    assert second_page["has_next"] is False
    assert second_page["has_prev"] is True


def test_composite_search_incidents_filters_and_cursor_paginates(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path))
    for index in range(3):
        storage.save_candidate(
            IncidentCandidate(
                incident_id=f"incident_{index}",
                service="checkout",
                env="prod",
                severity="error",
                window_start=f"2026-04-25T00:0{index}:00+00:00",
                window_end=f"2026-04-25T00:0{index}:30+00:00",
                score=0.7,
                summary=f"Checkout error {index}",
                updated_at=f"2026-04-25T00:0{index}:30+00:00",
            )
        )

    first_page = storage.search_incidents(q="checkout", service="checkout", limit=2)
    second_page = storage.search_incidents(q="checkout", service="checkout", limit=2, cursor=first_page["next_cursor"])

    assert [item["incident_id"] for item in first_page["items"]] == ["incident_2", "incident_1"]
    assert [item["incident_id"] for item in second_page["items"]] == ["incident_0"]


def test_composite_search_incidents_filters_by_updated_range_and_page(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path))
    for index in range(5):
        storage.save_candidate(
            IncidentCandidate(
                incident_id=f"incident_{index}",
                service="checkout",
                env="prod",
                severity="error",
                window_start=f"2026-04-25T00:0{index}:00+00:00",
                window_end=f"2026-04-25T00:0{index}:30+00:00",
                score=0.7,
                summary=f"Checkout error {index}",
                updated_at=f"2026-04-25T00:0{index}:30+00:00",
            )
        )

    first_page = storage.search_incidents(
        service="checkout",
        updated_from="2026-04-25T00:01:30Z",
        updated_to="2026-04-25T00:04:30Z",
        page=1,
        page_size=2,
    )
    second_page = storage.search_incidents(
        service="checkout",
        updated_from="2026-04-25T00:01:30Z",
        updated_to="2026-04-25T00:04:30Z",
        page=2,
        page_size=2,
    )

    assert [item["incident_id"] for item in first_page["items"]] == ["incident_4", "incident_3"]
    assert [item["incident_id"] for item in second_page["items"]] == ["incident_2", "incident_1"]
    assert first_page["total"] == 4
    assert first_page["total_pages"] == 2
    assert first_page["has_next"] is True
    assert first_page["has_prev"] is False
    assert second_page["has_next"] is False
    assert second_page["has_prev"] is True


def test_composite_search_incidents_q_does_not_match_service_only(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path))
    storage.save_candidate(
        IncidentCandidate(
            incident_id="incident_1",
            service="checkout",
            env="prod",
            severity="error",
            window_start="2026-04-25T00:00:00+00:00",
            window_end="2026-04-25T00:00:30+00:00",
            score=0.7,
            summary="Payment failure",
            updated_at="2026-04-25T00:00:30+00:00",
        )
    )

    result = storage.search_incidents(q="checkout", limit=10)

    assert result["items"] == []
