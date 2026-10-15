"""Resume a paused run, its session and its queue in one host transaction."""

import json
from typing import Any

from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    ApprovalGrantStorageError,
)
from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun, agent_run_from_dict, utc_now_iso
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.runtime_context import merge_runtime_context
from app.application.agent_orchestrator.session_renewal import renew_approval_session
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_models import TaskControlCommand
from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord, AgentTaskExecutionRecord


def resume_and_enqueue(
    runs: SQLAlchemyAgentRunRepository,
    queue: SQLAlchemyTaskExecutionRepository,
    *,
    run_id: str,
    principal_id: str,
    runtime_context: dict[str, Any],
    authenticated_binding: dict[str, Any] | None = None,
) -> AgentRun | None:
    with runs.transaction() as db:
        with queue.transaction(read_only=True) as queue_db:
            if db.get_bind() is not queue_db.get_bind():
                raise ApprovalGrantStorageError("恢复任务和队列必须使用同一数据库")
        execution = (
            db.query(AgentTaskExecutionRecord)
            .filter_by(run_id=run_id)
            .with_for_update()
            .one_or_none()
        )
        if execution is not None and execution.state == "claimed":
            raise ApprovalGrantError("任务执行器仍持有执行权，请等待结果核对")
        if execution is not None:
            # SQLite ignores FOR UPDATE. A conditional write both rechecks the
            # observation and holds the queue row through run/command updates.
            fenced = (
                db.query(AgentTaskExecutionRecord)
                .filter(
                    AgentTaskExecutionRecord.run_id == run_id,
                    AgentTaskExecutionRecord.state == execution.state,
                    AgentTaskExecutionRecord.execution_count == execution.execution_count,
                )
                .update(
                    {AgentTaskExecutionRecord.updated_at: execution.updated_at},
                    synchronize_session=False,
                )
            )
            if fenced != 1:
                raise ApprovalGrantError("任务执行权已变化，请刷新后重试")
        record = db.query(AgentRunRecord).filter_by(run_id=run_id).with_for_update().one_or_none()
        if record is None:
            return None
        old_payload = record.payload_json
        run = agent_run_from_dict(json.loads(old_payload))
        if run.status != "paused":
            return run
        if requires_retry_reconciliation(run):
            raise ApprovalGrantError("任务执行结果尚需人工核对，不能恢复执行")
        if any(step.status == "running" for step in run.steps):
            raise ApprovalGrantError("任务存在执行结果未确认的步骤，需要先核对")
        renew_approval_session(
            run,
            principal_id=principal_id,
            authenticated_binding=authenticated_binding,
            operation="resume",
        )
        context = merge_runtime_context(run, runtime_context)
        control = run.metadata.get("control") or {}
        needs_approval = control.get("resume_status") == "waiting_user" or any(
            step.status == "waiting_user" for step in run.steps
        )
        changed = (
            db.query(AgentRunRecord)
            .filter(
                AgentRunRecord.run_id == run_id,
                AgentRunRecord.payload_json == old_payload,
            )
            .update(
                {AgentRunRecord.status: "waiting_user" if needs_approval else "queued"},
                synchronize_session=False,
            )
        )
        if changed != 1:
            raise ApprovalGrantError("任务状态已变化，请刷新后重试")
        now = utc_now_iso()
        task = run.metadata.get("task_context") or {}
        command = TaskControlCommand(
            task_id=str(task.get("task_id") or ""),
            run_id=run_id,
            action="resume",
            requested_by=principal_id,
        )
        db.query(AgentTaskCommandRecord).filter(
            AgentTaskCommandRecord.run_id == run_id,
            AgentTaskCommandRecord.status == "requested",
        ).update(
            {AgentTaskCommandRecord.status: "superseded", AgentTaskCommandRecord.applied_at: now},
            synchronize_session=False,
        )
        db.add(
            AgentTaskCommandRecord(
                command_id=command.command_id,
                task_id=command.task_id,
                run_id=run_id,
                action="resume",
                status="applied",
                requested_by=principal_id,
                metadata_json="{}",
                created_at=command.created_at,
                applied_at=now,
            )
        )
        run.metadata["runtime_context"] = context
        run.metadata["control"] = {
            "state": "queued",
            "requested_by": principal_id,
            "command_id": command.command_id,
        }
        run.status = "waiting_user" if needs_approval else "queued"
        if not needs_approval:
            run.metadata["dispatch"] = {
                "state": "queued",
                "approved_step_id": "",
                "requested_by": principal_id,
                "queued_at": now,
            }
        run.add_event(
            "run.resumed",
            "Agent run 已恢复",
            {"requested_by": principal_id, "command_id": command.command_id},
        )
        runs.save_in_session(db, run)
        if not needs_approval:
            queue.enqueue_in_session(db, run, requested_by=principal_id)
        elif execution is not None:
            execution.state = "paused"
            execution.updated_at = now
    return run
