from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/reports/latest")
def latest_agent_reports(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {"items": request.app.state.store.latest_agent_reports(limit=limit), "limit": limit}


@router.get("/reports/{incident_id}")
def agent_report_by_incident_id(request: Request, incident_id: str) -> dict[str, object]:
    item = request.app.state.store.get_agent_report(incident_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail=f"Agent report not found: {incident_id}")
