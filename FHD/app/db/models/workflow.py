"""工作流定义与运行持久化模型。

提供 ``LLMWorkflowPlanner`` 生成的 ``PlanGraph`` 的可持久化载体，以及运行实例
（``WorkflowRun`` + ``WorkflowRunStep``）的状态跟踪。继承 ``TenantScopedMixin``
以纳入全局多租户隔离。
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func as sql_func

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class WorkflowTriggerType(str, Enum):
    """工作流触发类型。"""

    ONE_TIME = "one_time"
    EVENT = "event"
    SCHEDULE = "schedule"
    MANUAL = "manual"


class WorkflowRunStatus(str, Enum):
    """工作流运行状态机。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"


class WorkflowTriggerSource(str, Enum):
    """工作流运行触发来源。"""

    USER = "user"
    EVENT = "event"
    SCHEDULE = "schedule"


class WorkflowRunStepStatus(str, Enum):
    """单步执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowDefinition(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """工作流定义 — 持久化的 ``PlanGraph``，可重用、可编辑、可触发。

    ``nodes`` / ``edges`` / ``trigger_config`` 以 JSON 文本存储；服务层负责序列化与
    反序列化，避免 ORM 与 ``PlanGraph`` dataclass 强耦合。
    """

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        Index("ix_workflow_definitions_tenant_active", "tenant_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # one_time | event | schedule | manual
    trigger_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowTriggerType.MANUAL.value
    )
    # JSON 字符串：cron 表达式 / 事件 topic / 一次性 payload
    trigger_config: Mapped[Optional[str]] = mapped_column(Text)
    # JSON 字符串：PlanGraph.nodes 序列化
    nodes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串：节点依赖边
    edges: Mapped[Optional[str]] = mapped_column(Text, default="[]")
    # 每次更新自增（乐观并发控制）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer)

    runs: Mapped[list[WorkflowRun]] = relationship(
        "WorkflowRun", back_populates="definition", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "trigger_type": self.trigger_type,
            "trigger_config": json.loads(self.trigger_config) if self.trigger_config else {},
            "nodes": json.loads(self.nodes) if self.nodes else [],
            "edges": json.loads(self.edges) if self.edges else [],
            "version": self.version,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkflowRun(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """工作流运行实例 — 一次具体的执行。

    ``steps_snapshot`` 在创建时从 ``WorkflowDefinition.nodes`` 冻结，确保即使后续
    定义被修改，历史运行仍可追溯。
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_def_status", "definition_id", "status"),
        Index("ix_workflow_runs_tenant_started", "tenant_id", "started_at"),
    )

    definition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    # pending | running | succeeded | failed | cancelled | awaiting_approval
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowRunStatus.PENDING.value, index=True
    )
    # user | event | schedule
    triggered_by: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowTriggerSource.USER.value
    )
    trigger_payload: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)
    # JSON 字符串：运行开始时冻结的 nodes 快照
    steps_snapshot: Mapped[Optional[str]] = mapped_column(Text)

    definition: Mapped[Optional[WorkflowDefinition]] = relationship(
        "WorkflowDefinition", back_populates="runs"
    )
    steps: Mapped[list[WorkflowRunStep]] = relationship(
        "WorkflowRunStep", back_populates="run", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "definition_id": self.definition_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "triggered_by": self.triggered_by,
            "trigger_payload": json.loads(self.trigger_payload) if self.trigger_payload else {},
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "steps_snapshot": json.loads(self.steps_snapshot) if self.steps_snapshot else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkflowRunStep(IntegerPrimaryKeyMixin, Base):
    """工作流运行单步记录 — 对应 ``PlanGraph.nodes`` 中一个节点的执行状态。"""

    __tablename__ = "workflow_run_steps"
    __table_args__ = (Index("ix_workflow_run_steps_run_node", "run_id", "node_id"),)

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # pending | running | succeeded | failed | skipped
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowRunStepStatus.PENDING.value
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # JSON 字符串：节点执行结果
    result: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    # TimestampMixin 未继承（单步不需要 updated_at；created_at 由服务层填充）
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=sql_func.now()
    )

    run: Mapped[Optional[WorkflowRun]] = relationship("WorkflowRun", back_populates="steps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": json.loads(self.result) if self.result else {},
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
