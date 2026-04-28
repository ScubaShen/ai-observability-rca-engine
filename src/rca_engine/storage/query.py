from __future__ import annotations

import base64
import json
import math
from datetime import datetime
from typing import Any

from rca_engine.timeutils import parse_iso


def encode_cursor(sort_value: str, item_id: str) -> str:
    payload = {"sort": sort_value, "id": item_id}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    sort_value = payload.get("sort")
    item_id = payload.get("id")
    if not sort_value or not item_id:
        return None
    return str(sort_value), str(item_id)


def paginate_desc(
    rows: list[dict[str, Any]],
    *,
    sort_key: str,
    id_key: str,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    cursor_value = decode_cursor(cursor)
    filtered = rows
    if cursor_value:
        cursor_sort, cursor_id = cursor_value
        filtered = [
            row
            for row in rows
            if _desc_key(row.get(sort_key), row.get(id_key)) > _desc_key(cursor_sort, cursor_id)
        ]
    page = filtered[:limit]
    next_cursor = None
    if len(filtered) > limit and page:
        last = page[-1]
        next_cursor = encode_cursor(str(last.get(sort_key)), str(last.get(id_key)))
    return {"items": page, "limit": limit, "next_cursor": next_cursor}


def paginate_page(rows: list[dict[str, Any]], *, page: int, page_size: int) -> dict[str, Any]:
    page = max(page, 1)
    page_size = max(page_size, 1)
    total = len(rows)
    total_pages = math.ceil(total / page_size) if total else 0
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": rows[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": total_pages > 0 and page > 1,
    }


def sort_desc(rows: list[dict[str, Any]], *, sort_key: str, id_key: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: _desc_key(row.get(sort_key), row.get(id_key)))


def _desc_key(sort_value: Any, item_id: Any) -> tuple[float, str]:
    try:
        timestamp = parse_iso(str(sort_value)).timestamp()
    except Exception:  # noqa: BLE001
        try:
            timestamp = datetime.fromisoformat(str(sort_value).replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            timestamp = 0.0
    return (-timestamp, str(item_id or ""))
