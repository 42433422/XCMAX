"""多租户组织模型（对标钉钉 corpId 的第一步）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trial_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trial_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    plan_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
