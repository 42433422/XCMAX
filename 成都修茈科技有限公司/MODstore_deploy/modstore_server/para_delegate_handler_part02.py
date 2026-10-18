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


_TICKET_EVENT = "ops.intake.customer_ticket"
# 云端执行器回报"处理不了"时的显式标记（大小写不敏感）；命中即转下一跳。
_TICKET_CANNOT_HANDLE_MARKERS = ("cannot_handle", "无法处理此工单", "无法处理该工单")
# 与执行器无关的配置/前置失败：换下一跳结果相同，不转交。
_TICKET_NO_HANDOFF_STATUSES = frozenset(
    {"awaiting_para_dispatcher", "blocked_missing_repo_url", "blocked_git_preflight"}
)


def _ticket_route_hops(input_data: dict) -> list[dict]:
    """解析工单专用有序路由 MODSTORE_PARA_TICKET_ROUTE="grok_bot@<设备>,dolt@<设备>"。

    只对客服工单生效，显式 device_id 优先；格式不对或工具未知的跳过；未配置返回 []。
    """
    if input_data.get("device_id") or input_data.get("event_type") != _TICKET_EVENT:
        return []
    hops: list[dict] = []
    for item in (_facade().os.environ.get("MODSTORE_PARA_TICKET_ROUTE") or "").split(","):
        tool_raw, sep, device_id = item.strip().partition("@")
        tool = _facade()._normalize_tool_name(tool_raw)
        hop = {"tool_name": tool, "device_id": device_id.strip()}
        if sep and hop["device_id"] and tool in _facade()._VALID_DEV_TOOLS and hop not in hops:
            hops.append(hop)
    return hops


def _customer_ticket_cloud_route(input_data: dict) -> dict:
    """客服工单优先派给云端执行器（Grok Bot）；显式 device_id 优先。

    配了 MODSTORE_PARA_TICKET_ROUTE 时按有序路由，首跳先用，失败再由 _post_ticket_route 转下一跳；
    否则保持原行为：MODSTORE_PARA_TICKET_DEVICE_ID + MODSTORE_PARA_TICKET_TOOL（默认 grok_bot）。
    """
    hops = _facade()._ticket_route_hops(input_data)
    if hops:
        return {**hops[0], "_ticket_route": hops}
    env = _facade().os.environ
    device_id = (env.get("MODSTORE_PARA_TICKET_DEVICE_ID") or "").strip()
    if not device_id or input_data.get("device_id"):
        return {}
    if input_data.get("event_type") != _TICKET_EVENT:
        return {}
    return {"device_id": device_id, "tool_name": env.get("MODSTORE_PARA_TICKET_TOOL") or "grok_bot"}


def _ticket_hop_should_handoff(result: dict) -> bool:
    """工单跳失败、超时或回报"无法处理"时转下一跳；只用于工单路由，不影响自维护回退。"""
    if not isinstance(result, dict):
        return True
    if str(result.get("status") or "") in _TICKET_NO_HANDOFF_STATUSES:
        return False
    if not result.get("ok"):
        return True
    para_result = result.get("para_result")
    snapshot: dict = para_result if isinstance(para_result, dict) else {}
    texts = [str(result.get("error") or "")]
    texts += [
        str(sub.get("last_error") or "")
        for sub in snapshot.get("subtasks") or []
        if isinstance(sub, dict)
    ]
    texts += [
        str(log.get("content") or "")
        for log in snapshot.get("logs_tail") or []
        if isinstance(log, dict)
    ]
    text = " ".join(texts).lower()
    return any(marker in text for marker in _TICKET_CANNOT_HANDLE_MARKERS)


def _post_ticket_route(req: dict, hops: list[dict]) -> dict:
    """按有序路由逐跳派单：每跳固定自己的设备和工具（不在跳内换工具），需要时转下一跳。"""
    attempts: list[dict] = []
    result: dict = {}
    for index, hop in enumerate(hops):
        raw = dict(req.get("raw_input") or {})
        raw.update({**hop, "allow_tool_fallback": "0"})
        hop_req = {**req, **hop, "allow_tool_fallback": "0", "raw_input": raw}
        if index:
            hop_req.pop("para_task_id", None)
        result = _facade()._post_para_api_once(hop_req)
        if not _facade()._ticket_hop_should_handoff(result) or index == len(hops) - 1:
            break
        attempts.append(
            {
                **hop,
                "status": result.get("status") if isinstance(result, dict) else "",
                "error": (
                    str((result or {}).get("error") or "")[:500] if isinstance(result, dict) else ""
                ),
            }
        )
    if isinstance(result, dict):
        result["ticket_route"] = [hop["tool_name"] for hop in hops]
        if attempts:
            result["ticket_route_handoffs"] = attempts
    return result
