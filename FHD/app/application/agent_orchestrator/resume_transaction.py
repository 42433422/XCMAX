"""Resume a paused run, its session and its queue in one host transaction."""

import json
import time
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


def unresolved_effects(db: Any, run: AgentRun, *, clear_confirmed: bool = False) -> list[str]:
    """Only a durable successful step receipt can settle an old open effect."""
    from app.application.agent_orchestrator.result_verification import verified_effect_receipt
    from app.application.agent_orchestrator.task_models import tenant_id_of_run
    from app.domain.task_lifecycle.control import SessionBook

    book = SessionBook(db)
    tenant = tenant_id_of_run(run)
    body = book.get("agent", tenant, run.run_id)
    completed = {step.step_id for step in run.steps if verified_effect_receipt(run, step)}
    remaining = sorted(set(body.get("effects") or []) - completed)
    if clear_confirmed and not remaining and body.get("effects"):
        body["effects"] = []
        book.put("agent", tenant, run.run_id, body)
    return remaining


def retry_and_enqueue(
    runs: SQLAlchemyAgentRunRepository,
    *,
    run_id: str,
    principal_id: str,
    runtime_context: dict[str, Any],
    authenticated_binding: dict[str, Any] | None = None,
    authenticated_actor_binding: dict[str, Any] | None = None,
    verification_lease_token: str = "",
    expected_execution: Any = None,
    verification_time: float | None = None,
) -> AgentRun | None:
    """CAS a safe continuation and its queue without changing run/step identities."""
    from app.application.agent_orchestrator.run_lifecycle import (
        prepare_safe_continuation,
        safe_continuation_error,
    )
    from app.domain.task_lifecycle.adapters import execution_requeue_allowed

    queue = SQLAlchemyTaskExecutionRepository(session_factory=runs._session_factory)
    queue._ensure_schema()
    with runs.transaction() as db:
        execution = (
            db.query(AgentTaskExecutionRecord)
            .filter_by(run_id=run_id)
            .with_for_update()
            .one_or_none()
        )
        if verification_lease_token and (
            execution is None
            or expected_execution is None
            or queue._to_model(execution).to_dict() != expected_execution.to_dict()
            or execution.state not in {"blocked", "failed"}
            or execution.lease_owner
            or execution.lease_expires_at
        ):
            raise ApprovalGrantError("原执行队列已变化或仍有未知结果，不能自动确认")
        if execution is not None:
            if not execution_requeue_allowed(str(execution.state), retryable=True):
                raise ApprovalGrantError("执行器仍在运行或任务已经结束，不能重入队列")
            fence = db.query(AgentTaskExecutionRecord).filter(
                AgentTaskExecutionRecord.run_id == run_id,
                AgentTaskExecutionRecord.state == execution.state,
                AgentTaskExecutionRecord.execution_count == execution.execution_count,
            )
            if verification_lease_token:
                from app.application.agent_orchestrator.verification_recovery import (
                    _stopped_queue_conditions,
                )

                fence = fence.filter(*_stopped_queue_conditions(expected_execution))
            if (
                fence.update(
                    {AgentTaskExecutionRecord.updated_at: execution.updated_at},
                    synchronize_session=False,
                )
                != 1
            ):
                raise ApprovalGrantError("任务执行权已变化，请刷新后重试")
        record = db.query(AgentRunRecord).filter_by(run_id=run_id).with_for_update().one_or_none()
        if record is None:
            return None
        old_payload = record.payload_json
        run = agent_run_from_dict(json.loads(old_payload))
        if run.status not in {"failed", "blocked"}:
            return run
        if error := safe_continuation_error(run):
            raise ApprovalGrantError(error)
        if verification_lease_token:
            from app.application.agent_orchestrator.task_execution_models import _task_id_of
            from app.application.agent_orchestrator.task_models import tenant_id_of_run
            from app.application.agent_orchestrator.verification_recovery import (
                VERIFICATION_RECOVERY_KEY,
                verification_can_finalize,
            )
            from app.domain.task_lifecycle.control import SessionBook
            from app.infrastructure.auth.agent_mod_scope import validate_actor_context

            recovery = run.metadata.get(VERIFICATION_RECOVERY_KEY) or {}
            now = time.time() if verification_time is None else verification_time
            if (
                execution is None
                or recovery.get("lease_token") != verification_lease_token
                or float(recovery.get("lease_until") or 0) <= now
                or principal_id != run.user_id
                or execution is None
                or (execution.task_id, execution.user_id, execution.tenant_id)
                != (_task_id_of(run), run.user_id, tenant_id_of_run(run))
                or runtime_context
                or authenticated_binding is not None
                or authenticated_actor_binding is not None
                or not verification_can_finalize(run)
                or validate_actor_context(run.metadata.get("runtime_context") or {}) is not None
            ):
                raise ApprovalGrantError("原回执或授权未满足自动最终确认条件")
            # Observation is not effect reconciliation. Even a successful readback
            # cannot clear an outstanding effect, nor renew a login/approval.
            if SessionBook(db).get("agent", tenant_id_of_run(run), run.run_id).get("effects"):
                raise ApprovalGrantError("原任务仍有未结清副作用，核验只能更新观察")
            run.metadata[VERIFICATION_RECOVERY_KEY] = {
                **recovery,
                "status": "queued",
                "lease_until": 0,
                "next_attempt_at": 0,
                "reason_code": "verified_completed_receipts",
            }
        else:
            if unresolved_effects(db, run, clear_confirmed=True):
                raise ApprovalGrantError("任务仍有未确认的业务写入，需要人工核对")
            renew_approval_session(
                run,
                principal_id=principal_id,
                authenticated_binding=authenticated_binding,
                authenticated_actor_binding=authenticated_actor_binding,
                operation="retry",
            )
            run.metadata["runtime_context"] = merge_runtime_context(run, runtime_context)
        if (
            db.query(AgentRunRecord)
            .filter(
                AgentRunRecord.run_id == run_id,
                AgentRunRecord.payload_json == old_payload,
            )
            .update({AgentRunRecord.status: record.status}, synchronize_session=False)
            != 1
        ):
            raise ApprovalGrantError("任务状态已变化，请刷新后重试")
        prepare_safe_continuation(
            run,
            requested_by=principal_id,
            reason="verified_completed_receipts" if verification_lease_token else "explicit_retry",
        )
        runs.save_in_session(db, run, allow_safe_retry=True)
        queue.enqueue_in_session(db, run, requested_by=principal_id, retryable=True)
    return run


def resume_and_enqueue(
    runs: SQLAlchemyAgentRunRepository,
    queue: SQLAlchemyTaskExecutionRepository,
    *,
    run_id: str,
    principal_id: str,
    runtime_context: dict[str, Any],
    authenticated_binding: dict[str, Any] | None = None,
    authenticated_actor_binding: dict[str, Any] | None = None,
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
        if execution is not None and execution.state in {"running", "claimed"}:
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
        if unresolved_effects(db, run, clear_confirmed=True):
            raise ApprovalGrantError("任务仍有未确认的业务写入，需要人工核对")
        renew_approval_session(
            run,
            principal_id=principal_id,
            authenticated_binding=authenticated_binding,
            authenticated_actor_binding=authenticated_actor_binding,
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
            from app.domain.task_lifecycle.adapters import execution_transition_allowed

            if not execution_transition_allowed(str(execution.state), "waiting_approval"):
                raise ApprovalGrantError("任务队列已结束，不能改回暂停")
            execution.state = "waiting_approval"
            execution.updated_at = now
    return run
