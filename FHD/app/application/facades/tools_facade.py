from app.services.tools_execution_service import (
    _parse_order_text,
    execute_registered_workflow_tool,
    execute_tool_from_payload,
    get_workflow_tool_registry,
    set_tool_execute_headers,
)

__all__ = [
    "_parse_order_text",
    "execute_registered_workflow_tool",
    "execute_tool_from_payload",
    "get_workflow_tool_registry",
    "run_archive_tools_execute",
    "set_tool_execute_headers",
]


def run_archive_tools_execute(
    body: dict | None,
    *,
    owner_user_id: int | None = None,
) -> tuple[dict, int]:
    """
    Execute a workflow-tool payload and unpack the legacy JSON response shape.

    The public HTTP route still has to preserve the old response contract, but
    callers should import this facade instead of the removed historical route shim.
    """
    # ``owner_user_id`` is intentionally an out-of-band, route-injected value.
    # It must never be reconstructed from the legacy JSON body or request
    # headers: shipment template selection is private to the authenticated ETL
    # template owner.
    raw = execute_tool_from_payload(body or {}, owner_user_id=owner_user_id)

    if isinstance(raw, tuple):
        resp = raw[0]
        code = int(raw[1]) if len(raw) > 1 else 200
    else:
        resp = raw
        code = int(getattr(resp, "status_code", 200) or 200)

    get_json = getattr(resp, "get_json", None)
    if callable(get_json):
        data = get_json(silent=True)
        if isinstance(data, dict):
            return data, code
        return {"success": False, "message": "invalid tools response"}, 500

    return {"success": False, "message": "invalid tools response"}, 500
