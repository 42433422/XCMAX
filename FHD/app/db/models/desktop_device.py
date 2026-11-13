"""桌面设备心跳：用于移动端判断任务执行端是否在线。"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.db_base import Base
from app.utils.time import utc_now_naive


class DesktopDeviceRecord(Base):
    __tablename__ = "desktop_devices"

    device_id = Column(String(160), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    tenant_id = Column(String(128), nullable=False, default="", index=True)
    label = Column(String(200), nullable=False, default="")
    platform = Column(String(32), nullable=False, default="desktop")
    app_version = Column(String(64), nullable=False, default="")
    capabilities_json = Column(Text, nullable=False, default="{}")
    last_seen_at = Column(DateTime, nullable=False, default=utc_now_naive, index=True)
