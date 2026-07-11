"""站内通知：支付成功、员工执行完成等。"""

from __future__ import annotations

import json
import logging
import os
from enum import Enum
from ipaddress import ip_address
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from modstore_server.models import Notification, User, get_session_factory

logger = logging.getLogger(__name__)


def _mirror_notification_email(user_id: int, title: str, content: str) -> None:
    """可选：将站内通知抄送用户邮箱（``MODSTORE_MIRROR_NOTIFICATIONS_EMAIL=1``）。"""
    if (
        os.environ.get("MODSTORE_MIRROR_NOTIFICATIONS_EMAIL") or ""
    ).strip().lower() not in (
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
    HUMAN_QUESTION_ASKED = "human_question_asked"  # Phase-D：员工向老板提问


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


def notify_payment_success(
    user_id: int, order_no: str, amount: float, item_name: str
) -> None:
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


def notify_employee_execution_done(
    user_id: int, employee_id: str, task: str, status: str
) -> None:
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


def _fhd_internal_candidates() -> list[str]:
    """Return live FHD candidates in priority order.

    Desktop currently defaults to port 17500.  Older deployments used 5100,
    5000 or 8765, so employee-to-boss delivery probes them only when no
    explicit URL succeeds.  This keeps a missing optional env var from making
    every proactive employee message disappear silently.
    """

    raw = [
        os.environ.get("XCAGI_FHD_INTERNAL_URL"),
        os.environ.get("FHD_INTERNAL_BASE_URL"),
        os.environ.get("XCAGI_API_BASE_URL"),
        "http://127.0.0.1:17500",
        "http://127.0.0.1:5100",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:8765",
    ]
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip().rstrip("/")
        if value and _private_internal_url(value) and value not in out:
            out.append(value)
    return out


def _private_internal_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        hostname = str(parsed.hostname or "").strip().lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if hostname == "localhost":
            return True
        address = ip_address(hostname)
        return bool(address.is_loopback or address.is_private)
    except ValueError:
        return False


def _fhd_internal_api_key() -> str:
    return (
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or ""
    ).strip()


def employee_message_to_boss(
    user_id: int,
    employee_id: str,
    text: str,
    *,
    display_name: str = "",
    notification: dict | None = None,
) -> bool:
    """员工主动给老板发一条 IM 消息（通用出站原语，best-effort）。

    这是「员工真正长出嘴」的统一入口：员工在干活过程中可主动汇报进度、提建议、求确认——
    消息作为「该员工发来的 IM」出现在其 1:1 聊天页并实时推送。提问/汇报/建议都复用本函数。
    需 ``MODSTORE_INTERNAL_API_KEY``/``XCAGI_MARKET_INTERNAL_API_KEY`` 与 FHD 一致，
    ``XCAGI_FHD_INTERNAL_URL`` 指向 FHD 内网。返回是否成功投递。
    """
    key = _fhd_internal_api_key()
    body_text = (text or "").strip()
    if (
        not key
        or int(user_id or 0) <= 0
        or not str(employee_id or "").strip()
        or not body_text
    ):
        return False
    try:
        import httpx

        payload = {
            "boss_user_id": int(user_id),
            "employee_id": str(employee_id),
            "body": body_text,
            "display_name": str(display_name or employee_id),
        }
        if isinstance(notification, dict) and notification:
            payload["notification"] = notification
        last_error = ""
        with httpx.Client(timeout=5, trust_env=False) as client:
            for base in _fhd_internal_candidates():
                try:
                    resp = client.post(
                        f"{base}/api/internal/im/employee-message",
                        headers={"X-Internal-Api-Key": key},
                        json=payload,
                    )
                    if 200 <= resp.status_code < 300:
                        return True
                    last_error = f"{base} status={resp.status_code}"
                except Exception as exc:  # noqa: BLE001 - probe next known local endpoint
                    last_error = f"{base} {type(exc).__name__}"
        if last_error:
            logger.warning(
                "employee_message_to_boss exhausted candidates: %s", last_error
            )
        return False
    except Exception as e:  # noqa: BLE001 - 出站 IM 失败不影响主流程
        logger.warning("employee_message_to_boss failed: %s", e)
        return False


def post_employee_question_to_im(
    user_id: int, employee_id: str, question: str, task: str = ""
) -> None:
    """把员工提问作为该员工的 IM 消息投进老板聊天页（phase-D 双向问答出站，复用通用原语）。"""
    body_text = question if not task else f"{question}\n\n（任务：{task}）"
    employee_message_to_boss(user_id, employee_id, body_text)


def notify_human_question(
    user_id: int,
    question_id: int,
    employee_id: str,
    question: str,
    task: str = "",
) -> None:
    """Phase-D：员工向老板提问时推送站内通知 + 投进该员工 IM 聊天页（双向问答出站）。

    员工 cognition 输出 requires_human=true 触发 ask_human_blocking，
    这里把"员工有问题等你回答"推到通知中心 + 邮箱，并作为 IM 消息出现在该员工聊天页。
    """
    if not user_id:
        return
    try:
        title = f"员工 {employee_id} 有问题等你回答"
        task_suffix = f"（任务：{task}）" if task else ""
        create_notification(
            user_id=user_id,
            notification_type=NotificationType.HUMAN_QUESTION_ASKED,
            title=title,
            content=f"{question[:200]}{task_suffix}",
            data={
                "question_id": question_id,
                "employee_id": employee_id,
                "task": task,
                "question": question,
                "phase": "D",
            },
        )
    except Exception as e:
        logger.warning("notify_human_question failed: %s", e)
    # 出站半边：让问题作为该员工的 IM 消息出现在其聊天页（独立 best-effort，不被通知失败影响）。
    post_employee_question_to_im(user_id, employee_id, question, task)


def notify_quota_warning(
    user_id: int, quota_type: str, remaining: int, total: int
) -> None:
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
