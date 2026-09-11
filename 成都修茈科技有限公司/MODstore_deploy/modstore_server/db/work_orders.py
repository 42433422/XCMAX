"""工单事件流持久化：共享宿主的 Work Order SSOT 事件表。

与 FHD 侧本地 JSONL 事件流语义一致（同一 wo_id / 同一状态机），
但落在市场端共享数据库，供多进程（本地 relay、CI closeout、管理端）读写。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from modstore_server.db.base import Base


class WorkOrderEvent(Base):
    __tablename__ = "work_order_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wo_id = Column(String(32), nullable=False)
    event = Column(String(16), nullable=False)  # created | transition
    source = Column(String(64), default="", nullable=False)
    dedup_key = Column(String(96), default="", nullable=False)
    reason = Column(String(64), default="", nullable=False)
    context = Column(Text, default="{}", nullable=False)  # JSON
    from_state = Column(String(16), default="", nullable=False)
    to_state = Column(String(16), default="", nullable=False)
    ref = Column(Text, default="{}", nullable=False)  # JSON
    note = Column(String(500), default="", nullable=False)
    at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    ts_unix = Column(Float, default=lambda: datetime.now(UTC).timestamp(), nullable=False)

    __table_args__ = (
        Index("ix_work_order_events_wo_id", "wo_id"),
        Index("ix_work_order_events_at", "at"),
    )


__all__ = ["WorkOrderEvent"]
