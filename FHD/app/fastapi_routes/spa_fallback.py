"""Vue SPA History fallback。

Phase 2C 从 :mod:`app.fastapi_routes.archive_gap_batch2` 拆分而出。

关键不变量: ``register_spa_history_fallback`` 必须在所有 API 路由注册之后
调用,以避免 ``GET /{fallback:path}`` 捕获并遮蔽真实 ``/api/...`` 路由。
桌面 fast-start 阶段只调用 ``register_spa_root``，让 Vue 首页可立即加载；
history catch-all 要等 deferred API 全部挂载后才首次注册。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS
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
def _vue_dist_dir() -> str:
    return os.path.join(get_base_dir(), "templates", "vue-dist")


def _workflow_employees_json_candidates() -> list[str]:
    base = get_base_dir()
    return [
        os.path.join(_vue_dist_dir(), "workflow-employees.json"),
        os.path.join(base, "frontend", "public", "workflow-employees.json"),
        os.path.join(base, "frontend", "src", "data", "workflow-employees.json"),
    ]


def _resolved_asset_under(root: str | Path, filename: str) -> Path | None:
    """Resolve a trusted asset name and reject symlink escapes from its root."""

    try:
        safe_root = Path(root).resolve()
        candidate = (safe_root / filename).resolve()
        candidate.relative_to(safe_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _allowlisted_vue_dist_asset(fallback: str) -> tuple[str, str] | None:
    """Map an exact request value to a literal filename and media type."""

    if fallback == "sw.js":
        return "sw.js", "application/javascript"
    if fallback == "workflow-employee-docs.json":
        return "workflow-employee-docs.json", "application/json"
    if fallback == "vite.svg":
        return "vite.svg", "image/svg+xml"
    if fallback == "brand-xc-logo.jpg":
        return "brand-xc-logo.jpg", "image/jpeg"
    if fallback == "brand-xc-logo.png":
        return "brand-xc-logo.png", "image/png"
    return None


def _try_serve_vue_dist_root_file(fallback: str) -> FileResponse | None:
    if fallback == "workflow-employees.json":
        for raw_candidate in _workflow_employees_json_candidates():
            candidate = Path(raw_candidate)
            safe_candidate = _resolved_asset_under(candidate.parent, candidate.name)
            if safe_candidate is not None:
                return FileResponse(safe_candidate, media_type="application/json")
        return None
    allowed = _allowlisted_vue_dist_asset(fallback)
    if allowed is None:
        return None
    filename, media = allowed
    safe_asset = _resolved_asset_under(_vue_dist_dir(), filename)
    if safe_asset is not None:
        return FileResponse(safe_asset, media_type=media)
    return None


def _spa_response(fallback: str) -> FileResponse | JSONResponse:
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
    return JSONResponse({"success": False, "message": f"页面不存在：/{fallback}"}, status_code=404)


def register_spa_root(app: FastAPI) -> None:
    """Register only the exact Vue root for the desktop fast-start window."""

    @app.get("/", include_in_schema=False)
    def vue_spa_root():
        return _spa_response("")


def register_spa_history_fallback(app: FastAPI) -> None:
    """Vue History fallback：必须最后注册，避免吞掉 API。"""

    if any(
        getattr(route, "path", None) == "/{fallback:path}"
        for route in getattr(app.router, "routes", ())
    ):
        ensure_spa_fallback_last(app)
        return

    @app.get("/{fallback:path}", include_in_schema=False)
    def vue_history_fallback(fallback: str):
        return _spa_response(fallback)


__all__ = [
    "register_spa_root",
    "register_spa_history_fallback",
    "ensure_spa_fallback_last",
]


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
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Failed to reorder history fallback routes: %s", exc)
