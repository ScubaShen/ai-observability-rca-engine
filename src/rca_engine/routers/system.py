from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    store = request.app.state.store
    indexer = request.app.state.indexer
    copilot = request.app.state.copilot
    return {
        "status": "ok",
        "service": "observability-rca-engine",
        "phase": "production-query-rca-llm",
        "rag": {
            "embedding_model": indexer.embedding_provider.model_name,
            "llm_provider": settings.llm_provider,
            "llm_enabled": copilot.llm.available(),
            "llm_model": settings.llm_model or "not_configured",
            "reasoning_effort": settings.llm_reasoning_effort,
            "streaming_enabled": settings.llm_streaming_enabled,
            "llm_rerank_enabled": settings.llm_rerank_enabled,
            "cache_ttl_seconds": settings.rag_cache_ttl_seconds,
        },
        "input_topics": list(settings.input_topics),
        "output_dir": str(settings.output_dir),
        "storage": store.storage_health(),
    }


@router.get("/storage/health")
def storage_health(request: Request) -> dict[str, object]:
    return request.app.state.store.storage_health()
