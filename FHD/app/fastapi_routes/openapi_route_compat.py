"""尾斜杠兼容路由的 OpenAPI 去重辅助。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.routing import Mount

logger = logging.getLogger(__name__)

_DOC_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class EffectiveRoute:
    """Route view that hides FastAPI's lazy ``_IncludedRouter`` internals."""

    source: Any
    path: str
    methods: Any
    endpoint: Any
    include_in_schema: bool
    name: str = ""
    tags: list[str] | None = None
    summary: str | None = None
    operation_id: str | None = None
    original_route: Any | None = None


def _join_route_path(prefix: str, path: str) -> str:
    if not prefix:
        return path or ""
    if not path or path == "/":
        return prefix or "/"
    return prefix.rstrip("/") + (path if path.startswith("/") else f"/{path}")


def _route_view(route: Any, *, prefix: str = "") -> EffectiveRoute:
    path = _join_route_path(prefix, str(getattr(route, "path", "") or ""))
    return EffectiveRoute(
        source=route,
        path=path,
        methods=getattr(route, "methods", None),
        endpoint=getattr(route, "endpoint", None),
        include_in_schema=bool(getattr(route, "include_in_schema", True)),
        name=str(getattr(route, "name", "") or ""),
        tags=list(getattr(route, "tags", None) or []),
        summary=getattr(route, "summary", None),
        operation_id=getattr(route, "operation_id", None),
        original_route=getattr(route, "original_route", route),
    )


def iter_effective_routes(routes: Any, *, prefix: str = ""):
    """Yield route-like views, expanding FastAPI 0.137 lazy included routers.

    FastAPI 0.137 keeps ``include_router()`` entries as private ``_IncludedRouter``
    objects in ``app.routes``. OpenAPI generation and request dispatch understand
    them, but tests and consistency scripts that inspect ``app.routes`` need a
    version-tolerant flattened view.
    """
    for route in routes or []:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            for context in contexts():
                yield _route_view(context, prefix=prefix)
            continue

        if isinstance(route, Mount):
            mount_prefix = _join_route_path(prefix, str(getattr(route, "path", "") or ""))
            yield from iter_effective_routes(getattr(route, "routes", []), prefix=mount_prefix)
            continue

        yield _route_view(route, prefix=prefix)


def hide_trailing_slash_openapi_duplicates(app: FastAPI) -> int:
    """同一 handler 的 ``/path`` 与 ``/path/`` 并存时，隐藏尾斜杠变体的 schema 条目。

    运行时仍保留尾斜杠路由；仅避免 OpenAPI / 一致性检查重复告警。
    """
    try:
        from fastapi.routing import APIRoute
    except ImportError:  # pragma: no cover
        from starlette.routing import Route as APIRoute

    from app.utils.openapi_path import normalize_path_template

    grouped: dict[tuple[str, str], list[Any]] = {}
    for route in iter_effective_routes(app.routes):
        source_route = route.original_route
        if not isinstance(source_route, APIRoute):
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
                if hasattr(route.source, "include_in_schema"):
                    route.source.include_in_schema = False
                if route.original_route is not None:
                    route.original_route.include_in_schema = False
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
