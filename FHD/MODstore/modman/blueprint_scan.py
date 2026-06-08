"""
从 Mod 后端源文件中静态提取 FastAPI ``APIRouter`` 的路由（``@router.get`` / ``post`` / ``api_route`` 等）。

不再解析 Flask ``@*.route``；历史函数名 ``scan_flask_route_decorators`` 仍作为别名指向本实现，避免旧导入报错。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_ROUTER_HTTP_METHOD_ATTRS = frozenset(
    {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
)


def _path_from_expr(expr: ast.expr) -> str:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        parts: list[str] = []
        for v in expr.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                parts.append("{…}")
        return "".join(parts) if parts else ""
    return ""


def _methods_from_sequence(node: ast.expr | None) -> list[str] | None:
    if node is None:
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        m: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                m.append(elt.value.upper())
        return m if m else None
    return None


def _fastapi_route_from_decorator(dec: ast.expr) -> dict[str, Any] | None:
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr

    methods: list[str]
    if attr == "api_route":
        methods = ["GET"]
        for kw in dec.keywords or []:
            if kw.arg == "methods" and kw.value is not None:
                parsed = _methods_from_sequence(kw.value)
                if parsed:
                    methods = parsed
    elif attr in _ROUTER_HTTP_METHOD_ATTRS:
        methods = [attr.upper()]
    else:
        return None

    path = ""
    if dec.args:
        path = _path_from_expr(dec.args[0])
    if not path:
        for kw in dec.keywords or []:
            if kw.arg == "path" and kw.value is not None:
                path = _path_from_expr(kw.value)
                break
    return {"path": path or "/", "methods": methods}


def scan_fastapi_router_routes(py_file: Path) -> list[dict[str, Any]]:
    text = py_file.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(py_file))
    routes: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            info = _fastapi_route_from_decorator(dec)
            if info:
                routes.append(
                    {
                        "function": node.name,
                        "path": info["path"],
                        "methods": info["methods"],
                        "framework": "fastapi",
                    }
                )
    return routes


def scan_flask_route_decorators(py_file: Path) -> list[dict[str, Any]]:
    """兼容旧名：等价于 :func:`scan_fastapi_router_routes`。"""
    return scan_fastapi_router_routes(py_file)
