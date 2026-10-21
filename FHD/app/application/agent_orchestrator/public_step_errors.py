"""Step failures that may be shown verbatim to the end user.

Tool errors stay behind the generic "详细信息已记录" message by default; only
error codes whose message is produced by our own code for the user are listed.
"""

from __future__ import annotations

from typing import Any

_USER_FACING_CODES = frozenset({"unresolved_param_reference"})


def public_step_error(step: Any, *, allow_reference_message: bool = True) -> str:
    output = getattr(step, "output", None)
    output = output if isinstance(output, dict) else {}
    code = str(output.get("error_code") or "")
    if (getattr(step, "tool_id", ""), getattr(step, "action", "")) in {
        ("shipment_orders", "generate"),
        ("shipment_records", "create"),
        ("business_event", "shipment_create"),
    }:
        from app.domain.shipment.shipment_quantities import shipment_quantity_hint

        if hint := shipment_quantity_hint(code):
            return hint
    if allow_reference_message and code in _USER_FACING_CODES:
        return str(output.get("message") or "")[:500]
    return ""


def public_run_error(run: Any) -> str:
    for step in getattr(run, "steps", []) or []:
        if getattr(step, "status", "") == "failed" and (text := public_step_error(step)):
            return text
    return ""
