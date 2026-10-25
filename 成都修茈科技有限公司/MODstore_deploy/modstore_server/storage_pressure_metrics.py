"""Environment parsing and threshold calculations for storage self-healing."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Dict

GIB = 1024**3


def utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def bounded_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def pressure_thresholds() -> Dict[str, Any]:
    trigger_free_gib = bounded_env_float("MODSTORE_STORAGE_MIN_FREE_GIB", 10.0, 0.25, 4096.0)
    trigger_used_percent = bounded_env_float("MODSTORE_STORAGE_MAX_USED_PERCENT", 90.0, 50.0, 99.9)
    recovery_free_gib = bounded_env_float(
        "MODSTORE_STORAGE_RECOVERY_MIN_FREE_GIB",
        max(12.0, trigger_free_gib),
        trigger_free_gib,
        4096.0,
    )
    recovery_used_percent = bounded_env_float(
        "MODSTORE_STORAGE_RECOVERY_MAX_USED_PERCENT",
        min(88.0, trigger_used_percent),
        40.0,
        trigger_used_percent,
    )
    return {
        "trigger_min_free_bytes": int(trigger_free_gib * GIB),
        "trigger_max_used_percent": trigger_used_percent,
        "recovery_min_free_bytes": int(recovery_free_gib * GIB),
        "recovery_max_used_percent": recovery_used_percent,
    }


def pressure_reasons(snapshot: Dict[str, Any], thresholds: Dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if int(snapshot.get("free_bytes") or 0) < int(thresholds["trigger_min_free_bytes"]):
        reasons.append("free_bytes_below_threshold")
    if float(snapshot.get("used_percent") or 0.0) >= float(thresholds["trigger_max_used_percent"]):
        reasons.append("used_percent_at_or_above_threshold")
    return reasons


def recovery_verified(snapshot: Dict[str, Any], thresholds: Dict[str, Any]) -> bool:
    """Use hysteresis so a tiny reclaim does not cause repair/flap claims."""
    return int(snapshot.get("free_bytes") or 0) >= int(
        thresholds["recovery_min_free_bytes"]
    ) and float(snapshot.get("used_percent") or 0.0) <= float(
        thresholds["recovery_max_used_percent"]
    )


def parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return utc(parsed)


def build_storage_pressure_status(rows: list[Dict[str, Any]], audit_file: str) -> Dict[str, Any]:
    latest = rows[-1] if rows else None
    return {
        "ok": bool(latest and latest.get("ok") is True),
        "latest": latest,
        "runs": rows,
        "run_count": len(rows),
        "audit_path": audit_file,
    }
