"""移动端自建推送：离线通知队列（outbox）。

极光移除后,后台送达靠这条队列:notify_user 把通知入队,客户端
`/api/notifications/pending`(WorkManager 轮询)拉取并标记 delivered。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base
from app.utils.time import utc_now_naive


class MobileNotificationOutbox(Base):
    __tablename__ = "mobile_notification_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    route = Column(String(300), nullable=False, default="")
    channel = Column(String(64), nullable=False, default="")
    data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Delivery is transport state; reading is an independent account action.
    recipient_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def notification_recipient_scope(user: Any) -> str:
    if user is None or type(getattr(user, "id", None)) is not int or user.id <= 0:
        return ""
    if not hasattr(user, "tenant_id"):
        return ""
    tenant = user.tenant_id
    if tenant is None:
        return "local"
    return f"tenant:{tenant}" if type(tenant) is int and tenant > 0 else ""
