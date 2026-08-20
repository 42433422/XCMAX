"""公开只读行动看板 API（无鉴权、无写操作）。"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/action-board", tags=["public"])


@router.get("", summary="官网公开行动看板（脱敏只读）")
async def get_public_action_board(
    day: Optional[str] = Query(None, description="可选日历日 YYYY-MM-DD"),
):
    from modstore_server.public_action_board import build_public_action_board

    try:
        data = build_public_action_board(day=day)
        return {"ok": True, "data": data}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("public action board failed")
        return {"ok": False, "error": str(exc), "data": None}
