"""Governed execution of catalog operations (AIOPEN P1).

执行统一走 ``operation_call``：只接受目录中的 operation_id，
危险操作一律拒绝（等待审批桥），写操作需服务端显式开启，
路径/查询/请求体按目录中的 OpenAPI 参数结构组装。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from .catalog_builder import find_operation, get_catalog

WRITE_FLAG = "AIOPEN_ENABLE_WRITES"


def writes_enabled() -> bool:
    return (os.environ.get(WRITE_FLAG) or "").strip().lower() in {"1", "true", "yes", "on"}


def required_scope(app: Any, tool: str, args: dict[str, Any]) -> str:
    """``operation_call`` 按目标 operation 的 scope 鉴权；其余工具返回空串。"""
    if str(tool or "").strip() != "operation_call":
        return ""
    operation_id = str((args or {}).get("operation_id") or "").strip()
    if not operation_id:
        return ""
    entry = find_operation(get_catalog(app), operation_id)
    return str((entry or {}).get("scope") or "")


def _encode(value: Any) -> str:
    return quote(str(value), safe="")


def build_request(entry: dict[str, Any], args: dict[str, Any]) -> dict[str, Any] | str:
    """按目录参数拼装请求；返回错误说明字符串表示参数不合法。"""
    path = str(entry.get("path") or "")
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
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


def operation_call(
    app: Any, args: dict[str, Any], call: Callable[..., dict[str, Any]]
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
    risk = str(entry.get("risk") or "read")
    if risk == "danger":
        return {
            "success": False,
            "code": "APPROVAL_REQUIRED",
            "operation_id": operation_id,
            "risk": risk,
            "message": "危险操作不直接执行：需在 AIOPEN 审批桥上线后经人工审批。",
        }
    if risk == "write" and not writes_enabled():
        return {
            "success": False,
            "code": "WRITE_DISABLED",
            "operation_id": operation_id,
            "risk": risk,
            "message": f"写操作未启用：服务端需设置 {WRITE_FLAG}=1 才允许执行。",
        }
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
    result["risk"] = risk
    return result
