"""传统节点图工作流（只读迁移源）、触发器版本与脚本工作流。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class Workflow(Base):
    """工作流模型（节点图，**已弃用**：保留为只读迁移源数据）。"""

    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    migration_status = Column(String(16), default="", index=True)
    migrated_to_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(32), default="", index=True)


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    node_type = Column(String(64), nullable=False)
    name = Column(String(256), nullable=False)
    config = Column(Text, default="{}")
    position_x = Column(Float, default=0.0)
    position_y = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    source_node_id = Column(Integer, ForeignKey("workflow_nodes.id"), nullable=False)
    target_node_id = Column(Integer, ForeignKey("workflow_nodes.id"), nullable=False)
    condition = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkflowSandboxRun(Base):
    __tablename__ = "workflow_sandbox_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ok = Column(Boolean, default=False, index=True)
    validate_only = Column(Boolean, default=False, index=True)
    mock_employees = Column(Boolean, default=True)
    graph_fingerprint = Column(String(64), default="", index=True)
    report_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(32), default="pending")
    input_data = Column(Text, default="{}")
    output_data = Column(Text, default="{}")
    error_message = Column(Text, default="")
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class WorkflowTrigger(Base):
    __tablename__ = "workflow_triggers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    trigger_type = Column(String(32), nullable=False, index=True)
    trigger_key = Column(String(128), default="", index=True)
    config_json = Column(Text, default="{}")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version_no", name="uq_workflow_version_no"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    note = Column(Text, default="")
    graph_snapshot = Column(Text, nullable=False, default="{}")
    is_current = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScriptWorkflow(Base):
    __tablename__ = "script_workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    brief_json = Column(Text, default="{}")
    script_text = Column(Text, default="")
    schema_in_json = Column(Text, default="{}")
    status = Column(String(32), default="draft", index=True)
    agent_session_id = Column(String(64), default="", index=True)
    migrated_from_workflow_id = Column(Integer, nullable=True, index=True)
    last_manual_sandbox_run_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ScriptWorkflowVersion(Base):
    __tablename__ = "script_workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version_no", name="uq_script_workflow_version_no"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("script_workflows.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    script_text = Column(Text, default="")
    plan_md = Column(Text, default="")
    agent_log_json = Column(Text, default="{}")
    is_current = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScriptWorkflowRun(Base):
    __tablename__ = "script_workflow_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("script_workflows.id"), nullable=False, index=True)
    version_id = Column(
        Integer, ForeignKey("script_workflow_versions.id"), nullable=True, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mode = Column(String(16), default="auto", index=True)
    status = Column(String(16), default="running", index=True)
    stdout = Column(Text, default="")
    stderr = Column(Text, default="")
    outputs_meta_json = Column(Text, default="[]")
    runtime_sdk_calls_json = Column(Text, default="[]")
    error_message = Column(Text, default="")
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = Column(DateTime, nullable=True)
