"""HTTP 层共用的 wechat-decrypt 自动配置响应。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def wechat_decrypt_auto_configure_response(body: dict[str, Any] | None = None) -> JSONResponse:
    data = body or {}
    force_key_scan = bool(data.get("force_key_scan"))
    try:
        from app.services.wechat_decrypt_autoconfig import auto_configure_wechat_decrypt

        result = auto_configure_wechat_decrypt(force_key_scan=force_key_scan)
        code = 200 if result.get("success") else 503
        return JSONResponse(result, status_code=code)
    except Exception as exc:
        logger.exception("wechat_decrypt_auto_configure: %s", exc)
        return JSONResponse(
            {"success": False, "message": f"自动配置失败：{exc}"},
            status_code=500,
        )
