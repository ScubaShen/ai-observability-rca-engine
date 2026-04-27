from __future__ import annotations

from datetime import datetime, timezone


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unix_nano_to_iso(value: int | None) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def floor_time_window(value: str, seconds: int) -> tuple[str, str]:
    parsed = parse_iso(value)
    epoch = int(parsed.timestamp())
    start_epoch = epoch - (epoch % seconds)
    end_epoch = start_epoch + seconds
    start = datetime.fromtimestamp(start_epoch, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(end_epoch, tz=timezone.utc).isoformat()
    return start, end
