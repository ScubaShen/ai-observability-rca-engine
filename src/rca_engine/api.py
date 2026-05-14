from __future__ import annotations

from fastapi import FastAPI

from rca_engine.config import Settings, load_settings
from rca_engine.rag.copilot import RCACopilot
from rca_engine.rag.embedding import build_embedding_provider
from rca_engine.rag.indexer import RAGIndexer
from rca_engine.rag.llm import LLMSettings
from rca_engine.rag.retriever import KnowledgeRetriever
from rca_engine.routers import agents, events, incidents, rag, rca, runbooks, system
from rca_engine.storage.factory import build_storage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = build_storage(settings)
    embedding_provider = build_embedding_provider(
        provider=settings.rag_embedding_provider,
        api_url=settings.rag_embedding_api_url,
        api_key=settings.rag_embedding_api_key,
        model=settings.rag_embedding_model,
        dimensions=settings.rag_embedding_dimensions,
        timeout_seconds=settings.rag_embedding_timeout_seconds,
    )
    retriever = KnowledgeRetriever(store, embedding_provider=embedding_provider)
    indexer = RAGIndexer(store, embedding_provider=embedding_provider)
    copilot = RCACopilot(
        store,
        llm_settings=LLMSettings(
            api_url=settings.llm_api_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            provider=settings.llm_provider,
            reasoning_effort=settings.llm_reasoning_effort,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            streaming_enabled=settings.llm_streaming_enabled,
            rerank_enabled=settings.llm_rerank_enabled,
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
    app.state.settings = settings
    app.state.store = store
    app.state.embedding_provider = embedding_provider
    app.state.retriever = retriever
    app.state.indexer = indexer
    app.state.copilot = copilot

    app.include_router(system.router)
    app.include_router(events.router)
    app.include_router(incidents.router)
    app.include_router(rca.router)
    app.include_router(agents.router)
    app.include_router(runbooks.router)
    app.include_router(rag.router)
    return app


app = create_app()
