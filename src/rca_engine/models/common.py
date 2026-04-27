from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["debug", "info", "warning", "error", "critical"]


class EvidenceRef(BaseModel):
    source: str
    ref_type: str
    ref_id: str | None = None
    query: str | None = None
    time_range: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
