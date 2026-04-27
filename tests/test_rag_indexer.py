from rca_engine.models import RCAResult, RootCauseHypothesis
from rca_engine.rag.indexer import RAGIndexer


class FakeStore:
    def __init__(self):
        self.documents = []
        self.historical_incidents = []
        self.rca_result = None

    def list_runbooks(self):
        return [
            {
                "runbook_id": "rb-1",
                "title": "Application exception investigation",
                "categories": ["application"],
                "keywords": ["exception"],
                "steps": ["Inspect logs."],
            }
        ]

    def latest_rca_results(self, limit=200):
        return []

    def latest_agent_reports(self, limit=200):
        return []

    def save_rag_documents(self, documents):
        self.documents.extend(documents)

    def get_rca_result(self, incident_id):
        return self.rca_result

    def save_historical_incident(self, incident):
        self.historical_incidents.append(incident)


def test_rag_indexer_creates_embedding_documents():
    store = FakeStore()
    indexer = RAGIndexer(store)

    result = RCAResult(
        incident_id="incident_1",
        service="checkout",
        env="dev",
        severity="error",
        summary="Checkout exception",
        confidence=0.82,
        root_causes=[
            RootCauseHypothesis(
                hypothesis_id="hyp_1",
                title="Application exception",
                description="Trace error and log error agree.",
                category="application",
                confidence=0.82,
            )
        ],
    )
    documents = indexer.index_rca_result(result)

    assert len(documents) == 2
    assert all(document.embedding for document in documents)
    assert {document.source_type for document in documents} == {"rca_result", "evidence_summary"}
    assert len(store.documents) == 2


def test_rag_indexer_promotes_confirmed_historical_incident():
    store = FakeStore()
    store.rca_result = RCAResult(
        incident_id="incident_1",
        service="checkout",
        env="dev",
        severity="error",
        summary="Checkout exception",
        confidence=0.82,
    ).model_dump(mode="json")

    incident = RAGIndexer(store).promote_historical_incident(
        "incident_1",
        confirmed_root_cause="Confirmed application exception.",
    )

    assert incident is not None
    assert incident.root_cause == "Confirmed application exception."
    assert incident.embedding
    assert len(store.historical_incidents) == 1
