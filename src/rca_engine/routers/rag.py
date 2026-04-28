from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from rca_engine.models import CopilotFeedback, CopilotRequest

router = APIRouter(tags=["rag-copilot"])


@router.get("/knowledge/search")
def knowledge_search(
    request: Request,
    q: str = Query(min_length=1),
    incident_id: str | None = None,
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, object]:
    intent, matches = request.app.state.retriever.search_with_intent(q, incident_id, limit)
    return {
        "items": [item.model_dump(mode="json") for item in matches],
        "query": q,
        "incident_id": incident_id,
        "limit": limit,
        "intent": intent.intent,
    }


@router.post("/copilot/chat")
def copilot_chat(request: Request, payload: CopilotRequest) -> dict[str, object]:
    return request.app.state.copilot.answer(payload).model_dump(mode="json")


@router.post("/copilot/chat/stream")
def copilot_chat_stream(request: Request, payload: CopilotRequest) -> StreamingResponse:
    return StreamingResponse(
        request.app.state.copilot.stream_answer(payload),
        media_type="text/event-stream",
    )


@router.get("/copilot/sessions")
def copilot_sessions(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return {"items": request.app.state.store.latest_rag_query_traces(limit=limit), "limit": limit}


@router.post("/copilot/feedback")
def copilot_feedback(request: Request, feedback: CopilotFeedback) -> dict[str, object]:
    request.app.state.store.save_copilot_feedback(feedback)
    return {"status": "ok", "feedback_id": feedback.feedback_id}


@router.get("/rag/evaluations")
def rag_evaluations(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    traces = request.app.state.store.latest_rag_query_traces(limit=limit)
    feedback = request.app.state.store.latest_copilot_feedback(limit=limit)
    return {"traces": traces, "feedback": feedback, "metrics": _rag_metrics(traces, feedback)}


@router.post("/rag/reindex")
def rag_reindex(request: Request, limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, object]:
    return request.app.state.indexer.rebuild(limit=limit)


def _rag_metrics(traces: list[dict], feedback: list[dict]) -> dict[str, object]:
    if not traces:
        return {
            "queries": 0,
            "p95_latency_ms": 0,
            "cache_hit_rate": 0.0,
            "fallback_rate": 0.0,
            "recall_source_distribution": {},
            "llm_usage": {},
            "feedback_count": len(feedback),
        }
    latencies = sorted(int(item.get("latency_ms") or 0) for item in traces)
    p95_index = min(int(len(latencies) * 0.95), len(latencies) - 1)
    cache_hits = len([item for item in traces if item.get("cache_hit")])
    fallback_count = len([item for item in traces if item.get("fallback_reason")])
    recall_counts: dict[str, int] = {}
    llm_usage: dict[str, int] = {}
    for item in traces:
        for source, count in (item.get("recall_source_counts") or {}).items():
            recall_counts[source] = recall_counts.get(source, 0) + int(count)
        model = item.get("llm_model") or "not_configured"
        provider = item.get("llm_provider") or "disabled"
        if provider != "disabled" and model != "not_configured":
            llm_usage[f"{provider}:{model}"] = llm_usage.get(f"{provider}:{model}", 0) + 1
    return {
        "queries": len(traces),
        "p95_latency_ms": latencies[p95_index],
        "cache_hit_rate": round(cache_hits / len(traces), 4),
        "fallback_rate": round(fallback_count / len(traces), 4),
        "recall_source_distribution": recall_counts,
        "llm_usage": llm_usage,
        "feedback_count": len(feedback),
    }
