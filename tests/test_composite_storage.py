from rca_engine.models import NormalizedEvent, RAGDocument
from rca_engine.storage.composite import CompositeStorage
from rca_engine.storage.jsonl import JsonlStore


class FakePostgresStore:
    def __init__(self, fail=False):
        self.fail = fail
        self.events = []
        self.errors = []

    def available(self):
        return True

    def health(self):
        return {"status": "ok"}

    def save_event(self, event):
        if self.fail:
            raise RuntimeError("db down")
        self.events.append(event)

    def latest_events(self, limit=50):
        if self.fail:
            raise RuntimeError("db down")
        return [event.model_dump(mode="json") for event in self.events[-limit:]]

    def record_storage_error(self, component, operation, error):
        self.errors.append({"component": component, "operation": operation, "error": error})

    def save_rag_documents(self, documents):
        if self.fail:
            raise RuntimeError("db down")


def event():
    return NormalizedEvent(
        event_id="event_1",
        event_type="log.error_pattern",
        source_topic="observability.logs",
        event_time="2026-04-25T00:00:00+00:00",
        service="checkout",
        env="dev",
        severity="error",
        summary="Log error",
    )


def test_composite_storage_writes_postgres_and_jsonl(tmp_path):
    postgres = FakePostgresStore()
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path), postgres=postgres)

    storage.save_event(event())

    assert len(postgres.events) == 1
    assert storage.latest_events()[0]["event_id"] == "event_1"
    assert JsonlStore(tmp_path).latest("evidence.jsonl")[0]["event_id"] == "event_1"


def test_composite_storage_falls_back_to_jsonl_when_postgres_fails(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path), postgres=FakePostgresStore(fail=True))

    storage.save_event(event())

    assert storage.latest_events()[0]["event_id"] == "event_1"
    assert JsonlStore(tmp_path).latest("storage-errors.jsonl")[0]["component"] == "postgres"


def test_composite_storage_searches_rag_documents_from_jsonl_when_postgres_fails(tmp_path):
    storage = CompositeStorage(jsonl=JsonlStore(tmp_path), postgres=FakePostgresStore(fail=True))
    document = RAGDocument(
        document_id="doc_1",
        source_type="runbook",
        ref_id="rb-1",
        title="Application exception investigation",
        content="Inspect application exception logs and traces.",
        embedding=[1.0, 0.0],
    )

    storage.save_rag_documents([document])
    matches = storage.search_rag_documents("application exception", [1.0, 0.0], limit=5)

    assert matches[0]["document_id"] == "doc_1"
