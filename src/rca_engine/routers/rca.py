from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/rca", tags=["rca"])


@router.get("/latest")
def latest_rca_results(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {"items": request.app.state.store.latest_rca_results(limit=limit), "limit": limit}


@router.get("/{incident_id}")
def rca_result_by_incident_id(request: Request, incident_id: str) -> dict[str, object]:
    item = request.app.state.store.get_rca_result(incident_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail=f"RCA result not found: {incident_id}")
