"""派工工单（WorkOrder）持久化模型。

调度域的单一真相源：小C(assistant) 把一条任务派给某个员工后，落成一行
``work_orders``，贯穿 派工→执行→结果→汇报 全生命周期，可按发起人/受派人/状态查询。

与 ``AgentRunRecord``（工具编排，整包 JSON blob）不同：本表是**规范化**记录，
受派人分层（super / platform）与状态机均为独立列，便于"这个任务派给谁、到哪一步了"
的直接 SQL 查询与跨层统一收口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScopedMixin, TimestampMixin


class WorkOrder(Base, TenantScopedMixin, TimestampMixin):
    """一次派工的工单记录。

    业务数据 → 继承 :class:`TenantScopedMixin` 受全局租户隔离；单部署无租户时
    ``tenant_id`` 为 NULL，过滤 NULL 容忍故 no-op。
    """

    __tablename__ = "work_orders"
    __table_args__ = (
        Index("ix_work_orders_requester_status", "requester_user_id", "status"),
        Index("ix_work_orders_assignee", "assignee_tier", "assignee_id"),
    )

    work_order_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    # 发起方：默认小C助理（assistant 层）。
    requester: Mapped[str] = mapped_column(String(64), nullable=False, default="xiaoc")
    requester_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 受派人：tier ∈ {super, platform}；id 为超级员工 id 或平台员工 pack_id。
    assignee_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    assignee_id: Mapped[str] = mapped_column(String(128), nullable=False)
    assignee_name: Mapped[Optional[str]] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # 状态机：pending → dispatched → running → succeeded / failed / cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # 派工模式（预留三态：auto / direct / multi_device），当前默认 auto。
    dispatch_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    # 关联：tier-2 派工 request_id / tier-3 run 标识，便于回写对账。
    request_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text)
    result_json: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "requester": self.requester,
            "requester_user_id": self.requester_user_id,
            "assignee_tier": self.assignee_tier,
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
            "title": self.title,
            "instruction": self.instruction,
            "status": self.status,
            "dispatch_mode": self.dispatch_mode,
            "request_id": self.request_id,
            "result_summary": self.result_summary,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "dispatched_at": self.dispatched_at.isoformat() if self.dispatched_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
