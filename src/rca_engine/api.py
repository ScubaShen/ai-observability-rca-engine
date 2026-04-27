from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from rca_engine.config import Settings, load_settings
from rca_engine.models import CopilotFeedback, CopilotRequest, HistoricalIncidentPromotionRequest
from rca_engine.rag.copilot import RCACopilot
from rca_engine.rag.embedding import HashEmbeddingProvider
from rca_engine.rag.indexer import RAGIndexer
from rca_engine.rag.llm import LLMSettings
from rca_engine.rag.retriever import KnowledgeRetriever
from rca_engine.storage.factory import build_storage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = build_storage(settings)
    embedding_provider = HashEmbeddingProvider(dimensions=settings.rag_embedding_dimensions)
    retriever = KnowledgeRetriever(store, embedding_provider=embedding_provider)
    indexer = RAGIndexer(store, embedding_provider=embedding_provider)
    copilot = RCACopilot(
        store,
        llm_settings=LLMSettings(
            api_url=settings.llm_api_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            enabled=settings.llm_enabled,
        ),
        cache_ttl_seconds=settings.rag_cache_ttl_seconds,
        embedding_provider=embedding_provider,
    )
    app = FastAPI(
        title="Observability RCA Engine",
        version="0.1.0",
        description="Incident correlation, deterministic RCA, retrieval, and operator workflow API.",
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "observability-rca-engine",
            "rag": {
                "embedding_model": indexer.embedding_provider.model_name,
                "llm_enabled": settings.llm_enabled,
                "llm_model": settings.llm_model or "not_configured",
                "cache_ttl_seconds": settings.rag_cache_ttl_seconds,
            },
            "input_topics": list(settings.input_topics),
            "output_dir": str(settings.output_dir),
            "storage": store.storage_health(),
        }

    @app.get("/storage/health")
    def storage_health() -> dict[str, object]:
        return store.storage_health()

    # Core event and incident queries are intentionally read-only so the API can
    # be used safely by dashboards and operator tooling without mutating state.
    @app.get("/events/latest")
    def latest_events(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
        return {
            "items": store.latest_events(limit=limit),
            "limit": limit,
        }

    @app.get("/incidents/candidates/latest")
    def latest_incident_candidates(
        limit: int = Query(default=50, ge=1, le=500)
    ) -> dict[str, object]:
        return {
            "items": store.latest_candidates(limit=limit),
            "limit": limit,
        }

    @app.get("/rca/latest")
    def latest_rca_results(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
        return {
            "items": store.latest_rca_results(limit=limit),
            "limit": limit,
        }

    @app.get("/rca/{incident_id}")
    def rca_result_by_incident_id(incident_id: str) -> dict[str, object]:
        item = store.get_rca_result(incident_id)
        if item:
            return item
        raise HTTPException(status_code=404, detail=f"RCA result not found: {incident_id}")

    @app.get("/agents/reports/latest")
    def latest_agent_reports(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
        return {
            "items": store.latest_agent_reports(limit=limit),
            "limit": limit,
        }

    @app.get("/agents/reports/{incident_id}")
    def agent_report_by_incident_id(incident_id: str) -> dict[str, object]:
        item = store.get_agent_report(incident_id)
        if item:
            return item
        raise HTTPException(status_code=404, detail=f"Agent report not found: {incident_id}")

    @app.get("/incidents/{incident_id}/graph")
    def incident_graph(incident_id: str) -> dict[str, object]:
        return store.get_incident_graph(incident_id)

    @app.get("/runbooks")
    def runbooks() -> dict[str, object]:
        return {"items": store.list_runbooks()}

    @app.get("/runbooks/{runbook_id}")
    def runbook(runbook_id: str) -> dict[str, object]:
        item = store.get_runbook(runbook_id)
        if item:
            return item
        raise HTTPException(status_code=404, detail=f"Runbook not found: {runbook_id}")

    # Retrieval endpoints expose stored context, query traces, and feedback loops.
    # They are grouped here because they share the same retrieval/indexing boundary.
    @app.get("/knowledge/search")
    def knowledge_search(
        q: str = Query(min_length=1),
        incident_id: str | None = None,
        limit: int = Query(default=5, ge=1, le=20),
    ) -> dict[str, object]:
        intent, matches = retriever.search_with_intent(q, incident_id, limit)
        return {
            "items": [item.model_dump(mode="json") for item in matches],
            "query": q,
            "incident_id": incident_id,
            "limit": limit,
            "intent": intent.intent,
        }

    @app.post("/copilot/chat")
    def copilot_chat(request: CopilotRequest) -> dict[str, object]:
        return copilot.answer(request).model_dump(mode="json")

    @app.get("/copilot/sessions")
    def copilot_sessions(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
        return {"items": store.latest_rag_query_traces(limit=limit), "limit": limit}

    @app.post("/copilot/feedback")
    def copilot_feedback(feedback: CopilotFeedback) -> dict[str, object]:
        store.save_copilot_feedback(feedback)
        return {"status": "ok", "feedback_id": feedback.feedback_id}

    @app.get("/rag/evaluations")
    def rag_evaluations(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
        traces = store.latest_rag_query_traces(limit=limit)
        feedback = store.latest_copilot_feedback(limit=limit)
        return {
            "traces": traces,
            "feedback": feedback,
            "metrics": _rag_metrics(traces, feedback),
        }

    @app.post("/rag/reindex")
    def rag_reindex(limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, object]:
        return indexer.rebuild(limit=limit)

    @app.get("/incidents/{incident_id}/postmortem-draft")
    def postmortem_draft(incident_id: str) -> dict[str, object]:
        return copilot.postmortem_draft(incident_id).model_dump(mode="json")

    @app.post("/incidents/{incident_id}/promote-historical")
    def promote_historical_incident(
        incident_id: str,
        request: HistoricalIncidentPromotionRequest | None = None,
    ) -> dict[str, object]:
        request = request or HistoricalIncidentPromotionRequest()
        incident = indexer.promote_historical_incident(
            incident_id,
            confirmed_root_cause=request.confirmed_root_cause,
            notes=request.notes,
        )
        if not incident:
            raise HTTPException(status_code=404, detail=f"RCA result not found: {incident_id}")
        return incident.model_dump(mode="json")

    return app


app = create_app()


def _rag_metrics(traces: list[dict], feedback: list[dict]) -> dict[str, object]:
    if not traces:
        return {
            "queries": 0,
            "p95_latency_ms": 0,
            "cache_hit_rate": 0.0,
            "feedback_count": len(feedback),
        }
    latencies = sorted(int(item.get("latency_ms") or 0) for item in traces)
    p95_index = min(int(len(latencies) * 0.95), len(latencies) - 1)
    cache_hits = len([item for item in traces if item.get("cache_hit")])
    return {
        "queries": len(traces),
        "p95_latency_ms": latencies[p95_index],
        "cache_hit_rate": round(cache_hits / len(traces), 4),
        "feedback_count": len(feedback),
    }
