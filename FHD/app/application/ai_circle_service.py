"""AI circle persistence and employee-runtime event projection."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func

from app.db.base import Base
from app.db.models.ai_circle import AiCircleComment, AiCirclePost, AiCircleReaction
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def ensure_ai_circle_tables() -> None:
    """Idempotently upgrades existing desktop databases without a reset."""
    with get_db() as db:
        Base.metadata.create_all(
            bind=db.get_bind(),
            tables=[
                AiCirclePost.__table__,
                AiCircleReaction.__table__,
                AiCircleComment.__table__,
            ],
            checkfirst=True,
        )


def _iso(value: datetime | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def create_user_post(*, user_id: int, author_name: str, avatar: str | None, body: str) -> int:
    content = str(body or "").strip()
    if not content:
        raise ValueError("动态内容不能为空")
    if len(content) > 2000:
        raise ValueError("动态内容不能超过 2000 字")
    ensure_ai_circle_tables()
    with get_db() as db:
        row = AiCirclePost(
            author_kind="user",
            author_user_id=int(user_id),
            author_name=author_name.strip() or "企业成员",
            author_avatar=avatar,
            body=content,
            source_type="manual",
        )
        db.add(row)
        db.flush()
        return int(row.id)


def record_employee_activity(
    employee_id: str,
    *,
    success: bool,
    blocked: bool = False,
    task: str = "",
    summary: str = "",
) -> None:
    """Persist one post for one real employee execution; never synthesise idle posts."""
    employee = str(employee_id or "").strip()
    if not employee:
        return
    task_text = " ".join(str(task or "").split())[:240]
    summary_text = " ".join(str(summary or "").split())[:360]
    if blocked:
        state = "任务被安全策略拦截"
    elif success:
        state = "任务执行完成"
    else:
        state = "任务执行失败"
    details = []
    if task_text:
        details.append(f"任务：{task_text}")
    if summary_text:
        details.append(f"结果：{summary_text}")
    body = state if not details else f"{state}\n" + "\n".join(details)
    try:
        ensure_ai_circle_tables()
        with get_db() as db:
            db.add(
                AiCirclePost(
                    author_kind="employee",
                    employee_id=employee,
                    author_name=employee,
                    body=body,
                    source_type="employee_execution",
                    source_ref=f"employee-run:{uuid.uuid4().hex}",
                )
            )
    except RECOVERABLE_ERRORS:
        logger.warning("failed to persist AI circle employee event", exc_info=True)


def upsert_employee_post(
    *,
    employee_id: str,
    author_name: str,
    body: str,
    source_ref: str,
    source_type: str = "loop_report",
    created_at: datetime | None = None,
) -> int | None:
    """幂等投影一条员工汇报动态（按 ``source_ref`` 去重）。已存在返回 ``None``，新建返回 id。

    供 FHD 从 MODstore 汇报流拉取后投影使用：``source_ref`` 用 MODstore 消息的稳定标识，
    ``unique`` 约束 + 先查保证同一条汇报只落一条动态。
    """
    employee = str(employee_id or "").strip()
    content = str(body or "").strip()
    ref = str(source_ref or "").strip()[:160]
    if not employee or not content or not ref:
        return None
    ensure_ai_circle_tables()
    with get_db() as db:
        if db.query(AiCirclePost.id).filter(AiCirclePost.source_ref == ref).first() is not None:
            return None
        row = AiCirclePost(
            author_kind="employee",
            employee_id=employee,
            author_name=(author_name or employee).strip()[:128] or employee,
            body=content[:2000],
            source_type=str(source_type or "loop_report")[:48],
            source_ref=ref,
        )
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        db.flush()
        return int(row.id)


def list_posts(*, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    ensure_ai_circle_tables()
    safe_limit = max(1, min(int(limit), 100))
    with get_db() as db:
        posts = db.query(AiCirclePost).order_by(AiCirclePost.id.desc()).limit(safe_limit).all()
        if not posts:
            return []
        post_ids = [int(post.id) for post in posts]
        like_rows = (
            db.query(AiCircleReaction.post_id, func.count(AiCircleReaction.id))
            .filter(AiCircleReaction.post_id.in_(post_ids), AiCircleReaction.kind == "like")
            .group_by(AiCircleReaction.post_id)
            .all()
        )
        like_counts = {int(post_id): int(count) for post_id, count in like_rows}
        liked_ids = {
            int(row.post_id)
            for row in db.query(AiCircleReaction)
            .filter(
                AiCircleReaction.post_id.in_(post_ids),
                AiCircleReaction.user_id == int(user_id),
                AiCircleReaction.kind == "like",
            )
            .all()
        }
        comments = (
            db.query(AiCircleComment)
            .filter(AiCircleComment.post_id.in_(post_ids))
            .order_by(AiCircleComment.id.asc())
            .all()
        )
        comments_by_post: dict[int, list[dict[str, Any]]] = {post_id: [] for post_id in post_ids}
        for comment in comments:
            comments_by_post[int(comment.post_id)].append(
                {
                    "id": int(comment.id),
                    "author_name": comment.author_name,
                    "body": comment.body,
                    "created_at": _iso(comment.created_at),
                }
            )
        return [
            {
                "id": int(post.id),
                "author_kind": post.author_kind,
                "author_user_id": post.author_user_id,
                "employee_id": post.employee_id,
                "author_name": post.author_name,
                "author_avatar": post.author_avatar,
                "body": post.body,
                "source_type": post.source_type,
                "created_at": _iso(post.created_at),
                "like_count": like_counts.get(int(post.id), 0),
                "liked_by_me": int(post.id) in liked_ids,
                "comments": comments_by_post.get(int(post.id), [])[-20:],
            }
            for post in posts
        ]


def toggle_like(*, post_id: int, user_id: int) -> bool:
    ensure_ai_circle_tables()
    with get_db() as db:
        if db.get(AiCirclePost, int(post_id)) is None:
            raise LookupError("动态不存在")
        row = (
            db.query(AiCircleReaction)
            .filter_by(post_id=int(post_id), user_id=int(user_id), kind="like")
            .first()
        )
        if row is not None:
            db.delete(row)
            return False
        db.add(AiCircleReaction(post_id=int(post_id), user_id=int(user_id), kind="like"))
        return True


def add_comment(*, post_id: int, user_id: int, author_name: str, body: str) -> int:
    content = str(body or "").strip()
    if not content:
        raise ValueError("评论内容不能为空")
    if len(content) > 500:
        raise ValueError("评论不能超过 500 字")
    ensure_ai_circle_tables()
    with get_db() as db:
        if db.get(AiCirclePost, int(post_id)) is None:
            raise LookupError("动态不存在")
        row = AiCircleComment(
            post_id=int(post_id),
            user_id=int(user_id),
            author_name=author_name.strip() or "企业成员",
            body=content,
        )
        db.add(row)
        db.flush()
        return int(row.id)
