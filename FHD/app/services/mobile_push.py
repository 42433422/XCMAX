"""移动端推送：FCM（可选）+ 自建推送（在线 WS 下发 + 离线队列）。极光 JPush 已移除。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import inspect as sa_inspect

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _fcm_enabled() -> bool:
    return bool(
        os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    )


def send_fcm(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    if not tokens or not _fcm_enabled():
        return False
    try:
        import google.oauth2.service_account
        from google.auth.transport.requests import Request
    except ImportError:
        logger.warning("google-auth not installed; skip FCM")
        return False

    cred_path = (
        os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        or ""
    ).strip()
    if not cred_path or not os.path.isfile(cred_path):
        logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON not a file: %s", cred_path)
        return False

    try:
        creds = google.oauth2.service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        creds.refresh(Request())
        access_token = creds.token
        project_id = json.load(open(cred_path, encoding="utf-8")).get("project_id")
        if not project_id:
            return False
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        ok_any = False
        str_data = {k: str(v) for k, v in (data or {}).items()}
        for token in tokens[:500]:
            msg = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": str_data,
                }
            }
            r = httpx.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=msg,
                timeout=15.0,
            )
            if r.status_code < 400:
                ok_any = True
            else:
                logger.warning("fcm token fail: %s", r.text[:300])
        return ok_any
    except RECOVERABLE_ERRORS as exc:
        logger.warning("fcm error: %s", exc)
        return False


def send_to_user_devices(
    devices: List[Dict[str, Any]],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, bool]:
    """devices: rows with push_provider, push_token (or legacy fcm_token)."""
    fcm_tokens: List[str] = []
    for d in devices:
        tok = (d.get("push_token") or d.get("fcm_token") or "").strip()
        if not tok:
            continue
        # 极光已移除；非 FCM 设备走自建推送（见 notify_user 的离线队列入账），不在此处发。
        provider = (d.get("push_provider") or "fcm").strip().lower()
        if provider in ("fcm", ""):
            fcm_tokens.append(tok)
    return {
        "fcm": send_fcm(fcm_tokens, title, body, data),
    }


def enqueue_outbox(
    user_id: int, title: str, body: str, data: Optional[Dict[str, Any]] = None
) -> bool:
    """写入自建推送离线队列。客户端 /api/notifications/pending 轮询拉取(WorkManager 后台通道)。"""
    from app.db.models.mobile_notification import MobileNotificationOutbox
    from app.db.session import get_db

    payload = data or {}
    try:
        with get_db() as db:
            bind = db.get_bind()
            if not sa_inspect(bind).has_table(MobileNotificationOutbox.__tablename__):
                MobileNotificationOutbox.__table__.create(bind, checkfirst=True)
            db.add(
                MobileNotificationOutbox(
                    user_id=int(user_id),
                    title=(title or "")[:200],
                    body=body or "",
                    route=str(payload.get("route") or "")[:300],
                    channel=str(payload.get("channel") or "")[:64],
                    data_json=json.dumps(payload, ensure_ascii=False),
                )
            )
        return True
    except RECOVERABLE_ERRORS as exc:
        logger.warning("enqueue_outbox error: %s", exc)
        return False


def notify_user(
    user_id: int, title: str, body: str, data: Optional[Dict[str, Any]] = None
) -> Dict[str, bool]:
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db

    with get_db() as db:
        rows = db.query(MobileDeviceToken).filter(MobileDeviceToken.user_id == user_id).all()
        devices = [
            {
                "push_provider": getattr(r, "push_provider", None) or "fcm",
                "push_token": getattr(r, "push_token", None) or r.fcm_token,
                "fcm_token": r.fcm_token,
            }
            for r in rows
        ]
    result = send_to_user_devices(devices, title, body, data)
    # 自建推送后台通道:无论 FCM 是否送达,都入离线队列供轮询补发。
    result["outbox"] = enqueue_outbox(user_id, title, body, data)
    return result
