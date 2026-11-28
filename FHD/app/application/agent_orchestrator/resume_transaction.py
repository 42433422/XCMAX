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
from app.application.agent_orchestrator.task_execution_models import xiaox_queue_outcome
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_models import TaskControlCommand, tenant_id_of_run
from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord, AgentTaskExecutionRecord
from app.domain.task_lifecycle.adapters import WAITING_STATES


def _verified_xiaox_child_effects(db: Any, run: AgentRun, effects: list[str]) -> set[str]:
    """Settle only an exact delegated step from its current independent SQL receipt."""
    from app.application.agent_orchestrator.result_verification import verified_effect_receipt
    from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore

    metadata = run.metadata.get("xiaox_runtime")
    if run.metadata.get("runtime_type") != "xiaox" or not isinstance(metadata, dict):
        return set()
    try:
        XiaoxBindingStore._validate_goal(run, metadata)
    except XiaoxBindingError:
        return set()
    completed = set()
    for effect in effects:
        parts = effect.split(":")
        if len(parts) != 3 or parts[0] != "child":
            continue
        _, child_id, step_id = parts
        calls = [
            call
            for call in (metadata.get("calls") or {}).values()
            if call.get("child_run_id") == child_id
        ]
        if not calls:
            continue
        record = db.query(AgentRunRecord).filter_by(run_id=child_id).with_for_update().one_or_none()
        child = agent_run_from_dict(json.loads(record.payload_json)) if record is not None else None
        if (
            child is None
            or child.status != "completed"
            or len(child.steps) != 1
            or child.user_id != run.user_id
            or tenant_id_of_run(child) != tenant_id_of_run(run)
            or mod_id_of_run(child) != mod_id_of_run(run)
            or (child.metadata.get("runtime_context") or {}).get("parent_run_id") != run.run_id
        ):
            continue
        step = child.steps[0]
        task_id = (child.metadata.get("task_context") or {}).get("task_id")
        operation = {"tool_id": step.tool_id, "action": step.action, "params": step.params}
        nodes = (child.metadata.get("plan") or {}).get("nodes") or []
        if (
            step.step_id != step_id
            or not task_id
            or len(nodes) != 1
            or nodes[0].get("node_id") != step.node_id
            or {key: nodes[0].get(key) for key in operation} != operation
            or any(
                call.get("child_task_id") != task_id
                or call.get("fingerprint") != canonical_digest(operation)
                or {key: call.get(key) for key in operation} != operation
                for call in calls
            )
            or not verified_effect_receipt(child, step)
        ):
            continue
        completed.add(effect)
    return completed


def unresolved_effects(db: Any, run: AgentRun, *, clear_confirmed: bool = False) -> list[str]:
    """Only a durable successful step receipt can settle an old open effect."""
    from app.application.agent_orchestrator.result_verification import verified_effect_receipt
    from app.application.agent_orchestrator.task_models import tenant_id_of_run
    from app.domain.task_lifecycle.control import SessionBook

    book = SessionBook(db)
    tenant = tenant_id_of_run(run)
    body = book.get("agent", tenant, run.run_id)
    completed = {step.step_id for step in run.steps if verified_effect_receipt(run, step)}
    completed.update(_verified_xiaox_child_effects(db, run, body.get("effects") or []))
    remaining = sorted(set(body.get("effects") or []) - completed)
    if clear_confirmed and not remaining and body.get("effects"):
        body["effects"] = []
        book.put("agent", tenant, run.run_id, body)
    return remaining


def reconcile_xiaox_receipts(
    queue: SQLAlchemyTaskExecutionRepository, run_repository: Any, previous: AgentRun
) -> AgentRun | None:
    """Project verified delegated results without claiming or replaying a worker.

    This restricted reconciliation event is not a general lifecycle edge.
    A stopped parent's original children and frozen goal are independently
    checked, then its run, Task view and unleased waiting queue row commit
    together. Callers cannot supply a desired state or replacement result.
    """
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )
    from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord, AgentTaskRecord
    from app.domain.task_lifecycle.agent_runtime_results import (
        model_unsettled,
        receipt_artifact_failure,
        receipt_settled_failure,
        receipt_verified,
    )
    from app.domain.task_lifecycle.control import SessionBook, remember
    from app.infrastructure.xiaox.binding import (
        XiaoxBinding,
        XiaoxBindingError,
        XiaoxBindingStore,
    )
    from app.infrastructure.xiaox.receipt_projection import (
        project_receipt_state,
        projection_allowed,
    )
    from app.infrastructure.xiaox.receipts import read_call_receipt

    if not isinstance(run_repository, SQLAlchemyAgentRunRepository) or not projection_allowed(
        previous
    ):
        return None
    store = XiaoxBindingStore(run_repository)
    binding = XiaoxBinding(previous)
    store._validate_goal(previous, binding.metadata)
    rows, children = [], {}
    for call_id, call in binding.metadata["calls"].items():
        receipt = read_call_receipt(store, binding, call)
        if receipt != call.get("receipt"):
            return None  # A child changed since the caller's receipt snapshot.
        rows.append({"call_id": call_id, **call})
        if child_id := receipt.get("run_id"):
            child = run_repository.get(child_id)
            if child is None or child.updated_at != receipt.get("child_updated_at"):
                return None
            children[child_id] = child
    previous_result = previous.final_output.get("xiaox_result") or {}
    prior = {str(row.get("call_id")): row for row in previous_result.get("business_receipts") or []}
    quality_recovery = any(receipt_artifact_failure(row) for row in rows) and all(
        receipt_verified(row) or receipt_settled_failure(row) for row in rows
    )
    recovered_writes = [
        row
        for row in rows
        if row.get("read_only") is not True
        and (prior.get(str(row["call_id"])) or {}).get("state")
        in (
            {"waiting_user", "waiting_approval", "running", "unknown"}
            if quality_recovery
            else {"waiting_user", "waiting_approval", "running"}
        )
    ]
    verified_child_recovery = bool(
        (previous.metadata.get("recovery") or {}) == {"state": "manual_reconciliation_required"}
        and previous.metadata.get("non_retryable") is True
        and previous.status
        in (
            {"running", "waiting_user", "unknown", "blocked"}
            if quality_recovery
            else {"running", "waiting_user", "unknown"}
        )
        and not previous.metadata.get("stream_interruption")
        and not model_unsettled(binding.metadata)
        and (quality_recovery or previous_result.get("exit_status") in {"waiting_user", "running"})
        and (
            quality_recovery
            or not any(
                (request.get("result") or {}).get("execution_state") == "unknown"
                for request in (previous.metadata.get("runtime_requests") or {}).values()
            )
        )
        and recovered_writes
        and all(
            receipt_verified(row) or (quality_recovery and receipt_settled_failure(row))
            for row in rows
        )
    )
    projected = project_receipt_state(
        previous, rows, verified_child_recovery=verified_child_recovery
    )
    if projected is None:
        return None
    result = projected.final_output["xiaox_result"]
    if projected.status == "completed" and not (
        result.get("business_completed") is True
        and result.get("verified_operations") is True
        and (result.get("goal_coverage") or {}).get("completed") is True
    ):
        return None
    target, code = xiaox_queue_outcome(result)
    code = code or "xiaox_receipt_projection"
    now = utc_now_iso()
    with queue.transaction() as db, run_repository.transaction(read_only=True) as runs:
        if db.get_bind() is not runs.get_bind():
            raise XiaoxBindingError("durable_storage_required", "父任务与队列不属于同一数据库")
        execution = db.get(AgentTaskExecutionRecord, previous.run_id)
        if execution is not None:
            if (
                (
                    execution.state not in WAITING_STATES
                    and not (
                        verified_child_recovery
                        and quality_recovery
                        and execution.state == "unknown"
                    )
                )
                or execution.lease_owner
                or execution.lease_expires_at
            ):
                return None
            fenced = (
                db.query(AgentTaskExecutionRecord)
                .filter(
                    AgentTaskExecutionRecord.run_id == previous.run_id,
                    AgentTaskExecutionRecord.state == execution.state,
                    AgentTaskExecutionRecord.execution_count == execution.execution_count,
                    AgentTaskExecutionRecord.lease_owner == execution.lease_owner,
                    AgentTaskExecutionRecord.lease_expires_at == execution.lease_expires_at,
                )
                .update(
                    {AgentTaskExecutionRecord.updated_at: execution.updated_at},
                    synchronize_session=False,
                )
            )
            if fenced != 1:
                return None
            book = SessionBook(db)
            body = book.get("agent", str(execution.tenant_id or ""), previous.run_id)
            settled_files = (
                {
                    f"child:{row['child_run_id']}:{children[row['child_run_id']].steps[0].step_id}"
                    for row in rows
                    if receipt_artifact_failure(row)
                }
                if verified_child_recovery and quality_recovery
                else set()
            )
            if set(body.get("effects") or []) - settled_files or (
                execution.last_error_code == "needs_verification" and not settled_files
            ):
                return None
            if settled_files:
                body["effects"] = []
        for child_id, child in children.items():
            record = db.get(AgentRunRecord, child_id)
            current = run_repository._record_to_run(record) if record is not None else None
            if current is None or current.to_dict() != child.to_dict():
                return None
            assert record is not None
            if (
                db.query(AgentRunRecord)
                .filter(
                    AgentRunRecord.run_id == child_id,
                    AgentRunRecord.payload_json == record.payload_json,
                )
                .update({AgentRunRecord.status: record.status}, synchronize_session=False)
                != 1
            ):
                return None
        if verified_child_recovery:
            for row in recovered_writes:
                child_id, task_id = row["child_run_id"], row["child_task_id"]
                child = children[child_id]
                tasks = (
                    db.query(AgentTaskRecord)
                    .filter(
                        AgentTaskRecord.task_id == task_id,
                        AgentTaskRecord.user_id == previous.user_id,
                        AgentTaskRecord.tenant_id == tenant_id_of_run(previous),
                    )
                    .limit(2)
                    .all()
                )
                if (
                    len(tasks) != 1
                    or tasks[0].active_run_id != child_id
                    or tasks[0].root_run_id != previous.run_id
                    or tasks[0].attempt != 1
                    or tasks[0].run_count != 1
                    or (child.status != "completed" and not receipt_artifact_failure(row))
                    or child.metadata.get("non_retryable")
                    or child.metadata.get("recovery")
                ):
                    return None
        if not run_repository.save_if_unchanged_in_session(
            db,
            projected,
            previous,
            allow_verified_xiaox_recovery=verified_child_recovery,
        ):
            return None
        if projected.status != result["execution_state"] and not (
            projected.status == "blocked" and result["execution_state"] in {"unknown", "partial"}
        ):
            raise XiaoxBindingError("evidence_mismatch", "父任务投影未通过宿主结果核验")
        if execution is not None:
            remember(body, at=now, source=str(execution.state), target=target, code=code, actor="")
            book.put("agent", str(execution.tenant_id or ""), previous.run_id, body)
            execution.state = target
            execution.last_error_code = None if target == "succeeded" else code
            execution.updated_at = now
            if target in {"succeeded", "failed"}:
                execution.finished_at = now
    return run_repository.get(previous.run_id)


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
