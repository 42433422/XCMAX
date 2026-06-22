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
    """业务数据多租户隔离作用域列。

    仅业务模型继承；``User`` / ``Session`` / ``Tenant`` / RBAC 等**不**继承，
    故全局租户过滤（app/db/tenant_filter.py）永不波及登录与会话校验。
    nullable：存量未打标数据为 NULL，配合 NULL 容忍过滤不被隐藏。
    """

    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
