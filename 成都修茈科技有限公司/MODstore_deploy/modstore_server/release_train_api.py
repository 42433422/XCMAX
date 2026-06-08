"""release_train SSOT 管理 API：快照 + 历史 + 回滚（管理员）。

- ``GET  /api/admin/release-train``           —— 当前四段快照（含 last_bump_day 幂等日）
- ``GET  /api/admin/release-train/history``    —— 历史快照列表（容灾/回滚选择/可视化）
- ``POST /api/admin/release-train/rollback``   —— 回退到上一/指定版本/步数（回修）

回滚是 v10 线内日更四段迭代的纠错动作，不触碰营销锚点（10.0.0），不改 VERSION.md 等。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modstore_server.api.deps import _require_admin
from modstore_server.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/release-train", tags=["admin-ops"])


class ReleaseTrainRollbackDTO(BaseModel):
    to_version: Optional[str] = Field(
        None, description="回退到指定四段版本（如 1.0.0.8）；优先于 steps"
    )
    steps: int = Field(1, ge=1, le=100, description="未指定版本时按步数回退（默认上一步）")
    reason: str = Field("manual", description="审计原因")


@router.get("", summary="release_train 当前快照")
async def get_release_train(_: User = Depends(_require_admin)):
    from modstore_server.release_train import snapshot_public

    return {"ok": True, "data": snapshot_public()}


@router.get("/history", summary="release_train 历史快照列表")
async def get_release_train_history(limit: int = 50, _: User = Depends(_require_admin)):
    from modstore_server.release_train import list_release_train_history

    rows = list_release_train_history(limit=limit)
    return {"ok": True, "data": rows, "total": len(rows)}


@router.post("/rollback", summary="回退 release_train（回修）")
async def post_release_train_rollback(
    body: ReleaseTrainRollbackDTO,
    _: User = Depends(_require_admin),
):
    from modstore_server.release_train import rollback_release_train

    out = rollback_release_train(
        to_version=body.to_version,
        steps=body.steps,
        reason=body.reason or "manual",
    )
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error") or "回滚失败"))
    return {"ok": True, "data": out}
