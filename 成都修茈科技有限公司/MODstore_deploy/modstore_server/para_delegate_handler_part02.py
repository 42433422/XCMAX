# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


def _fallback_order_tools() -> list[str]:
    configured = _facade().os.environ.get(
        "MODSTORE_PARA_TOOL_FALLBACK_ORDER", "cursor,claude_code,trae"
    )
    out: list[str] = []
    for value in configured.split(","):
        tool = _facade()._normalize_tool_name(value)
        if tool in _facade()._VALID_DEV_TOOLS and tool not in out:
            out.append(tool)
    return out


def _dev_tool() -> str:
    """loops 桥默认派给的设备工具(DevFleet devTool)，用于设备过滤。"""
    normalized = _facade()._normalize_tool_name(
        _facade().os.environ.get("MODSTORE_PARA_DEV_TOOL") or ""
    )
    if normalized in _facade()._VALID_DEV_TOOLS:
        return normalized
    order = _facade()._fallback_order_tools()
    return order[0] if order else "cursor"


def _customer_ticket_cloud_route(input_data: dict) -> dict:
    """客服工单优先派给云端执行器（Grok Bot）；需配 MODSTORE_PARA_TICKET_DEVICE_ID，显式 device_id 优先。"""
    env = _facade().os.environ
    device_id = (env.get("MODSTORE_PARA_TICKET_DEVICE_ID") or "").strip()
    if not device_id or input_data.get("device_id"):
        return {}
    if input_data.get("event_type") != "ops.intake.customer_ticket":
        return {}
    return {"device_id": device_id, "tool_name": env.get("MODSTORE_PARA_TICKET_TOOL") or "grok_bot"}
