"""Discover actual mounted API contracts without treating discovery as authorization."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import routing
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from starlette.routing import Mount


def mounted_operations(app: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    # FastAPI's lazy included routers carry prefix/dependency overrides in a
    # RouteContext. Use the same iterator as OpenAPI, with older-version fallback.
    contexts = getattr(routing, "iter_route_contexts", iter)
    for route in contexts(getattr(app, "routes", [])):
        original = getattr(route, "original_route", route)
        if isinstance(original, APIRoute):
            yield prefix + route.path, route
        elif isinstance(original, Mount):
            yield from mounted_operations(original, prefix + route.path)


def api_operations(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    from app.application.aiopen.service import is_path_whitelisted

    raw_offset, raw_limit = args.get("offset", 0), args.get("limit", 100)
    if (
        type(raw_offset) is not int
        or type(raw_limit) is not int
        or raw_offset < 0
        or not 1 <= raw_limit <= 200
    ):
        return {
            "success": False,
            "code": "INVALID_PAGE",
            "message": "offset 必须非负，limit 必须为 1–200 的整数",
        }
    query = str(args.get("query") or "").casefold().strip()
    operations = []
    for path, route in mounted_operations(app):
        if not path.startswith("/api/"):
            continue
        description = str(route.summary or route.name or "")
        if query and query not in f"{path} {description} {' '.join(route.tags)}".casefold():
            continue
        for method in sorted(route.methods or []):
            operations.append(
                {
                    "path": path,
                    "method": method,
                    "description": description,
                    "tags": list(route.tags),
                    "enabled": bool(is_path_whitelisted(path)),
                    "authorization": "request_identity_and_endpoint_policy",
                }
            )
    operations.sort(key=lambda item: (item["path"], item["method"]))
    page = operations[raw_offset : raw_offset + raw_limit]
    end = raw_offset + len(page)
    return {
        "success": True,
        "operation_count": len(operations),
        "operations": page,
        "next_offset": end if end < len(operations) else None,
        "instruction": "登记不表示当前账号获准调用。enabled 仅表示 AIOPEN 路由开关；操作仍需原接口身份与权限检查。",
    }


def api_schema(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path") or "").strip()
    method = str(args.get("method") or "GET").upper()
    matches = [
        (mounted, route)
        for mounted, route in mounted_operations(app)
        if mounted == path and method in (route.methods or set()) and mounted.startswith("/api/")
    ]
    if not matches:
        return {
            "success": False,
            "code": "OPERATION_NOT_FOUND",
            "message": "未找到已挂载的 API 动作，请先读取 api_operations",
        }
    if len(matches) != 1:
        return {
            "success": False,
            "code": "AMBIGUOUS_OPERATION",
            "message": "同一动作存在多个路由，需先消除分发冲突",
        }
    mounted, route = matches[0]
    # Build from the actual selected route rather than app.openapi()'s startup
    # cache so Mods mounted after startup are represented immediately.
    schema = get_openapi(title="XCMAX operation", version="1", routes=[route])
    operation = schema.get("paths", {}).get(route.path_format, {}).get(method.lower())
    if not operation:
        return {
            "success": False,
            "code": "SCHEMA_UNAVAILABLE",
            "message": "该动作未提供 OpenAPI 协议",
        }
    return {
        "success": True,
        "path": mounted,
        "method": method,
        "operation": operation,
        "components": schema.get("components", {}),
    }


API_CONTRACT_TOOLS = [
    {
        "name": "api_operations",
        "description": "分页读取当前软件实际挂载的 API 动作，包括动态 Mods；同时标明 AIOPEN 开关状态。",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        },
    },
    {
        "name": "api_schema",
        "description": "读取已挂载 API 的参数、请求体和响应协议。path/method 必须来自 api_operations，不得猜测。",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "method"],
            "properties": {
                "path": {"type": "string"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                },
            },
        },
    },
]
