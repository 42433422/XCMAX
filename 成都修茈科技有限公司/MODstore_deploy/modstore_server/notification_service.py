"""站内通知：支付成功、员工执行完成等。"""

from __future__ import annotations

import json
import logging
import os
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server.models import Notification, User, get_session_factory

logger = logging.getLogger(__name__)


def _mirror_notification_email(user_id: int, title: str, content: str) -> None:
    """可选：将站内通知抄送用户邮箱（``MODSTORE_MIRROR_NOTIFICATIONS_EMAIL=1``）。"""
    if (os.environ.get("MODSTORE_MIRROR_NOTIFICATIONS_EMAIL") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    sf = get_session_factory()
    with sf() as db:
        u = db.query(User).filter(User.id == user_id).first()
        addr = (getattr(u, "email", None) or "").strip() if u else ""
    if not addr or "@" not in addr:
        return
    try:
        from modstore_server.email_service import send_simple_html_email

        html = f"<html><body><h2>{title}</h2><p>{content}</p></body></html>"
        send_simple_html_email(addr, f"[MODstore] {title}", html)
    except Exception as e:
        logger.debug("notification email mirror skipped: %s", e)


class NotificationType(str, Enum):
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    EMPLOYEE_EXECUTION_DONE = "employee_execution_done"
    QUOTA_WARNING = "quota_warning"
    SYSTEM = "system"


def create_notification(
    user_id: int,
    notification_type: NotificationType,
    title: str,
    content: str,
    data: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
) -> Notification:
    should_close = False
    if db is None:
        sf = get_session_factory()
        db = sf()
        should_close = True
    try:
        notif = Notification(
            user_id=user_id,
            kind=notification_type.value,
            title=title,
            content=content,
            data_json=json.dumps(data or {}, ensure_ascii=False),
            is_read=False,
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        try:
            from modstore_server.realtime_ws import schedule_push_to_user

            schedule_push_to_user(
                user_id,
                {
                    "type": "notification",
                    "id": notif.id,
                    "kind": notif.kind,
                    "title": notif.title,
                },
            )
        except Exception:
            pass
        try:
            _mirror_notification_email(notif.user_id, notif.title, notif.content)
        except Exception:
            pass
        return notif
    finally:
        if should_close:
            db.close()


def notify_payment_success(user_id: int, order_no: str, amount: float, item_name: str) -> None:
    if not user_id:
        return
    try:
        create_notification(
            user_id=user_id,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="支付成功",
            content=f"您购买的「{item_name}」支付成功，金额 ¥{amount:.2f}",
            data={"order_no": order_no, "amount": amount, "item_name": item_name},
        )
    except Exception as e:
        logger.warning("notify_payment_success failed: %s", e)


def notify_employee_execution_done(user_id: int, employee_id: str, task: str, status: str) -> None:
    if not user_id:
        return
    try:
        ok = status == "success"
        create_notification(
            user_id=user_id,
            notification_type=NotificationType.EMPLOYEE_EXECUTION_DONE,
            title="员工执行完成",
            content=f"员工 {employee_id} 的任务「{task}」执行{'成功' if ok else '失败'}",
            data={"employee_id": employee_id, "task": task, "status": status},
        )
    except Exception as e:
        logger.warning("notify_employee_execution_done failed: %s", e)


def notify_quota_warning(user_id: int, quota_type: str, remaining: int, total: int) -> None:
    if not user_id or total <= 0:
        return
    usage_pct = (1 - remaining / total) * 100
    if usage_pct < 80:
        return
    try:
        create_notification(
            user_id=user_id,
            notification_type=NotificationType.QUOTA_WARNING,
            title="配额预警",
            content=f"您的 {quota_type} 配额已使用 {usage_pct:.0f}%，剩余 {remaining}",
            data={"quota_type": quota_type, "remaining": remaining, "total": total},
        )
    except Exception as e:
        logger.warning("notify_quota_warning failed: %s", e)
