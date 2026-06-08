"""Notification domain value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class NotificationType(str, Enum):
    """支持的通知类型。

    与 ``modstore_server.notification_service.NotificationType`` 同步。
    数据库列名是 ``type``，因此这里取值需要保持稳定（小写 + 下划线），
    跨服务消费方依赖这些字面量。
    """

    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    EMPLOYEE_EXECUTION_DONE = "employee_execution_done"
    QUOTA_WARNING = "quota_warning"
    SYSTEM = "system"


@dataclass(frozen=True)
class OutboundNotification:
    """Application 入口构造的不可变值对象。

    通过 :class:`NotificationRepository` 落库后会换成 :class:`Notification`
    （带 ID、created_at 等持久化字段）。
    """

    user_id: int
    notification_type: NotificationType
    title: str
    content: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Notification:
    """已持久化的通知聚合。"""

    id: int
    user_id: int
    notification_type: NotificationType
    title: str
    content: str
    data: dict[str, Any]
    is_read: bool
    created_at: datetime | None
