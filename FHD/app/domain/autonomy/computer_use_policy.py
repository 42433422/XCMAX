"""Pure outcome rules for verified and uncertain Computer Use effects."""

from __future__ import annotations

from typing import Any


def normalize_computer_effect(result: dict[str, Any]) -> dict[str, Any]:
    """Return a new receipt; uncertain input effects never permit blind replay."""
    result = dict(result)
    result["success"] = result.get("success") is True and result.get("verified") is True
    if result["success"]:
        result.pop("retryable", None)
    else:
        result["retryable"] = False
    if result.get("code") and not result.get("error_code"):
        result["error_code"] = result["code"]
    if result.get("success") is not True and (
        result.get("executed")
        or result.get("may_have_executed")
        or result.get("outcome_unknown")
        or result.get("steps_completed", 0)
        or result.get("status") == "outcome_unknown"
    ):
        result.update(outcome="unknown", reconciliation_required=True)
    return result
