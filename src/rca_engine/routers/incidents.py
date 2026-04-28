from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from rca_engine.models import HistoricalIncidentPromotionRequest

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("/candidates/latest")
def latest_incident_candidates(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    return {"items": request.app.state.store.latest_candidates(limit=limit), "limit": limit}


@router.get("/search")
def search_incidents(
    request: Request,
    q: str | None = None,
    service: str | None = None,
    env: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    return request.app.state.store.search_incidents(
        q=q,
        service=service,
        env=env,
        severity=severity,
        status=status,
        updated_from=updated_from,
        updated_to=updated_to,
        cursor=cursor,
        limit=limit,
        page=None if cursor else page,
        page_size=page_size,
    )


@router.get("/{incident_id}/graph")
def incident_graph(request: Request, incident_id: str) -> dict[str, object]:
    return request.app.state.store.get_incident_graph(incident_id)


@router.get("/{incident_id}/postmortem-draft")
def postmortem_draft(request: Request, incident_id: str) -> dict[str, object]:
    return request.app.state.copilot.postmortem_draft(incident_id).model_dump(mode="json")


@router.post("/{incident_id}/promote-historical")
def promote_historical_incident(
    request: Request,
    incident_id: str,
    promotion: HistoricalIncidentPromotionRequest | None = None,
) -> dict[str, object]:
    promotion = promotion or HistoricalIncidentPromotionRequest()
    incident = request.app.state.indexer.promote_historical_incident(
        incident_id,
        confirmed_root_cause=promotion.confirmed_root_cause,
        notes=promotion.notes,
    )
    if not incident:
        raise HTTPException(status_code=404, detail=f"RCA result not found: {incident_id}")
    return incident.model_dump(mode="json")
