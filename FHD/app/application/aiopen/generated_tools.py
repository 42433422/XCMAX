"""Governed execution of catalog operations (AIOPEN P1).

执行统一按目录风险等级放行：只读直连、写操作需服务端开关、
危险操作经既有审批中心审批并凭 approval_id 执行一次。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from app.infrastructure.aiopen.principal_context import current_screen_principal

from . import approval_bridge
from .catalog_builder import find_operation, get_catalog

WRITE_FLAG = "AIOPEN_ENABLE_WRITES"
_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def writes_enabled() -> bool:
    return (os.environ.get(WRITE_FLAG) or "").strip().lower() in {"1", "true", "yes", "on"}


def required_scope(app: Any, tool: str, args: dict[str, Any]) -> str:
    """``operation_call`` 按目标 operation 的 scope 鉴权；其余工具返回空串。"""
    tool = str(tool or "").strip()
    if tool == "operation_call":
        operation_id = str((args or {}).get("operation_id") or "").strip()
    elif tool == "api_call":
        entry = find_operation_by_request(
            app,
            str((args or {}).get("method") or "GET"),
            str((args or {}).get("path") or ""),
        )
        return str((entry or {}).get("scope") or "")
    else:
        return ""
    if not operation_id:
        return ""
    entry = find_operation(get_catalog(app), operation_id)
    return str((entry or {}).get("scope") or "")


def find_operation_by_request(app: Any, method: str, path: str) -> dict[str, Any] | None:
    """把 ``api_call`` 的 method+path 映射回目录条目，用于套用同一套闸门。"""
    verb = str(method or "GET").upper()
    if verb not in _HTTP_METHODS:
        return None
    raw = str(path or "").split("?", 1)[0].rstrip("/")
    target = [part for part in raw.split("/") if part]
    for entry in get_catalog(app).get("operations") or []:
        if not isinstance(entry, dict) or entry.get("method") != verb:
            continue
        template = [part for part in str(entry.get("path") or "").split("/") if part]
        if len(template) != len(target):
            continue
        if all(
            piece.startswith("{") or piece == actual
            for piece, actual in zip(template, target, strict=True)
        ):
            return entry
    return None


def _encode(value: Any) -> str:
    return quote(str(value), safe="")


def build_request(entry: dict[str, Any], args: dict[str, Any]) -> dict[str, Any] | str:
    """按目录参数拼装请求；返回错误说明字符串表示参数不合法。"""
    path = str(entry.get("path") or "")
    raw_params = args.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    query: list[str] = []
    for spec in entry.get("parameters") or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "")
        location = str(spec.get("in") or "")
        if not name or location not in {"path", "query"}:
            continue
        value = params.get(name)
        if location == "path":
            if value is None or value == "":
                return f"缺少路径参数：{name}"
            path = path.replace("{" + name + "}", _encode(value))
            continue
        if value is None or value == "" or value == []:
            if spec.get("required"):
                return f"缺少必填查询参数：{name}"
            continue
        if isinstance(value, (list, tuple)):
            query.extend(f"{quote(name, safe='')}={_encode(item)}" for item in value)
        else:
            query.append(f"{quote(name, safe='')}={_encode(value)}")
    if "{" in path:
        missing = [part.strip("{}") for part in path.split("/") if part.startswith("{")]
        return f"缺少路径参数：{', '.join(missing)}"
    body_spec = entry.get("request_body") or {}
    body = args.get("body") if isinstance(args.get("body"), dict) else None
    if body_spec.get("required") and not body:
        return "缺少请求体 body"
    request_path = path + ("?" + "&".join(query) if query else "")
    return {
        "path": request_path,
        "method": str(entry.get("method") or "GET").upper(),
        "body": body or {},
    }


def _approval_outcome(
    entry: dict[str, Any],
    args: dict[str, Any],
    bridge: Any,
) -> dict[str, Any] | None:
    """危险操作：无审批单则发起，有审批单则校验并消费；返回拦截结果或 None。"""
    principal = current_screen_principal()
    approval_id = args.get("approval_id")
    if approval_id:
        try:
            parsed = int(approval_id)
        except (TypeError, ValueError):
            return {
                "success": False,
                "code": "APPROVAL_INVALID",
                "message": "approval_id 必须是审批单编号。",
            }
        outcome = bridge.consume(parsed, entry, args, principal)
        return (
            None
            if outcome.get("status") == "approved"
            else {
                "success": False,
                "operation_id": entry.get("operation_id"),
                **outcome,
            }
        )
    outcome = bridge.submit(entry, args, principal)
    # 显式开启“自动批准危险操作”时，仍先落审批记录，再由系统批准并立即消费，
    # 保留申请人、批准人、参数摘要与消费时间，避免无痕执行。
    if outcome.get("status") == "pending" and writes_enabled() and _auto_approve_enabled(bridge):
        approval_id = int(outcome.get("approval_id") or 0)
        if approval_id and bridge.auto_approve(approval_id, principal):
            consumed = bridge.consume(approval_id, entry, args, principal)
            if consumed.get("status") == "approved":
                return None
            return {
                "success": False,
                "operation_id": entry.get("operation_id"),
                **consumed,
            }
    return {
        "success": False,
        "operation_id": entry.get("operation_id"),
        **outcome,
    }


def _auto_approve_enabled(bridge: Any) -> bool:
    checker = getattr(bridge, "auto_approve_enabled", None)
    return bool(checker()) if callable(checker) else False


def _blocked_by_risk(
    entry: dict[str, Any], args: dict[str, Any], bridge: Any
) -> dict[str, Any] | None:
    risk = str(entry.get("risk") or "read")
    if risk == "danger":
        return _approval_outcome(entry, args, bridge)
    if risk == "write" and not writes_enabled():
        return {
            "success": False,
            "code": "WRITE_DISABLED",
            "operation_id": entry.get("operation_id"),
            "risk": risk,
            "message": f"写操作未启用：服务端需设置 {WRITE_FLAG}=1 才允许执行。",
        }
    return None


def operation_call(
    app: Any,
    args: dict[str, Any],
    call: Callable[..., dict[str, Any]],
    bridge: Any | None = None,
) -> dict[str, Any]:
    operation_id = str((args or {}).get("operation_id") or "").strip()
    if not operation_id:
        return {
            "success": False,
            "code": "INVALID_ARGUMENT",
            "message": "operation_id 不能为空",
        }
    entry = find_operation(get_catalog(app), operation_id)
    if entry is None:
        return {
            "success": False,
            "code": "OPERATION_NOT_FOUND",
            "message": f"目录中不存在 operation：{operation_id}",
        }
    blocked = _blocked_by_risk(entry, args, bridge or approval_bridge)
    if blocked is not None:
        return blocked
    request = build_request(entry, args or {})
    if isinstance(request, str):
        return {
            "success": False,
            "code": "INVALID_ARGUMENT",
            "operation_id": operation_id,
            "message": request,
        }
    result = call(
        app,
        {"path": request["path"], "method": request["method"], "body": request["body"]},
    )
    result["operation_id"] = operation_id
    result["risk"] = entry.get("risk")
    return result


def guarded_api_call(
    app: Any,
    args: dict[str, Any],
    call: Callable[..., dict[str, Any]],
    bridge: Any | None = None,
) -> dict[str, Any]:
    """``api_call`` 逃生舱：命中目录时套用同样的读写/危险闸门。"""
    method = str((args or {}).get("method") or "GET").upper()
    entry = find_operation_by_request(app, method, str((args or {}).get("path") or ""))
    if entry is None:
        return call(app, args)
    normalized: dict[str, Any] = {
        "params": {},
        "body": args.get("body") if isinstance(args.get("body"), dict) else {},
        "approval_id": args.get("approval_id"),
    }
    blocked = _blocked_by_risk(entry, normalized, bridge or approval_bridge)
    if blocked is not None:
        return blocked
    result = call(app, args)
    result["operation_id"] = entry.get("operation_id")
    result["risk"] = entry.get("risk")
    return result
