"""桌面进程拒绝管理端 API 路径前缀。"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class DesktopAdminForbiddenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.application.desktop_admin_gate import (
            forbidden_payload,
            is_desktop_admin_api_path,
            is_desktop_runtime,
        )

        if is_desktop_runtime() and is_desktop_admin_api_path(request.url.path):
            return JSONResponse(forbidden_payload(), status_code=403)
        return await call_next(request)
