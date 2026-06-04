from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.utils.time import utc_now_naive


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utc_now_naive)


class DataScope(Base):
    """ABAC-style row filter metadata per tenant and resource type."""

    __tablename__ = "data_scopes"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # JSON list of department ids or filter key; interpreted by apply_data_scope()
    scope_json: Mapped[str] = mapped_column(String(2048), default="{}")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utc_now_naive)
