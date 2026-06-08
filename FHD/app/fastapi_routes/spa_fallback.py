"""Vue SPA History fallback。

Phase 2C 从 :mod:`app.fastapi_routes.archive_gap_batch2` 拆分而出。

关键不变量: ``register_spa_history_fallback`` 必须在所有 API 路由注册之后
调用,以避免 ``GET /{fallback:path}`` 捕获并遮蔽真实 ``/api/...`` 路由。
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app.utils.path_utils import get_base_dir

logger = logging.getLogger(__name__)

_EXCLUDED_PREFIXES = (
    "api/",
    "assets/",
    "static/",
    "outputs/",
    "uploads/",
    "fonts/",
    "images/",
    "js/",
    "css/",
    "favicon",
    "docs",
    "openapi.json",
    "redoc",
    # Vue public/ 根路径资源（由 StaticFiles 或显式路由提供；勿被 SPA 兜底成 index.html）
    "font-awesome/",
    "startup/",
    "yuangong/",
    "workflow/",
    "data-sources/",
    "xcmax-dashboard/",
    "brand-xc-logo",
)


# vue-dist 根目录单文件（非 full 版可能未挂载 legacy_gaps，须在此兜底，勿返回 index.html）
_VUE_DIST_ROOT_FILES: dict[str, str] = {
    "sw.js": "application/javascript",
    "workflow-employee-docs.json": "application/json",
    "workflow-employees.json": "application/json",
    "vite.svg": "image/svg+xml",
    "brand-xc-logo.jpg": "image/jpeg",
    "brand-xc-logo.png": "image/png",
}


def _vue_dist_dir() -> str:
    return os.path.join(get_base_dir(), "templates", "vue-dist")


def _workflow_employees_json_candidates() -> list[str]:
    base = get_base_dir()
    return [
        os.path.join(_vue_dist_dir(), "workflow-employees.json"),
        os.path.join(base, "frontend", "public", "workflow-employees.json"),
        os.path.join(base, "frontend", "src", "data", "workflow-employees.json"),
    ]


def _try_serve_vue_dist_root_file(fallback: str) -> FileResponse | None:
    media = _VUE_DIST_ROOT_FILES.get(fallback)
    if not media:
        return None
    if fallback == "workflow-employees.json":
        for p in _workflow_employees_json_candidates():
            if os.path.isfile(p):
                return FileResponse(p, media_type=media)
        return None
    p = os.path.join(_vue_dist_dir(), fallback)
    if os.path.isfile(p):
        return FileResponse(p, media_type=media)
    return None


def register_spa_history_fallback(app: FastAPI) -> None:
    """Vue History fallback：必须最后注册，避免吞掉 API。"""

    @app.get("/{fallback:path}", include_in_schema=False)
    def vue_history_fallback(fallback: str):
        root_file = _try_serve_vue_dist_root_file(fallback)
        if root_file is not None:
            return root_file
        if any(fallback.startswith(p) for p in _EXCLUDED_PREFIXES):
            return JSONResponse(
                {"success": False, "message": f"资源不存在：/{fallback}"}, status_code=404
            )
        vue_index = os.path.join(_vue_dist_dir(), "index.html")
        if os.path.exists(vue_index):
            return FileResponse(vue_index, media_type="text/html")
        return JSONResponse(
            {"success": False, "message": f"页面不存在：/{fallback}"}, status_code=404
        )


__all__ = ["register_spa_history_fallback", "ensure_spa_fallback_last"]


def ensure_spa_fallback_last(app: FastAPI) -> None:
    """After Mod routes are appended post-fallback registration, move catch-all to the end."""
    try:
        routes = getattr(getattr(app, "router", None), "routes", None)
        if not isinstance(routes, list) or not routes:
            return
        fallback_path = "/{fallback:path}"
        fallback_routes = [r for r in routes if getattr(r, "path", None) == fallback_path]
        if not fallback_routes:
            return
        for route in fallback_routes:
            try:
                routes.remove(route)
            except ValueError:
                continue
            routes.append(route)
        logger.info(
            "Reordered %d Vue history fallback route(s) to end of app.router.routes",
            len(fallback_routes),
        )
    except Exception as exc:
        logger.warning("Failed to reorder history fallback routes: %s", exc)
