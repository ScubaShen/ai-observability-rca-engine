from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/latest")
def latest_events(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    return {"items": request.app.state.store.latest_events(limit=limit), "limit": limit}


@router.get("/search")
def search_events(
    request: Request,
    q: str | None = None,
    service: str | None = None,
    env: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    event_time_from: str | None = None,
    event_time_to: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    return request.app.state.store.search_events(
        q=q,
        service=service,
        env=env,
        severity=severity,
        event_type=event_type,
        trace_id=trace_id,
        event_time_from=event_time_from,
        event_time_to=event_time_to,
        cursor=cursor,
        limit=limit,
        page=None if cursor else page,
        page_size=page_size,
    )
