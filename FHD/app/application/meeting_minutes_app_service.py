"""会议纪要应用服务：编排「持久化 + 三级派生」。

DB 访问全在本层（函数内延迟导入 app.db.*，避免与 LLM 层循环导入）；
派生逻辑委托给纯内核 ``app.services.meeting_minutes.pipeline``。
持久化走 ``with get_db() as db:``，让 TenantScopedMixin 的 before_flush 自动打标 tenant_id。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.meeting_minutes.pipeline import compute_source_hash, generate_all_levels

logger = logging.getLogger(__name__)


async def create_and_generate(
    raw_transcript: str,
    *,
    title: Optional[str] = None,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """建档 → 一次性派生三级 → 回写。返回完整记录 dict（含 id/status/三级）。"""
    from app.db.models.meeting_minutes import MeetingMinute
    from app.db.session import get_db

    raw = (raw_transcript or "").strip()
    source_hash = compute_source_hash(raw)

    # 阶段一：建档 status=generating（先落原文，生成崩溃也不丢素材）
    with get_db() as db:
        row = MeetingMinute(
            title=(title or None),
            user_id=user_id,
            raw_transcript=raw,
            source_hash=source_hash,
            status="generating",
        )
        db.add(row)
        db.flush()
        minute_id = row.id

    # 阶段二：派生（async，DB 之外）
    result = await generate_all_levels(raw)

    # 阶段三：回写
    with get_db() as db:
        row = db.get(MeetingMinute, minute_id)
        if row is None:  # 极端：被并发删除
            return {"id": minute_id, **result, "source_hash": source_hash}
        row.status = result["status"]
        row.level1_script = result["level1_script"]
        row.level2_architecture = result["level2_architecture"]
        row.level3_plain = result["level3_plain"]
        row.error_message = result["error_message"]
        db.flush()
        return row.to_dict()


def get_minute(minute_id: int, *, user_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    """按 id 取一条（租户读过滤自动生效）。可选按 user_id 加锁归属。"""
    from app.db.models.meeting_minutes import MeetingMinute
    from app.db.session import get_db

    with get_db() as db:
        row = db.get(MeetingMinute, minute_id)
        if row is None:
            return None
        if user_id is not None and row.user_id is not None and row.user_id != user_id:
            return None
        return row.to_dict()


def list_minutes(
    *, user_id: Optional[int] = None, page: int = 1, per_page: int = 20
) -> dict[str, Any]:
    """分页列出会议纪要（租户读过滤自动生效）。摘要不含三级正文，减小体积。"""
    from sqlalchemy import select

    from app.db.models.meeting_minutes import MeetingMinute
    from app.db.session import get_db

    page = max(1, int(page or 1))
    per_page = min(100, max(1, int(per_page or 20)))

    with get_db() as db:
        stmt = select(MeetingMinute)
        if user_id is not None:
            stmt = stmt.where(MeetingMinute.user_id == user_id)
        stmt = stmt.order_by(MeetingMinute.id.desc())
        rows = list(db.execute(stmt.limit(per_page).offset((page - 1) * per_page)).scalars())
        items = [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "source_hash": r.source_hash,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"items": items, "page": page, "per_page": per_page}
