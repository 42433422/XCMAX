from __future__ import annotations

import logging

from app.services.tools_execution.context import _hdr, _j
from app.services.tools_execution.order_parser import _parse_order_text
from app.services.tools_execution.registry import (
    _normalize_action,
    _validate_required_params,
    get_workflow_tool_registry,
)
from app.services.tools_payload_legacy import dispatch_legacy_tool_payload
from app.services.tools_workflow_registered import execute_registered_workflow_tool
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _normalize_trusted_owner_user_id(value):
    """Accept only a positive route-injected owner id.

    This helper deliberately has no knowledge of HTTP headers or JSON payloads.
    Callers at the route boundary own authentication and may pass the resulting
    identity through this internal argument.
    """

    try:
        owner_user_id = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return owner_user_id if owner_user_id > 0 else None


def execute_tool_from_payload(data, *, owner_user_id=None):
    return _execute_tool_from_payload_inner(data, owner_user_id=owner_user_id)


def _execute_tool_from_payload_inner(data, *, owner_user_id=None):
    try:
        # Tool parameters can contain a one-time print capability (and other
        # credentials).  Record structure for diagnostics, never raw payloads.
        logger.info(
            "[DEBUG] /api/tools/execute 收到请求 - keys: %s",
            sorted(str(key) for key in data.keys()) if isinstance(data, dict) else [],
        )

        if not data:
            logger.error("[DEBUG] /api/tools/execute 请求数据为空")
            return _j({"success": False, "message": "未收到数据"}, 400)

        tool_id = data.get("tool_id")
        action = _normalize_action(data.get("action", "view"), data.get("params") or {})
        params = data.get("params") or {}

        valid, err_msg = _validate_required_params(str(tool_id or "").strip(), action, params)
        if not valid:
            return _j(
                {
                    "success": False,
                    "error_code": "missing_required_params",
                    "message": err_msg,
                },
                400,
            )

        registry = get_workflow_tool_registry()
        if tool_id in registry and action in registry[tool_id].get("actions", {}):
            routed = execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
            status_code = 200 if routed.get("success") else 400
            return _j(routed, status_code)

        logger.info(
            "[DEBUG] tool_id=%s, action=%s, params_keys=%s", tool_id, action, list(params.keys())
        )
        if "order_text" in params:
            logger.info(
                "[DEBUG] order_text_present=true length=%s",
                len(str(params.get("order_text") or "")),
            )

        return dispatch_legacy_tool_payload(
            tool_id,
            action,
            params,
            json_response_fn=_j,
            hdr_getter=_hdr,
            parse_order_text_fn=_parse_order_text,
            owner_user_id=_normalize_trusted_owner_user_id(owner_user_id),
        )

    except RECOVERABLE_ERRORS as e:
        logger.error("执行工具失败: %s", e)
        return _j({"success": False, "message": str(e)}, 500)
