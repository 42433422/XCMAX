# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.customer_issue_delivery_contract import (
    execution_requires_reconciliation,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS


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

    配了 MODSTORE_PARA_TICKET_ROUTE 时按有序路由；只有证实未提交且无排队工作才转下一跳。
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
    return {
        "device_id": device_id,
        "tool_name": env.get("MODSTORE_PARA_TICKET_TOOL") or "grok_bot",
    }


def _ticket_hop_should_handoff(result: dict) -> bool:
    """Only local pre-POST refusal proves safety; failure/logs do not confirm termination."""
    return (
        isinstance(result, dict)
        and result.get("ok") is False
        and result.get("status") == "blocked_no_online_para_device"
        and result.get("accepted") is False
        and result.get("queued") is False
        and not any(result.get(key) for key in ("outbox_path", "task_id", "devices", "para_result"))
    )


def _post_ticket_route(req: dict, hops: list[dict]) -> dict:
    """固定每跳设备和工具；结果不明时保留待核对，不再次派单。"""
    attempts: list[dict] = []
    result: dict = {}
    for index, hop in enumerate(hops):
        raw = dict(req.get("raw_input") or {})
        raw.update({**hop, "allow_tool_fallback": "0"})
        hop_req = {**req, **hop, "allow_tool_fallback": "0", "raw_input": raw}
        result = _facade()._post_para_api_once(hop_req)
        if not isinstance(result, dict):
            result = {"ok": False, "status": "para_ticket_requires_reconciliation"}
        safe = not req.get("para_task_id") and _facade()._ticket_hop_should_handoff(result)
        if not result.get("ok") and result.get("status") not in _TICKET_NO_HANDOFF_STATUSES:
            result["ticket_route_requires_reconciliation"] = not safe
        if not safe or index == len(hops) - 1:
            break
        attempts.append(
            dict(hop, status=result["status"], error=str(result.get("error") or "")[:500])
        )
    result["ticket_route"] = [hop["tool_name"] for hop in hops]
    if attempts:
        result["ticket_route_handoffs"] = attempts
    return result


def _wait_for_para_task(
    client: _facade().httpx.Client,
    base: str,
    token: str,
    task_id: str,
    req: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    deadline = _facade().time.monotonic() + _facade()._wait_timeout_sec(req)
    last_body: _facade().Any = {}
    terminal = {"completed", "merged", "failed", "merge_conflict"}
    from modstore_server.customer_issue_delivery_contract import para_task_succeeded

    while True:
        resp = client.get(
            f"{base}/api/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"}
        )
        try:
            body = resp.json() if resp.content else {}
        except RECOVERABLE_ERRORS:
            body = {"raw": resp.text[:4000]}
        last_body = body
        if resp.status_code >= 400:
            return {
                "ok": False,
                "status": "para_task_poll_failed",
                "status_code": resp.status_code,
                "error": str(
                    body.get("error") or body.get("detail") or resp.text[:500]
                    if isinstance(body, dict)
                    else resp.text[:500]
                ),
                "snapshot": _facade()._task_result_snapshot(body),
            }
        task = (
            body.get("task")
            if isinstance(body, dict) and isinstance(body.get("task"), dict)
            else {}
        )
        status = str(task.get("status") or "").strip()
        if str(task.get("id") or "") != task_id:
            return {
                "ok": False,
                "outcome": "unknown",
                "requires_reconciliation": True,
                "status": "para_task_identity_mismatch",
                "error": "Para returned a different task identity",
                "snapshot": _facade()._task_result_snapshot(body),
            }
        if status in terminal:
            snapshot = _facade()._task_result_snapshot(body)
            ok = para_task_succeeded(
                task, task_id, req.get("required_subtask_ids"), req.get("planned_devices")
            )
            incomplete = status in {"completed", "merged"} and not ok
            return {
                "ok": ok,
                "status": "para_task_incomplete" if incomplete else "para_task_" + status,
                "error": "" if ok else _facade()._first_para_error(snapshot),
                "snapshot": snapshot,
            }
        if _facade().time.monotonic() >= deadline:
            snapshot = _facade()._task_result_snapshot(last_body)
            return {
                "ok": False,
                "status": "para_task_timeout",
                "error": f"Para task {task_id} 未在 {_facade()._wait_timeout_sec(req):.0f}s 内完成",
                "snapshot": snapshot,
            }
        _facade().time.sleep(_facade()._wait_poll_sec())


def _req_with_excluded_tools(
    req: _facade().Dict[str, _facade().Any], excluded: set[str]
) -> _facade().Dict[str, _facade().Any]:
    work = dict(req or {})
    raw = dict(work.get("raw_input") or {}) if isinstance(work.get("raw_input"), dict) else {}
    merged = sorted(set(excluded) | _facade()._excluded_tools(work))
    raw["_para_exclude_tools"] = merged
    work["raw_input"] = raw
    work["_para_exclude_tools"] = merged
    work.pop("para_task_id", None)
    return work


def _attach_tool_fallback_meta(
    result: _facade().Dict[str, _facade().Any], *, attempts: list
) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(result, dict):
        return result
    if attempts:
        result["tool_fallback_attempts"] = list(attempts)
        result["tool_fallback_used"] = True
    return result


def _post_para_api(
    req: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    attempts: list = []
    excluded: set[str] = set(_facade()._excluded_tools(req))
    result = _facade()._post_para_api_once(req)
    fallback_budget = max(0, len(_facade()._tool_candidates(req)) - 1)
    for _ in range(fallback_budget):
        if bool(result.get("ok")) or execution_requires_reconciliation(result):
            return _facade()._attach_tool_fallback_meta(result, attempts=attempts)
        if not _facade()._tool_fallback_allowed(req):
            return _facade()._attach_tool_fallback_meta(result, attempts=attempts)
        used_tool = ""
        for item in result.get("devices") or []:
            if isinstance(item, dict) and str(item.get("tool_name") or "").strip():
                used_tool = str(item.get("tool_name") or "").strip()
                break
        if not used_tool:
            used_tool = str(
                (result.get("request") or {}).get("tool_name")
                if isinstance(result.get("request"), dict)
                else ""
            ).strip()
        if used_tool not in _facade()._VALID_DEV_TOOLS:
            candidates = _facade()._tool_candidates(
                _facade()._req_with_excluded_tools(req, excluded)
            )
            used_tool = candidates[0] if candidates else ""
        if not used_tool or used_tool in excluded:
            return _facade()._attach_tool_fallback_meta(result, attempts=attempts)
        if not _facade()._is_cli_runtime_failure(
            error=str(result.get("error") or ""),
            status=str(result.get("status") or ""),
            snapshot=result.get("para_result"),
            api_error=str(result.get("error") or ""),
        ):
            return _facade()._attach_tool_fallback_meta(result, attempts=attempts)
        attempts.append(
            {
                "tool_name": used_tool,
                "status": result.get("status"),
                "error": str(result.get("error") or "")[:500],
            }
        )
        excluded.add(used_tool)
        next_req = _facade()._req_with_excluded_tools(req, excluded)
        if not _facade()._tool_candidates(next_req):
            return _facade()._attach_tool_fallback_meta(result, attempts=attempts)
        logger_msg = f"para tool runtime failure tool={used_tool}; retry with {','.join(_facade()._tool_candidates(next_req))}"
        try:
            import logging

            logging.getLogger(__name__).warning(logger_msg)
        except RECOVERABLE_ERRORS:
            pass
        result = _facade()._post_para_api_once(next_req)
    return _facade()._attach_tool_fallback_meta(result, attempts=attempts)
