"""公开只读公司大厅 API（无鉴权、无写操作）。"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/company-hall", tags=["public"])


@router.get("", summary="官网世界意志公司大厅（脱敏只读）")
async def get_public_company_hall(
    day: Optional[str] = Query(None, description="可选日历日 YYYY-MM-DD"),
):
    from modstore_server.public_company_hall import build_public_company_hall

    try:
        data = build_public_company_hall(day=day)
        return {"ok": True, "data": data}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("public company hall failed")
        return {"ok": False, "error": str(exc), "data": None}
