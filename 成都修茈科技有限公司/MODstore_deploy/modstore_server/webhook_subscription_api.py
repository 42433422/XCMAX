"""开发者级 Webhook 订阅管理 API。

涵盖：
- 订阅 CRUD（``/api/developer/webhooks``）
- 投递日志查询（``/api/developer/webhooks/{id}/deliveries``）
- 手动重试单条失败投递（``/api/developer/webhooks/deliveries/{delivery_id}/retry``）
- 手动发送测试事件（``/api/developer/webhooks/{id}/test``），便于配置完成后立刻验证回调

订阅签名密钥使用 ``llm_crypto`` 中的 Fernet 加密保存；列表只返回掩码后的 prefix。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server import webhook_dispatcher
from modstore_server.api.deps import _get_current_user
from modstore_server.eventing.contracts import EVENT_CONTRACTS
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_crypto import encrypt_secret, fernet_configured, mask_api_key
from modstore_server.models import User, WebhookDelivery, WebhookSubscription

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/developer/webhooks", tags=["developer", "webhooks"])


class CreateSubscriptionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    target_url: str = Field(..., min_length=8, max_length=1024)
    secret: str = Field("", max_length=256)
    enabled_events: List[str] = Field(default_factory=lambda: ["*"])
    description: str = Field("", max_length=2000)
    is_active: bool = True


class UpdateSubscriptionBody(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    target_url: Optional[str] = Field(None, max_length=1024)
    secret: Optional[str] = Field(None, max_length=256)
    enabled_events: Optional[List[str]] = None
    description: Optional[str] = Field(None, max_length=2000)
    is_active: Optional[bool] = None


def _safe_load_events(raw: Optional[str]) -> List[str]:
    if not raw:
        return ["*"]
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return ["*"]
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return ["*"]


def _serialize_subscription(row: WebhookSubscription) -> Dict[str, Any]:
    has_secret = bool(row.secret_encrypted)
    return {
        "id": row.id,
        "name": row.name or "",
        "description": row.description or "",
        "target_url": row.target_url,
        "secret_mask": mask_api_key((row.secret_encrypted or "")[:4]) if has_secret else "",
        "has_secret": has_secret,
        "secret_storage": (
            "fernet"
            if has_secret and fernet_configured()
            else ("plaintext" if has_secret else "none")
        ),
        "enabled_events": _safe_load_events(row.enabled_events_json),
        "is_active": bool(row.is_active),
        "success_count": int(row.success_count or 0),
        "failure_count": int(row.failure_count or 0),
        "last_delivery_at": row.last_delivery_at.isoformat() if row.last_delivery_at else None,
        "last_delivery_status": row.last_delivery_status or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_delivery(row: WebhookDelivery) -> Dict[str, Any]:
    return {
        "id": row.id,
        "subscription_id": row.subscription_id,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "target_url": row.target_url,
        "status": row.status,
        "status_code": row.status_code,
        "attempts": int(row.attempts or 0),
        "duration_ms": float(row.duration_ms or 0.0),
        "request_body": row.request_body or "",
        "response_body": row.response_body or "",
        "error_message": row.error_message or "",
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _encrypt_secret_or_warn(secret: str) -> str:
    if not secret:
        return ""
    if not fernet_configured():
        logger.warning(
            "MODSTORE_FERNET_KEY 未配置，webhook secret 将以非加密方式保存（仅开发期可接受）"
        )
        return secret
    return encrypt_secret(secret)


@router.get("/event-catalog", summary="可订阅的业务事件清单")
async def list_event_catalog():
    """提供给前端展示可订阅事件的字典；与 ``eventing.contracts`` 单一真相源。"""
    return [
        {
            "name": c.name,
            "version": c.version,
            "aggregate": c.aggregate,
            "description": c.description,
            "required_payload": list(c.required_payload),
        }
        for c in EVENT_CONTRACTS.values()
    ]


@router.post("", summary="创建 Webhook 订阅")
async def create_subscription(
    body: CreateSubscriptionBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if not (body.target_url.startswith("http://") or body.target_url.startswith("https://")):
        raise HTTPException(400, "target_url 必须是 http(s) 链接")
    enabled = body.enabled_events or ["*"]
    row = WebhookSubscription(
        user_id=user.id,
        name=body.name.strip(),
        description=(body.description or "").strip(),
        target_url=body.target_url.strip(),
        secret_encrypted=_encrypt_secret_or_warn((body.secret or "").strip()),
        enabled_events_json=json.dumps(enabled, ensure_ascii=False),
        is_active=bool(body.is_active),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_subscription(row)


@router.get("", summary="Webhook 订阅列表")
async def list_subscriptions(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(WebhookSubscription)
        .filter(WebhookSubscription.user_id == user.id)
        .order_by(WebhookSubscription.created_at.desc())
        .all()
    )
    return [_serialize_subscription(r) for r in rows]


@router.get("/{subscription_id}", summary="订阅详情")
async def get_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    row = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "订阅不存在")
    return _serialize_subscription(row)


@router.put("/{subscription_id}", summary="更新订阅")
async def update_subscription(
    subscription_id: int,
    body: UpdateSubscriptionBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    row = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "订阅不存在")

    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description.strip()
    if body.target_url is not None:
        if not (body.target_url.startswith("http://") or body.target_url.startswith("https://")):
            raise HTTPException(400, "target_url 必须是 http(s) 链接")
        row.target_url = body.target_url.strip()
    if body.secret is not None:
        row.secret_encrypted = _encrypt_secret_or_warn(body.secret.strip())
    if body.enabled_events is not None:
        row.enabled_events_json = json.dumps(body.enabled_events or ["*"], ensure_ascii=False)
    if body.is_active is not None:
        row.is_active = bool(body.is_active)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize_subscription(row)


@router.delete("/{subscription_id}", summary="删除订阅（投递日志保留）")
async def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    row = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "订阅不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/{subscription_id}/deliveries", summary="投递日志（按订阅）")
async def list_deliveries(
    subscription_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="success|failed|pending"),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    sub = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.user_id == user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(404, "订阅不存在")
    q = db.query(WebhookDelivery).filter(WebhookDelivery.subscription_id == subscription_id)
    if status:
        q = q.filter(WebhookDelivery.status == status.strip().lower())
    rows = q.order_by(WebhookDelivery.started_at.desc()).limit(limit).offset(offset).all()
    return [_serialize_delivery(r) for r in rows]


@router.post(
    "/deliveries/{delivery_id}/retry",
    summary="手动重试一次失败的投递（产生一条新投递记录）",
)
async def retry_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    delivery = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.user_id == user.id,
        )
        .first()
    )
    if not delivery:
        raise HTTPException(404, "投递记录不存在")
    sub = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.id == delivery.subscription_id,
            WebhookSubscription.user_id == user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(404, "订阅不存在或已删除")

    try:
        event = json.loads(delivery.request_body or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"原始事件 JSON 损坏: {exc}") from exc

    webhook_dispatcher._deliver_event_to_subscription(db, sub, event)
    db.commit()
    new_row = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.subscription_id == sub.id)
        .order_by(WebhookDelivery.started_at.desc())
        .first()
    )
    return _serialize_delivery(new_row) if new_row else {"ok": True}


@router.post("/{subscription_id}/test", summary="向订阅发送一条测试事件 (modstore.webhook_test)")
async def send_test_event(
    subscription_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    sub = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.user_id == user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(404, "订阅不存在")
    event = webhook_dispatcher.build_event(
        "modstore.webhook_test",
        aggregate_id=str(sub.id),
        data={
            "subscription_id": sub.id,
            "user_id": user.id,
            "message": "ping from MODstore developer portal",
            "ts": int(datetime.now(timezone.utc).timestamp()),
        },
        source="modstore-developer-portal",
    )
    webhook_dispatcher._deliver_event_to_subscription(db, sub, event)
    db.commit()
    new_row = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.subscription_id == sub.id)
        .order_by(WebhookDelivery.started_at.desc())
        .first()
    )
    return _serialize_delivery(new_row) if new_row else {"ok": True}
