from rca_engine.models import CopilotRequest
from rca_engine.rag.copilot import RCACopilot
from rca_engine.rag.retriever import KnowledgeRetriever


class FakeStore:
    def __init__(self):
        self.traces = []

    def list_runbooks(self):
        return [
            {
                "runbook_id": "rb-application-exception",
                "title": "Application exception investigation",
                "categories": ["application"],
                "keywords": ["exception", "trace.error"],
                "steps": ["Open Loki.", "Open Tempo."],
            }
        ]

    def get_rca_result(self, incident_id):
        return {
            "incident_id": incident_id,
            "service": "checkout",
            "summary": "Application error or exception path",
            "root_causes": [{"title": "Application exception"}],
        }

    def get_agent_report(self, incident_id):
        return {
            "incident_id": incident_id,
            "summary": "Agent analysis for checkout",
            "agent_findings": [{"finding_type": "log_error_pattern"}],
        }

    def latest_rca_results(self, limit=10):
        return [self.get_rca_result("incident_1")]

    def latest_agent_reports(self, limit=10):
        return [self.get_agent_report("incident_1")]

    def search_rag_documents(self, query, embedding, incident_id=None, limit=10):
        return [
            {
                "document_id": "doc_1",
                "source_type": "rca_result",
                "ref_id": incident_id or "incident_1",
                "incident_id": incident_id or "incident_1",
                "service": "checkout",
                "env": "dev",
                "severity": "error",
                "title": "Checkout application exception",
                "content": "Checkout application exception with trace error evidence.",
                "score": 0.91,
                "metadata": {"evidence_event_ids": ["event_1"], "evidence_strength": "strong"},
            }
        ]

    def latest_events(self, limit=500):
        return []

    def get_incident_graph(self, incident_id):
        return {"incident_id": incident_id, "nodes": [], "relationships": []}

    def save_rag_query_trace(self, trace):
        self.traces.append(trace)


def test_knowledge_retriever_matches_runbook_and_incident_context():
    matches = KnowledgeRetriever(FakeStore()).search(
        "application exception",
        incident_id="incident_1",
        limit=5,
    )

    assert matches
    assert {match.source for match in matches}.intersection({"runbook", "rca_result", "agent_report"})


def test_copilot_returns_evidence_grounded_answer():
    response = RCACopilot(FakeStore()).answer(
        request=CopilotRequest(
            question="How do I investigate application exception?",
            incident_id="incident_1",
            limit=5,
        )
    )

    assert response.confidence > 0
    assert "Working summary:" in response.answer
    assert "Primary source:" in response.answer
    assert response.matches
    assert response.citations
    assert response.verification.status in {"confirmed", "likely"}
    assert response.latency_ms is not None
    assert response.response_path in {"fast", "fallback"}


def test_copilot_cache_marks_second_response_as_cache_hit():
    store = FakeStore()
    copilot = RCACopilot(store)
    request = CopilotRequest(question="What is the root cause?", incident_id="incident_1")

    first = copilot.answer(request)
    second = copilot.answer(request)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(store.traces) == 2
    assert store.traces[-1].cache_hit is True
