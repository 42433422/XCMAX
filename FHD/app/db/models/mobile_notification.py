"""移动端自建推送：离线通知队列（outbox）。

极光移除后,后台送达靠这条队列:notify_user 把通知入队,客户端
`/api/notifications/pending`(WorkManager 轮询)拉取并标记 delivered。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.base import Base
from app.utils.time import utc_now_naive


class MobileNotificationOutbox(Base):
    __tablename__ = "mobile_notification_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    route = Column(String(300), nullable=False, default="")
    channel = Column(String(64), nullable=False, default="")
    data_json = Column(Text, nullable=False, default="{}")
    delivered = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive, index=True)
    delivered_at = Column(DateTime, nullable=True)
