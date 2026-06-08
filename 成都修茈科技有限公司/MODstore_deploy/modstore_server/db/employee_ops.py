"""员工执行度量、Duty 编排、运维审批与协作。"""

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


class EmployeeExecutionMetric(Base):
    __tablename__ = "employee_execution_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    employee_id = Column(String(128), nullable=False, index=True)
    task = Column(String(128), default="")
    status = Column(String(32), default="success")
    duration_ms = Column(Float, default=0.0)
    llm_tokens = Column(Integer, default=0)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DutyGraphRun(Base):
    __tablename__ = "duty_graph_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_employee_id = Column(String(128), nullable=False, index=True)
    task = Column(Text, default="")
    input_data_json = Column(Text, default="{}")
    include_dependencies = Column(Boolean, default=True)
    max_concurrency = Column(Integer, default=2)
    allow_high_risk_real_run = Column(Boolean, default=False)
    status = Column(String(32), default="pending", index=True)
    total_nodes = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class DutyGraphRunNode(Base):
    __tablename__ = "duty_graph_run_nodes"
    __table_args__ = (UniqueConstraint("run_id", "employee_id", name="uq_duty_graph_run_employee"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("duty_graph_runs.id"), nullable=False, index=True)
    employee_id = Column(String(128), nullable=False, index=True)
    order_index = Column(Integer, default=0, nullable=False)
    depends_on_json = Column(Text, default="[]")
    status = Column(String(32), default="pending", index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, default=0.0)
    llm_tokens = Column(Integer, default=0)
    metric_id = Column(
        Integer, ForeignKey("employee_execution_metrics.id"), nullable=True, index=True
    )
    summary = Column(Text, default="")
    error = Column(Text, default="")
    result_json = Column(Text, default="{}")


class OpsActionAuditLog(Base):
    __tablename__ = "ops_action_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    employee_id = Column(String(128), nullable=False, index=True)
    handler = Column(String(32), nullable=False)
    command_id = Column(String(128), nullable=False, index=True)
    args_json = Column(Text, default="{}")
    host_id = Column(String(64), default="", index=True)
    exit_code = Column(Integer, nullable=True)
    stdout_excerpt = Column(Text, default="")
    stderr_excerpt = Column(Text, default="")
    duration_ms = Column(Float, default=0.0)
    approval_required = Column(Boolean, default=False, index=True)
    dry_run = Column(Boolean, default=False)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, index=True)
    source = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, default="{}")
    fingerprint = Column(String(128), default="", index=True)
    dispatched_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class EmployeeTriggerBinding(Base):
    __tablename__ = "employee_trigger_bindings"
    __table_args__ = (
        UniqueConstraint("employee_id", "event_type", name="uq_employee_trigger_event"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    is_active = Column(Boolean, default=True, index=True)
    priority = Column(Integer, default=5, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class OpsApprovalToken(Base):
    __tablename__ = "ops_approval_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    kind = Column(String(32), nullable=False, index=True)
    payload_json = Column(Text, default="{}")
    authorized_email = Column(String(128), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True, index=True)
    consumed_message_id = Column(String(512), default="", index=True)
    dispatched_audit_ids_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class DailyDigestRecord(Base):
    __tablename__ = "daily_digest_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(String(32), nullable=False, index=True)
    subject = Column(String(256), nullable=False, index=True)
    body_html = Column(Text, default="")
    body_text = Column(Text, default="")
    meeting_minutes_html = Column(Text, default="")
    vibe_prep_updates_md = Column(Text, default="")
    vibe_prep_patches_md = Column(Text, default="")
    vibe_prep_meta_json = Column(Text, default="")
    vibe_prep_pw_md = Column(Text, default="")
    vibe_prep_ps_md = Column(Text, default="")
    vibe_prep_app_md = Column(Text, default="")
    vibe_prep_sr_md = Column(Text, default="")
    vibe_prep_line_dispatch_json = Column(Text, default="")
    vibe_line_execute_json = Column(Text, default="")
    release_train_before = Column(String(32), default="")
    release_train_after = Column(String(32), default="")
    release_kind = Column(String(16), default="")
    recipients_json = Column(Text, default="[]")
    delivery_json = Column(Text, default="[]")
    delivered = Column(Boolean, default=False, index=True)
    source = Column(String(32), default="daily_digest", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class OpsStagedChange(Base):
    __tablename__ = "ops_staged_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    branch = Column(String(256), nullable=False, index=True)
    base_commit = Column(String(64), nullable=False, default="")
    head_commit = Column(String(64), nullable=False, default="")
    files_changed_count = Column(Integer, default=0)
    diff_summary = Column(Text, default="")
    created_by_employee_id = Column(
        String(128), nullable=False, default="daily-orchestrator", index=True
    )
    status = Column(String(32), nullable=False, default="pending", index=True)
    deploy_audit_id = Column(
        Integer, ForeignKey("ops_action_audit_logs.id"), nullable=True, index=True
    )
    approval_token_id = Column(
        Integer, ForeignKey("ops_approval_tokens.id"), nullable=True, index=True
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    approved_at = Column(DateTime, nullable=True)
    deployed_at = Column(DateTime, nullable=True)


class OnDemandOrchestrateJob(Base):
    __tablename__ = "on_demand_orchestrate_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_description = Column(Text, default="")
    status = Column(String(32), default="pending", index=True)
    use_task_router = Column(Boolean, default=True)
    target_employee_id = Column(String(128), default="")
    max_concurrency = Column(Integer, default=2)
    allow_high_risk_real_run = Column(Boolean, default=False)
    llm_provider = Column(String(64), default="auto")
    llm_model = Column(String(128), default="auto")
    result_json = Column(Text, default="")
    error = Column(Text, default="")
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class EmployeeChangeRequest(Base):
    __tablename__ = "employee_change_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_employee_id = Column(String(128), nullable=False, index=True)
    change_kind = Column(String(32), nullable=False, index=True)
    workspace_root_hint = Column(String(512), default="", index=True)
    target_paths_json = Column(Text, default="[]")
    diff_summary = Column(Text, default="")
    diff_blob = Column(Text, default="")
    status = Column(String(32), default="pending", index=True)
    risk_level = Column(String(16), default="low")
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    rejected_reason = Column(Text, default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    git_branch = Column(String(256), default="", index=True)
    base_commit_sha = Column(String(64), default="")
    staged_commit_sha = Column(String(64), default="")
    approval_required_globs_json = Column(Text, default="[]")


class PendingBriefTask(Base):
    __tablename__ = "pending_brief_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_employee_id = Column(String(128), nullable=False, index=True)
    source_kind = Column(String(32), default="daily_brief", index=True)
    source_ref = Column(String(128), default="", index=True)
    task_brief = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    fingerprint = Column(String(64), default="", unique=True, index=True)
    status = Column(String(32), default="pending", index=True)
    dispatched_run_id = Column(String(64), default="")
    dispatched_result_json = Column(Text, default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    dispatched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class EmployeeCollabThread(Base):
    __tablename__ = "employee_collab_threads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), default="", index=True)
    participants_json = Column(Text, default="[]")
    context_json = Column(Text, default="{}")
    status = Column(String(32), default="open", index=True)
    created_by_employee_id = Column(String(128), default="", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EmployeeCollabMessage(Base):
    __tablename__ = "employee_collab_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(
        Integer, ForeignKey("employee_collab_threads.id"), nullable=False, index=True
    )
    sender_employee_id = Column(String(128), default="", index=True)
    content = Column(Text, default="")
    mentions_json = Column(Text, default="[]")
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class EmployeeSuggestion(Base):
    __tablename__ = "employee_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_employee_id = Column(String(128), nullable=False, index=True)
    target_employee_ids_json = Column(Text, default="[]")
    kind = Column(String(64), default="general", index=True)
    summary = Column(Text, default="")
    detail = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    risk_level = Column(String(16), default="medium", index=True)
    status = Column(String(32), default="pending", index=True)
    thread_id = Column(Integer, ForeignKey("employee_collab_threads.id"), nullable=True, index=True)
    created_change_request_ids_json = Column(Text, default="[]")
    created_task_ids_json = Column(Text, default="[]")
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_reason = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EmployeeEvolutionRecord(Base):
    __tablename__ = "employee_evolution_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(128), nullable=False, index=True)
    failure_count = Column(Integer, default=0)
    lookback_hours = Column(Integer, default=24)
    status = Column(String(32), default="suggested", index=True)
    prompt_before = Column(Text, default="")
    prompt_after = Column(Text, default="")
    diff_explanation = Column(Text, default="")
    triggered_by = Column(String(64), default="scheduler", index=True)
    created_suggestion_id = Column(
        Integer, ForeignKey("employee_suggestions.id"), nullable=True, index=True
    )
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
