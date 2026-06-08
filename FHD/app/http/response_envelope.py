"""Standard API response envelope (success field SSOT)."""

from __future__ import annotations

from typing import Any


def ok(data: Any = None, *, message: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a success JSON envelope."""
    out: dict[str, Any] = {"success": True}
    if data is not None:
        out["data"] = data
    if message is not None:
        out["message"] = message
    out.update(extra)
    return out


def fail(
    message: str,
    *,
    error_code: str | None = None,
    data: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build an error JSON envelope."""
    out: dict[str, Any] = {"success": False, "message": message}
    if error_code is not None:
        out["error_code"] = error_code
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out


def read_success(payload: dict[str, Any] | None, *, default: bool = True) -> bool:
    """Read boolean outcome from API or service envelope."""
    if not isinstance(payload, dict):
        return default
    if "success" in payload:
        return bool(payload["success"])
    if "ok" in payload:
        return bool(payload["ok"])
    return default


def from_legacy_ok_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Map legacy ``{ok: bool, ...}`` payloads to the standard envelope."""
    if not isinstance(data, dict):
        return ok(data)
    success = read_success(data)
    body = dict(data)
    body.pop("ok", None)
    body["success"] = success
    return body
