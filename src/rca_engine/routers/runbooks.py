from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/runbooks", tags=["runbooks"])


@router.get("")
def runbooks(request: Request) -> dict[str, object]:
    return {"items": request.app.state.store.list_runbooks()}


@router.get("/{runbook_id}")
def runbook(request: Request, runbook_id: str) -> dict[str, object]:
    item = request.app.state.store.get_runbook(runbook_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail=f"Runbook not found: {runbook_id}")
