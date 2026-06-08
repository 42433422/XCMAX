"""日更行动条目 API（Agentic Business OS）。

- ``GET  /api/admin/action-items``           —— 列表（kind=patch|update, day 可选）
- ``GET  /api/admin/action-items/stats``     —— 完成率/分布指标
- ``POST /api/admin/action-items/{id}/status`` —— 状态流转（open→dispatched→in_progress→merged→closed）

供「断点清单」（kind=patch）与「实现目标/路线图」（kind=update）页面数据驱动渲染。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.api.deps import _require_admin
from modstore_server.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/action-items", tags=["admin-ops"])


class StatusDTO(BaseModel):
    status: str = Field(..., description="open|dispatched|in_progress|merged|closed")


@router.get("", summary="日更行动条目列表")
async def get_action_items(
    kind: Optional[str] = Query(None, description="patch|update"),
    day: Optional[str] = Query(None),
    latest: bool = Query(True, description="未指定 day 时取最新一天"),
    _: User = Depends(_require_admin),
):
    from modstore_server.digest_action_items import latest_day, list_action_items

    use_day = day
    if not use_day and latest:
        use_day = latest_day(kind=kind) or None
    items = list_action_items(kind=kind, day=use_day, limit=1000)
    # 按 产线 + 优先级 分组，便于「断点清单」规范格式渲染
    grouped: dict = {}
    for it in items:
        line = it.get("line") or "P-S"
        grouped.setdefault(line, []).append(it)
    return {
        "ok": True,
        "day": use_day,
        "kind": kind,
        "total": len(items),
        "items": items,
        "grouped": grouped,
    }


@router.get("/stats", summary="日更行动条目指标")
async def get_action_items_stats(
    kind: Optional[str] = Query(None),
    day: Optional[str] = Query(None),
    _: User = Depends(_require_admin),
):
    from modstore_server.digest_action_items import latest_day, stats

    use_day = day or (latest_day(kind=kind) or None)
    return {"ok": True, "day": use_day, "data": stats(kind=kind, day=use_day)}


@router.post("/{item_id}/status", summary="行动条目状态流转")
async def post_action_item_status(item_id: int, body: StatusDTO, _: User = Depends(_require_admin)):
    from modstore_server.digest_action_items import set_status

    out = set_status(item_id, body.status)
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error") or "状态更新失败"))
    return {"ok": True, "data": out}
