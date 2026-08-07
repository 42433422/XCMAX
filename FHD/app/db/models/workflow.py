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
    __table_args__ = (Index("ix_workflow_definitions_tenant_active", "tenant_id", "is_active"),)

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
    # JSON 字符串：最近一次 runtime_context 快照（checkpoint 支持，可空）
    context_checkpoint: Mapped[Optional[str]] = mapped_column(Text)

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
            "context_checkpoint": (
                json.loads(self.context_checkpoint) if self.context_checkpoint else {}
            ),
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


class WorkflowCheckpoint(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    """DB 持久化的工作流 checkpoint 快照（对标 LangGraph BaseCheckpointSaver）。

    每次执行（节点或一批）完成后在 ``workflow_checkpoints`` 落一行快照，把
    ``runtime_context`` 与已执行节点集合持久化到数据库，支持跨进程断点续跑与
    只读重放。``checkpoint_id`` 为逻辑键（非主键），同一 ``plan_id`` 下按
    ``step_index`` 升序构成可回溯的历史。
    """

    __tablename__ = "workflow_checkpoints"
    __table_args__ = (Index("ix_workflow_checkpoints_plan_step", "plan_id", "step_index"),)

    plan_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    checkpoint_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 执行进度（已执行节点数），用于按序排列历史快照
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON 字符串：runtime_context 快照
    runtime_context: Mapped[Optional[str]] = mapped_column(Text)
    # JSON 字符串：已执行节点集合
    executed_nodes: Mapped[Optional[str]] = mapped_column(Text)
    # JSON 字符串：条件边屏蔽的分支目标集合
    blocked: Mapped[Optional[str]] = mapped_column(Text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "checkpoint_id": self.checkpoint_id,
            "step_index": self.step_index,
            "runtime_context": json.loads(self.runtime_context) if self.runtime_context else {},
            "executed_nodes": json.loads(self.executed_nodes) if self.executed_nodes else [],
            "blocked": json.loads(self.blocked) if self.blocked else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WorkflowPlan(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    """持久化的动态工作流计划（跨会话续跑的载体）。

    工作流规划产出的 ``PlanGraph`` 序列化后按 ``plan_id`` 落库；配合 DB 化的
    checkpoint（``workflow_checkpoints``）即可在用户换会话/进程重启后，通过
    ``plan_id`` 载入计划并从最新 checkpoint 续跑，实现真正的长任务跨会话续跑。
    ``status`` 标记计划生命周期（running / pending_awaiting / succeeded / failed /
    cancelled）。
    """

    __tablename__ = "workflow_plans"
    __table_args__ = (Index("ix_workflow_plans_user_status", "user_id", "status"),)

    plan_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, unique=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    intent: Mapped[Optional[str]] = mapped_column(String(256))
    # JSON 字符串：PlanGraph 序列化（plan_to_dict 产物）
    plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON 字符串：runtime_context 快照
    runtime_context: Mapped[Optional[str]] = mapped_column(Text)
    # running | pending_awaiting | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    message: Mapped[Optional[str]] = mapped_column(Text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "intent": self.intent,
            "plan": json.loads(self.plan_json) if self.plan_json else {},
            "runtime_context": json.loads(self.runtime_context) if self.runtime_context else {},
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
