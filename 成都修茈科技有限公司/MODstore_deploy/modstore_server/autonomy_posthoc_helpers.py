# mypy: disable-error-code="union-attr"
"""Pure normalization helpers for post-execution autonomy verification."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10


def utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def payload(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def safe_repo_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or Path(raw).is_absolute():
        return ""
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def recorded_at_or_after(record: dict[str, Any], allowed_at: datetime) -> bool:
    raw = str(
        record.get("created_at") or record.get("completed_at") or record.get("observed_at") or ""
    ).strip()
    if not raw:
        return False
    try:
        return utc(datetime.fromisoformat(raw.replace("Z", "+00:00"))) >= utc(allowed_at)
    except ValueError:
        return False


def failed_merge_request_attempt(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for record in reversed(records):
        policy = (
            record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        )
        if (
            str(record.get("phase") or "") == "complete"
            and str(record.get("status") or "") == "completed_held_for_remediation"
            and str(policy.get("action") or "") == "hold_for_automated_remediation"
            and str(policy.get("reason") or "") == "para_merge_request_failed"
            and str(record.get("para_task_id") or "").strip()
            and str(record.get("branch") or "").strip()
        ):
            return record
    return None
