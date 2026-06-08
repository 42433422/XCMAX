"""尾斜杠兼容路由的 OpenAPI 去重辅助。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_DOC_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def hide_trailing_slash_openapi_duplicates(app: FastAPI) -> int:
    """同一 handler 的 ``/path`` 与 ``/path/`` 并存时，隐藏尾斜杠变体的 schema 条目。

    运行时仍保留尾斜杠路由；仅避免 OpenAPI / 一致性检查重复告警。
    """
    try:
        from fastapi.routing import APIRoute
    except ImportError:  # pragma: no cover
        from starlette.routing import Route as APIRoute  # type: ignore[misc, assignment]

    from app.utils.openapi_path import normalize_path_template

    grouped: dict[tuple[str, str], list[Any]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        norm = normalize_path_template(route.path)
        for method in route.methods or []:
            m = str(method).upper()
            if m not in _DOC_METHODS:
                continue
            grouped.setdefault((m, norm), []).append(route)

    hidden = 0
    for (_method, _norm), routes in grouped.items():
        if len(routes) <= 1:
            continue
        qualnames = {getattr(r.endpoint, "__qualname__", "") for r in routes}
        if len(qualnames) != 1:
            continue
        slash_routes = [r for r in routes if str(r.path).endswith("/") and str(r.path) != "/"]
        for route in slash_routes:
            if getattr(route, "include_in_schema", True):
                route.include_in_schema = False
                hidden += 1

    if hidden:
        app.openapi_schema = None
        logger.debug("Hid %s trailing-slash route(s) from OpenAPI schema", hidden)
    return hidden


def include_router_with_slash_compat(
    app: FastAPI,
    router: Any,
    *,
    hide_slash_in_schema: bool = True,
    **kwargs: Any,
) -> None:
    """``include_router`` 并在挂载后自动隐藏尾斜杠重复项的 schema。"""
    app.include_router(router, **kwargs)
    if hide_slash_in_schema:
        hide_trailing_slash_openapi_duplicates(app)
