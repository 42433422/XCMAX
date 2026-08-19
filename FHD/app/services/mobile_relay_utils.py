"""Pure serialization and time helpers for mobile relay state."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.infrastructure.topology import FHD_API_BASE_URL


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _utc_after(seconds: int) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=max(60, int(seconds))))
        .replace(microsecond=0)
        .isoformat()
    )


def _epoch_from_iso(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return int(time.time())


def _json_dumps(value: Any) -> str:
    return json.dumps(value if isinstance(value, (dict, list)) else {}, ensure_ascii=False)


def _json_loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_dict(row: Any) -> dict[str, Any]:
    data = dict(row or {})
    for key in ("capabilities_json", "payload_json", "result_json"):
        if key in data:
            data[key.removesuffix("_json")] = _json_loads(data.pop(key))
    return data


def _public_base_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        value = FHD_API_BASE_URL
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/") + "/"
