"""HTTP status recovery for routes backed by the Agent runtime."""

from __future__ import annotations

from typing import Any


def agent_route_http_status(
    payload: dict[str, Any],
    *,
    failure_status: int = 400,
    success_status: int = 200,
) -> int:
    """Preserve the domain status hidden by semantic-verification envelopes."""

    if payload.get("success") is True:
        return success_status

    raw_output = payload.get("raw_output")
    candidates = [payload]
    if isinstance(raw_output, dict):
        candidates.append(raw_output)

    for candidate in candidates:
        for key in ("http_status_code", "status_code"):
            try:
                status_code = int(candidate.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if 400 <= status_code < 600:
                return status_code

    error_codes = {
        str(candidate.get("error_code") or "").strip()
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    if error_codes.intersection(
        {
            "tool_exception",
            "excel_vector_exception",
            "http_exception",
        }
    ):
        return 500
    return failure_status


def restore_agent_domain_error(payload: dict[str, Any]) -> dict[str, Any]:
    """Expose a tool's stable domain error while retaining Agent verification."""

    if str(payload.get("error_code") or "") != "semantic_verification_failed":
        return payload
    raw_output = payload.get("raw_output")
    if not isinstance(raw_output, dict) or raw_output.get("success") is not False:
        return payload

    restored = dict(raw_output)
    for key in ("run_id", "agent_run_id", "agent_status", "verification"):
        if key in payload:
            restored[key] = payload[key]
    restored["agent_verification_error_code"] = "semantic_verification_failed"
    return restored


__all__ = ["agent_route_http_status", "restore_agent_domain_error"]
