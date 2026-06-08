"""MOD 商店后台 · 生命周期 API（阶段 9）。

补齐三块能力：
- 作者收益结算（settle）：把 ``AuthorEarning`` 从 pending 结算为 settled。
- 灰度发布（gray release）：按比例 + 标签放量某商品某版本，并提供可见性判定。
- 评价（reviews）：用户评分/评论，作者回复，商品聚合评分。

依赖既有 ``AuthorEarning`` 模型（db/billing.py）与本阶段新增的
``GrayRelease`` / ``ModReview`` 模型。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import AuthorEarning, GrayRelease, ModReview, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/store", tags=["store-lifecycle"])


# --------------------------------------------------------------------------
# 作者收益结算
# --------------------------------------------------------------------------
class SettleBody(BaseModel):
    author_id: int = Field(..., description="待结算作者")
    earning_ids: list[int] | None = Field(default=None, description="为空则结算该作者全部 pending")


@router.post("/earnings/settle")
def settle_earnings(
    body: SettleBody,
    db: Session = Depends(get_db),
    current: User = Depends(_get_current_user),
):
    """将作者 pending 收益标记为 settled，返回结算汇总。

    幂等：已 settled 的记录跳过。需要管理员权限。
    """
    if not getattr(current, "is_admin", False):
        raise HTTPException(status_code=403, detail="仅管理员可结算")

    q = db.query(AuthorEarning).filter(
        AuthorEarning.author_id == body.author_id,
        AuthorEarning.status == "pending",
    )
    if body.earning_ids:
        q = q.filter(AuthorEarning.id.in_(body.earning_ids))

    rows = q.all()
    now = datetime.now(timezone.utc)
    total_net = 0.0
    for row in rows:
        row.status = "settled"
        row.settled_at = now
        total_net += float(row.net or 0)
    db.commit()
    return {
        "ok": True,
        "author_id": body.author_id,
        "settled_count": len(rows),
        "settled_net": round(total_net, 2),
    }


@router.get("/earnings/summary")
def earnings_summary(
    author_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(_get_current_user),
):
    """作者收益汇总（pending / settled 各自金额与笔数）。"""
    out: dict[str, dict] = {}
    for status in ("pending", "settled"):
        agg = (
            db.query(func.count(AuthorEarning.id), func.coalesce(func.sum(AuthorEarning.net), 0))
            .filter(AuthorEarning.author_id == author_id, AuthorEarning.status == status)
            .one()
        )
        out[status] = {"count": int(agg[0] or 0), "net": round(float(agg[1] or 0), 2)}
    return {"ok": True, "author_id": author_id, **out}


# --------------------------------------------------------------------------
# 灰度发布
# --------------------------------------------------------------------------
class GrayReleaseBody(BaseModel):
    catalog_id: int
    version: str
    rollout_percent: float = Field(0.0, ge=0.0, le=1.0)
    allow_tags: list[str] = Field(default_factory=list)
    note: str = ""


@router.post("/gray-releases")
def upsert_gray_release(
    body: GrayReleaseBody,
    db: Session = Depends(get_db),
    current: User = Depends(_get_current_user),
):
    """创建或更新某商品某版本的灰度配置（按 catalog_id+version 唯一）。"""
    row = (
        db.query(GrayRelease)
        .filter(GrayRelease.catalog_id == body.catalog_id, GrayRelease.version == body.version)
        .first()
    )
    if row is None:
        row = GrayRelease(
            catalog_id=body.catalog_id,
            version=body.version,
            author_id=getattr(current, "id", None),
        )
        db.add(row)
    row.rollout_percent = body.rollout_percent
    row.allow_tags_json = json.dumps(body.allow_tags, ensure_ascii=False)
    row.note = body.note
    row.status = "active"
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id, "status": row.status}


@router.post("/gray-releases/{release_id}/status")
def set_gray_release_status(
    release_id: int,
    status: str,
    db: Session = Depends(get_db),
    current: User = Depends(_get_current_user),
):
    """变更灰度状态：active / paused / promoted（全量）/ rolled_back（回滚）。"""
    if status not in {"active", "paused", "promoted", "rolled_back"}:
        raise HTTPException(status_code=400, detail="非法状态")
    row = db.query(GrayRelease).filter(GrayRelease.id == release_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="灰度配置不存在")
    row.status = status
    if status == "promoted":
        row.rollout_percent = 1.0
    elif status == "rolled_back":
        row.rollout_percent = 0.0
    db.commit()
    return {"ok": True, "id": release_id, "status": status}


def _in_rollout(catalog_id: int, version: str, user_id: int, percent: float) -> bool:
    """基于 (catalog_id, version, user_id) 稳定哈希分桶判定是否命中放量。"""
    if percent >= 1.0:
        return True
    if percent <= 0.0:
        return False
    digest = hashlib.sha256(f"{catalog_id}:{version}:{user_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 10000
    return bucket < int(percent * 10000)


@router.get("/gray-releases/{catalog_id}/visible")
def gray_release_visible(
    catalog_id: int,
    version: str,
    user_id: int,
    user_tags: str = "",
    db: Session = Depends(get_db),
):
    """判定某用户是否可见某商品的某灰度版本（供客户端/网关调用）。"""
    row = (
        db.query(GrayRelease)
        .filter(GrayRelease.catalog_id == catalog_id, GrayRelease.version == version)
        .first()
    )
    if row is None or row.status in {"rolled_back", "paused"}:
        return {"visible": False, "reason": "no_active_release"}
    try:
        allow_tags = set(json.loads(row.allow_tags_json or "[]"))
    except json.JSONDecodeError:
        allow_tags = set()
    tags = {t.strip() for t in user_tags.split(",") if t.strip()}
    if allow_tags & tags:
        return {"visible": True, "reason": "tag_match"}
    visible = _in_rollout(catalog_id, version, user_id, float(row.rollout_percent or 0))
    return {
        "visible": visible,
        "reason": "rollout_bucket",
        "percent": float(row.rollout_percent or 0),
    }


# --------------------------------------------------------------------------
# 评价
# --------------------------------------------------------------------------
class ReviewBody(BaseModel):
    catalog_id: int
    rating: int = Field(..., ge=1, le=5)
    content: str = ""


@router.post("/reviews")
def submit_review(
    body: ReviewBody,
    db: Session = Depends(get_db),
    current: User = Depends(_get_current_user),
):
    """提交/更新评价（每用户每商品一条，upsert）。"""
    row = (
        db.query(ModReview)
        .filter(ModReview.catalog_id == body.catalog_id, ModReview.user_id == current.id)
        .first()
    )
    if row is None:
        row = ModReview(catalog_id=body.catalog_id, user_id=current.id)
        db.add(row)
    row.rating = body.rating
    row.content = body.content
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


class ReviewReplyBody(BaseModel):
    reply: str = Field(..., min_length=1)


@router.post("/reviews/{review_id}/reply")
def reply_review(
    review_id: int,
    body: ReviewReplyBody,
    db: Session = Depends(get_db),
    current: User = Depends(_get_current_user),
):
    """作者回复评价。"""
    row = db.query(ModReview).filter(ModReview.id == review_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="评价不存在")
    row.author_reply = body.reply
    db.commit()
    return {"ok": True, "id": review_id}


@router.get("/reviews/{catalog_id}")
def list_reviews(catalog_id: int, db: Session = Depends(get_db)):
    """列出某商品评价 + 聚合评分。"""
    rows = (
        db.query(ModReview)
        .filter(ModReview.catalog_id == catalog_id, ModReview.is_hidden == False)  # noqa: E712
        .order_by(ModReview.created_at.desc())
        .all()
    )
    agg = (
        db.query(func.count(ModReview.id), func.coalesce(func.avg(ModReview.rating), 0))
        .filter(ModReview.catalog_id == catalog_id, ModReview.is_hidden == False)  # noqa: E712
        .one()
    )
    return {
        "ok": True,
        "catalog_id": catalog_id,
        "count": int(agg[0] or 0),
        "avg_rating": round(float(agg[1] or 0), 2),
        "reviews": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "rating": r.rating,
                "content": r.content,
                "author_reply": r.author_reply,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
