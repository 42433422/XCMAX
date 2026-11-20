"""兼容旧版 ``POST /api/debug/client-log``（静态脚本 / 专业浮窗等仍主动上报）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.infrastructure.auth.dependencies import get_logged_in_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debug", tags=["debug"])
_MAX_CLIENT_LOG_BYTES = 16 * 1024


@router.post("/client-log")
async def post_client_debug_log(
    request: Request, _user=Depends(get_logged_in_user)
) -> dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > _MAX_CLIENT_LOG_BYTES:
            raise HTTPException(status_code=413, detail="客户端日志请求体过大")
        raw.extend(chunk)
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="无效的客户端日志 JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="客户端日志必须是 JSON 对象")
    try:
        from app.utils.logging.logging_utils import ingest_client_debug_json

        return ingest_client_debug_json(body)
    except RECOVERABLE_ERRORS:
        logger.exception("[debug] client-log 处理失败")
        return {"success": False, "message": "客户端日志处理失败"}
