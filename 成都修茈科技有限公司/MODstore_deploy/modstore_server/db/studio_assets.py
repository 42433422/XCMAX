"""用户工作台「我的素材」持久化元数据（文件本体在 MODSTORE_DATA_DIR）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from modstore_server.db.base import Base


class UserStudioAsset(Base):
    __tablename__ = "user_studio_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(32), nullable=False, default="other")
    filename = Column(String(512), nullable=False, default="")
    mime_type = Column(String(256), nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False, default=0)
    storage_relpath = Column(String(1024), nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
