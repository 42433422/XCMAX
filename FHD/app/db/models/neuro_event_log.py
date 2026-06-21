"""NeuroBus 已消费业务事件的持久化落地表。

Application 层在 default-ON 路径发布的领域事件（``application.*``）被领域消费者消费后，
在此表落一条持久审计/投影记录。这是 NeuroBus 在核心 app service「真实落地」的可观测、
可持久副作用：将原本 fire-and-forget、无消费者即被丢弃（``No handlers for event``）的事件，
转为可查询、可对账的持久记录，同时修复「处理失败被静默吞掉」的可观测性缺口。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NeuroEventLog(Base):
    """单条 NeuroBus 已消费事件的持久投影。"""

    __tablename__ = "neuro_event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), default="", index=True)
    source: Mapped[str] = mapped_column(String(120), default="")
    correlation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload: Mapped[str] = mapped_column(Text, default="")
    # 消费者执行的额外副作用标识（如 product_cache_invalidated），便于审计/对账。
    side_effect: Mapped[str] = mapped_column(String(120), default="")
