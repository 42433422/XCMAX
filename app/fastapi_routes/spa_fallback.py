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
    "brand-xc-logo",
    "workflow-employee-docs.json",
)


def register_spa_history_fallback(app: FastAPI) -> None:
    """Vue History fallback：必须最后注册，避免吞掉 API。"""

    @app.get("/{fallback:path}", include_in_schema=False)
    def vue_history_fallback(fallback: str):
        if any(fallback.startswith(p) for p in _EXCLUDED_PREFIXES):
            return JSONResponse({"success": False, "message": f"资源不存在：/{fallback}"}, status_code=404)
        vue_dist_dir = os.path.join(get_base_dir(), "templates", "vue-dist")
        vue_index = os.path.join(vue_dist_dir, "index.html")
        if os.path.exists(vue_index):
            return FileResponse(vue_index, media_type="text/html")
        return JSONResponse({"success": False, "message": f"页面不存在：/{fallback}"}, status_code=404)


__all__ = ["register_spa_history_fallback"]
