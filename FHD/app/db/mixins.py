"""SQLAlchemy ORM mixins — v10 线内统一主键与时间戳。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class IntegerPrimaryKeyMixin:
    """INTEGER 自增主键（PG/SQLite 通用 autoincrement）。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(default=False)


class TenantScopedMixin:
    """业务数据租户标记。继承本 mixin 的模型会被全局 ORM 事件
    （见 ``app/db/tenant_filter.py``）按当前租户自动过滤(读)与打标(写)。

    auth / 身份类模型（User / Session / Role / Permission / Tenant）**故意不继承**，
    以保证登录、会话与权限可跨租户查询。
    """

    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
