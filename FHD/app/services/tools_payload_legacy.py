"""Legacy /api/tools/execute compatibility dispatcher."""

from __future__ import annotations

from app.services.tools_payload_basic import dispatch_basic_tool_payload
from app.services.tools_payload_customers import dispatch_customer_tool_payload
from app.services.tools_payload_dispatch_common import NOT_HANDLED
from app.services.tools_payload_operations import dispatch_operational_tool_payload

_DISPATCHERS = (
    dispatch_basic_tool_payload,
    dispatch_customer_tool_payload,
    dispatch_operational_tool_payload,
)


def dispatch_legacy_tool_payload(
    tool_id,
    action: str,
    params: dict,
    *,
    json_response_fn,
    hdr_getter,
    parse_order_text_fn,
):
    """Return the first matching legacy Werkzeug JSON response."""
    for dispatch in _DISPATCHERS:
        result = dispatch(
            tool_id,
            action,
            params,
            json_response_fn=json_response_fn,
            hdr_getter=hdr_getter,
            parse_order_text_fn=parse_order_text_fn,
        )
        if result is not NOT_HANDLED:
            return result
    return json_response_fn({"success": False, "message": f"未知工具: {tool_id}"}, 400)
