"""桌面设备心跳：用于移动端判断任务执行端是否在线。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base
from app.utils.time import utc_now_naive


class DesktopDeviceRecord(Base):
    __tablename__ = "desktop_devices"

    device_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="desktop")
    app_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, index=True
    )
