"""启动对账：收敛被进程中断遗留的 running AgentRun。

后端进程退出（正常退出、崩溃、被强杀）时不会为在途任务补写终态，于是
``agent_runs`` / ``agent_tasks`` 会永久停留在 running，界面显示「进行中」而存储
侧再无任何状态写入（M15）。启动时恢复可证明安全的完整计划；未决副作用保留为
unknown，其余不可恢复状态收敛为 failed，并同步 ``agent_tasks``。

边界（不得越权）：
- 只收敛 planning/running/retrying 等在途状态。``queued`` 属于可恢复的持久队列，
  由 ``task_dispatcher`` 的 claim()/重认领负责，启动对账失败它会破坏队列。
- 服务端仍持有**未过期租约**的 run 交给既有租约+重认领机制，启动对账不改写。
- 桌面单进程（``XCAGI_DESKTOP_MODE``）没有第二个 worker，旧租约可回收；
  只有完成回执完整、剩余步骤仍为低风险幂等的原计划可继续。
- 不推断业务成功、不解除权益或审批门禁；未确认的非幂等调用需人工核对后才能重试。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.sql.elements import ColumnElement

from app.application.agent_orchestrator.run_models import AgentRun, agent_run_from_dict, utc_now_iso
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

INTERRUPTED_ERROR_CODE = "interrupted_by_restart"
INTERRUPTED_MESSAGE = "运行被中断：后端进程在任务结束前退出，已由启动对账标记为失败"
IN_FLIGHT_RUN_STATUSES = ("planning", "running", "retrying")
DEFAULT_STALE_AFTER_SECONDS = 60.0


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except RECOVERABLE_ERRORS:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _stale_cutoff(now: str, stale_after_seconds: float) -> str:
    parsed = _parse_timestamp(now) or datetime.now(UTC)
    window = max(1.0, float(stale_after_seconds))
    return (parsed - timedelta(seconds=window)).isoformat()


def _load_payload(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except RECOVERABLE_ERRORS:
        return {}
    return data if isinstance(data, dict) else {}


def _desktop_single_process() -> bool:
    raw = os.environ.get("XCAGI_DESKTOP_MODE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _remember_queue_recovery(db: Any, execution: Any, target: str, now: str) -> None:
    from app.domain.task_lifecycle.control import SessionBook, remember

    book = SessionBook(db)
    tenant = str(execution.tenant_id or "")
    body = book.get("agent", tenant, execution.run_id)
    remember(
        body,
        at=now,
        source=str(execution.state),
        target=target,
        code=INTERRUPTED_ERROR_CODE,
        actor="startup",
    )
    body["history"][-1]["execution_count"] = int(execution.execution_count or 0)
    book.put("agent", tenant, execution.run_id, body)


def _parked_xiaox_parent(payload: dict[str, Any], execution: Any) -> bool:
    """Recognize an unleased original parent waiting on its durable child ledger."""
    from app.application.agent_orchestrator.task_models import task_from_run
    from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
    from app.infrastructure.xiaox.receipt_projection import projection_allowed

    if (
        execution is None
        or execution.state not in {"waiting_approval", "waiting_input", "waiting_auth"}
        or execution.lease_owner
        or execution.lease_expires_at
        or execution.heartbeat_at
        or execution.finished_at
        or execution.last_error_code == "needs_verification"
    ):
        return False
    run = agent_run_from_dict(payload)
    task = task_from_run(run)
    binding = run.metadata.get("xiaox_runtime") or {}
    result = run.final_output.get("xiaox_result") or {}
    if (
        (execution.run_id, execution.user_id, execution.task_id, execution.tenant_id or "")
        != (run.run_id, run.user_id, task.task_id, task.tenant_id)
        or run.intent != "xiaox.runtime"
        or not projection_allowed(run)
        or binding.get("coordinator_active") is not False
        or run.metadata.get("non_retryable")
        or (run.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
        or result.get("reconciliation_required")
        or result.get("execution_state") not in {"running", "waiting_user"}
        or result.get("exit_status") not in {"running", "waiting_user", "continuation_pending"}
    ):
        return False
    try:
        XiaoxBindingStore._validate_goal(run, binding)
    except XiaoxBindingError:
        return False
    return True


def _approved_unsubmitted_step(db: Any, run: AgentRun) -> str:
    """Recognize a committed queue approval that never reached its tool."""
    from app.application.agent_orchestrator.approval_grant import _params_hash
    from app.db.models.agent_approval import AgentApprovalConsumption

    dispatch = run.metadata.get("dispatch")
    receipt = run.metadata.get("approval_receipt")
    if not isinstance(dispatch, dict) or not isinstance(receipt, dict):
        return ""
    step_id = dispatch.get("approved_step_id")
    step = next((step for step in run.steps if step.step_id == step_id), None)
    if (
        step is None
        or step.status != "pending"
        or step.output
        or step.started_at
        or step.attempt_count
        or any(call.step_id == step_id for call in run.tool_calls)
        or (receipt.get("step_id"), receipt.get("tool_id"), receipt.get("action"))
        != (step_id, step.tool_id, step.action)
        or receipt.get("params_sha256") != _params_hash(step)
    ):
        return ""
    if receipt.get("queue_approval") == "workspace_claim":
        from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict

        plan = plan_from_dict(run.metadata.get("plan"))
        return (
            str(step_id)
            if (
                receipt.get("approval_request_id")
                and receipt.get("approved_by")
                and (step.tool_id, step.action) == ("elt_import", "execute")
                and plan is not None
                and plan.metadata.get("durable_elt_batch") is True
                and receipt.get("plan_sha256") == plan_fingerprint(plan)
            )
            else ""
        )
    grant_id = receipt.get("grant_id")
    if not isinstance(grant_id, str) or not grant_id or receipt.get("approved_by") != run.user_id:
        return ""
    consumed = db.get(AgentApprovalConsumption, grant_id)
    return (
        str(step_id)
        if consumed and (consumed.run_id, consumed.step_id) == (run.run_id, step_id)
        else ""
    )


def _owns_current_task(db: Any, repository: Any, run: AgentRun) -> bool:
    """Fence the active attempt or an originally registered same-task handoff."""
    from app.application.agent_orchestrator.run_audit_scope import _result_scope
    from app.application.agent_orchestrator.task_context import task_context_of
    from app.application.agent_orchestrator.task_models import task_from_run
    from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord, AgentTaskRecord

    task = task_from_run(run)
    observed = (
        db.query(AgentTaskRecord)
        .filter_by(tenant_id=task.tenant_id, user_id=task.user_id, task_id=task.task_id)
        .populate_existing()
        .one_or_none()
    )
    target = observed.active_run_id if observed is not None else run.run_id
    live_states = {"planning", "queued", "running", "retrying", "waiting_user"}
    seen: set[str] = set()
    child = run
    for _ in range(16):
        command = (
            db.query(AgentTaskCommandRecord)
            .filter_by(run_id=child.run_id)
            .order_by(
                AgentTaskCommandRecord.created_at.desc(), AgentTaskCommandRecord.command_id.desc()
            )
            .first()
        )
        if (
            child.run_id in seen
            or child.status not in live_states
            or child.metadata.get("non_retryable")
            or (child.metadata.get("control") or {}).get("state") in {"paused", "cancelled"}
            or (child.metadata.get("xiaox_runtime") or {}).get("close_reason")
            in {"paused", "cancelled"}
            or (child.metadata.get("recovery") or {}).get("state")
            == "manual_reconciliation_required"
            or (
                command is not None
                and command.status in {"requested", "applied"}
                and command.action in {"pause", "cancel"}
            )
        ):
            return False
        seen.add(child.run_id)
        if child.run_id == target:
            # Follow the ordinary repository's run -> Task lock order. A new
            # attempt admitted while ancestors were read invalidates this chain.
            current = repository._lock_task_record(db, task)
            return (
                current.active_run_id == child.run_id
                and current.attempt == task_from_run(child).attempt
                and current.status in live_states
            )
        context = child.metadata.get("runtime_context") or {}
        child_task = task_context_of(child)
        parent_id = str(context.get("parent_run_id") or "")
        scope = _result_scope(child)
        if (
            not parent_id
            or scope is None
            or child_task.get("parent_run_id") != parent_id
            or child_task.get("task_id") != task.task_id
            or context.get("task_id") != task.task_id
            or context.get("parent_task_id") != task.task_id
        ):
            return False
        record = (
            db.query(AgentRunRecord).filter_by(run_id=parent_id).populate_existing().one_or_none()
        )
        if record is None:
            return False
        raw = record.payload_json
        if (
            db.query(AgentRunRecord)
            .filter_by(run_id=parent_id, payload_json=raw)
            .update({AgentRunRecord.status: record.status}, synchronize_session=False)
            != 1
        ):
            return False
        parent = agent_run_from_dict(_load_payload(raw))
        original = parent.metadata.get("runtime_context") or {}
        receipt = (parent.metadata.get("child_results") or {}).get(child.run_id)
        if (
            scope != _result_scope(parent)
            or task_context_of(parent).get("task_id") != task.task_id
            or not isinstance(receipt, dict)
            or not context.get("employee_id")
            or any(
                receipt.get(key) != value
                for key, value in {
                    "parent_run_id": parent.run_id,
                    "parent_task_id": task.task_id,
                    "tenant_id": scope[1],
                    "user_id": scope[0],
                    "mod_id": scope[2],
                    "employee_id": context.get("employee_id"),
                }.items()
            )
            or any(
                context.get(key) != original.get(key)
                for key in (
                    "_actor_authorization",
                    "_mod_authorization",
                    "_credential_authorization",
                    "workspace_id",
                    "workspace_path",
                    "root_run_id",
                    "user_id",
                )
            )
        ):
            return False
        child = parent
    return False


def reconcile_stale_running_runs(
    *,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    now: str | None = None,
) -> int:
    """恢复可证明安全的原计划余步，其余中断任务保护停机；返回收敛条数。"""
    from app.application.agent_orchestrator.elt_checkpoint_recovery import checkpoint_step
    from app.application.agent_orchestrator.resume_transaction import unresolved_effects
    from app.application.agent_orchestrator.run_lifecycle import (
        prepare_safe_continuation,
        safe_continuation_error,
    )
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_runtime.verification_budget import JOB_KEY
    from app.domain.task_lifecycle.machine import DEFAULT_MAX_ATTEMPTS
    from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
    from app.infrastructure.xiaox.queued_runtime import recover_abandoned_goal_verification

    repository = get_agent_run_repository()
    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return 0
    queue = SQLAlchemyTaskExecutionRepository(session_factory=repository._session_factory)
    queue._ensure_schema()

    current = str(now or utc_now_iso())
    desktop = _desktop_single_process()
    reconciled = 0
    # A former synchronous entry has no queue lease to reclaim. Only an expired
    # original grant can be parked for the existing independent-review scanner.
    # Read/authority checks run outside the reconciliation write transaction.
    with repository.transaction(read_only=True) as db:
        from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord

        direct_query = db.query(AgentRunRecord).filter(
            AgentRunRecord.status.in_(IN_FLIGHT_RUN_STATUSES),
            AgentRunRecord.intent == "xiaox.runtime",
        )
        if not desktop:
            direct_query = direct_query.filter(
                AgentRunRecord.updated_at <= _stale_cutoff(current, stale_after_seconds)
            )
        direct_ids = [
            record.run_id
            for record in direct_query.all()
            if db.get(AgentTaskExecutionRecord, record.run_id) is None
            and ((_load_payload(record.payload_json).get("metadata") or {}).get(JOB_KEY) or {}).get(
                "state"
            )
            in {"running", "pending", "needs_work", "verified", "blocked"}
        ]
    for run_id in direct_ids:
        try:
            if recover_abandoned_goal_verification(
                XiaoxBindingStore(repository),
                run_id,
                now=(_parse_timestamp(current) or datetime.now(UTC)).timestamp(),
            ):
                reconciled += 1
        except XiaoxBindingError:
            pass  # The original control, authorization and uncertain-effect guards remain closed.
    with repository.transaction() as db:
        from app.db.models.agent import (
            AgentRunRecord,
            AgentTaskExecutionRecord,
        )

        filters: list[ColumnElement[bool]] = [AgentRunRecord.status.in_(IN_FLIGHT_RUN_STATUSES)]
        if not desktop:
            filters.append(AgentRunRecord.updated_at <= _stale_cutoff(current, stale_after_seconds))
        records = db.query(AgentRunRecord).filter(*filters).all()
        for record in records:
            execution = db.get(AgentTaskExecutionRecord, record.run_id)
            if _parked_xiaox_parent(_load_payload(record.payload_json), execution):
                # The coordinator has exited intentionally; receipt reconciliation
                # owns the next transition, independently of this process restart.
                continue
            if (
                not desktop
                and execution is not None
                and execution.state in {"running", "claimed"}
                and str(execution.lease_expires_at or "") > current
            ):
                # 服务端租约仍有效：交由既有重认领机制处理，启动对账不越权改写。
                continue
            payload = _load_payload(record.payload_json)
            metadata = payload.get("metadata") or {}
            verification = metadata.get(JOB_KEY) or {}
            runtime = metadata.get("xiaox_runtime") or {}
            if (
                metadata.get("runtime_type") == "xiaox"
                and verification.get("state")
                in {"running", "pending", "needs_work", "verified", "blocked"}
                and verification.get("generation") == runtime.get("generation")
                and runtime.get("coordinator_active")
                and (
                    (execution is not None and execution.state in {"queued", "running", "claimed"})
                    or (
                        execution is None
                        and float(runtime.get("expires_at") or 0)
                        > (_parse_timestamp(current) or datetime.now(UTC)).timestamp()
                    )
                )
            ):
                # The original queue must fence/reclaim this owner before its
                # settled review can resume. Generic plan recovery cannot judge
                # an SDK request or erase its independent verification checkpoint.
                continue
            if execution is not None and execution.state in {"queued", "running", "claimed"}:
                # Fence the observed owner/count before touching either projection.
                # A replacement worker may have claimed it after our initial read.
                fence = db.query(AgentTaskExecutionRecord).filter(
                    AgentTaskExecutionRecord.run_id == record.run_id,
                    AgentTaskExecutionRecord.state == execution.state,
                    AgentTaskExecutionRecord.execution_count == execution.execution_count,
                    AgentTaskExecutionRecord.lease_owner == execution.lease_owner,
                )
                if not desktop and execution.state in {"running", "claimed"}:
                    fence = fence.filter(AgentTaskExecutionRecord.lease_expires_at <= current)
                if (
                    fence.update(
                        {AgentTaskExecutionRecord.updated_at: execution.updated_at},
                        synchronize_session=False,
                    )
                    != 1
                ):
                    continue
            if (
                db.query(AgentRunRecord)
                .filter(
                    AgentRunRecord.run_id == record.run_id,
                    AgentRunRecord.payload_json == record.payload_json,
                )
                .update({AgentRunRecord.status: record.status}, synchronize_session=False)
                != 1
            ):
                continue
            payload = _load_payload(record.payload_json)
            interrupted = agent_run_from_dict(payload)
            owns_current_task = _owns_current_task(db, repository, interrupted)
            unknown_effects = unresolved_effects(db, interrupted)
            checkpoint = checkpoint_step(interrupted) if execution is not None else None
            checkpoint_id = (
                checkpoint.step_id
                if checkpoint is not None and set(unknown_effects) <= {checkpoint.step_id}
                else ""
            )
            approved_step = (
                _approved_unsubmitted_step(db, interrupted)
                if not unknown_effects
                and execution is not None
                and execution.state in {"queued", "claimed", "running"}
                else ""
            )
            if (
                owns_current_task
                and (not unknown_effects or checkpoint_id)
                and not safe_continuation_error(
                    interrupted,
                    approved_unsubmitted_step_id=approved_step,
                    elt_checkpoint_step_id=checkpoint_id,
                )
                and (execution is None or execution.state in {"queued", "claimed", "running"})
                and (
                    execution is None or int(execution.execution_count or 0) < DEFAULT_MAX_ATTEMPTS
                )
            ):
                unresolved_effects(db, interrupted, clear_confirmed=True)
                prepare_safe_continuation(
                    interrupted,
                    requested_by="startup",
                    reason="process_restart",
                    approved_unsubmitted_step_id=approved_step,
                    elt_checkpoint_step_id=checkpoint_id,
                )
                if execution is not None:
                    _remember_queue_recovery(db, execution, "queued", current)
                    execution.recovery_count = int(execution.recovery_count or 0) + 1
                    execution.state = "queued"
                    execution.lease_owner = execution.lease_expires_at = execution.heartbeat_at = (
                        None
                    )
                    execution.finished_at = None
                repository.save_in_session(db, interrupted)
                queue.enqueue_in_session(db, interrupted, requested_by="startup")
                reconciled += 1
                continue
            payload["updated_at"] = current
            metadata = payload.get("metadata")
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            metadata["interrupted"] = {
                "error_code": INTERRUPTED_ERROR_CODE,
                "reconciled_at": current,
                "previous_status": str(record.status or ""),
            }
            if not owns_current_task:
                metadata["interrupted"]["reason"] = "task_ownership_or_control_changed"
            interrupted = agent_run_from_dict(payload)
            uncertain_steps = []
            for step in interrupted.steps:
                if step.status != "running":
                    continue
                spec = get_tool_action_spec(step.tool_id, step.action)
                if not (step.idempotent and spec is not None and spec.idempotent):
                    uncertain_steps.append(step.step_id)
            if (
                unknown_effects
                or uncertain_steps
                or metadata.get("trace_mode")
                in {
                    "legacy_planner_run",
                    "legacy_planner_run_with_tools",
                }
            ):
                metadata["non_retryable"] = True
                recovery = metadata.get("recovery")
                metadata["recovery"] = {
                    **(recovery if isinstance(recovery, dict) else {}),
                    "state": "manual_reconciliation_required",
                    "error_code": INTERRUPTED_ERROR_CODE,
                    "step_ids": sorted(set(uncertain_steps) | set(unknown_effects)),
                }
            payload["metadata"] = metadata
            status = "unknown" if metadata.get("non_retryable") else "failed"
            payload["status"] = status
            payload["error"] = str(payload.get("error") or "") or (
                "运行被中断：执行结果未知，已保留原任务待核对，禁止自动重放"
                if status == "unknown"
                else INTERRUPTED_MESSAGE
            )
            interrupted = agent_run_from_dict(payload)
            interrupted.add_event(
                "run.interrupted",
                interrupted.error,
                {**metadata["interrupted"], "status": status},
            )
            # The ordinary repository locks the shared Task and retains its
            # newest attempt. A stale run must not rewrite a newer Task view.
            repository.save_in_session(db, interrupted)
            if (
                (desktop or not owns_current_task)
                and execution is not None
                and str(execution.state or "") in {"queued", "claimed", "running"}
            ):
                # Park dead desktop claims, obsolete attempts and stopped
                # descendants before the dispatcher can reclaim them.
                _remember_queue_recovery(db, execution, status, current)
                execution.state = status
                execution.last_error_code = (
                    "needs_verification" if status == "unknown" else INTERRUPTED_ERROR_CODE
                )
                execution.lease_owner = execution.lease_expires_at = execution.heartbeat_at = None
                # Match the queue's fenced unknown transition: it is parked,
                # not a finished business result or a surviving worker lease.
                execution.finished_at = None if status == "unknown" else current
                execution.updated_at = current
            reconciled += 1
    if reconciled:
        logger.warning(
            "agent run startup reconciliation: %s interrupted run(s) reconciled (error_code=%s desktop=%s)",
            reconciled,
            INTERRUPTED_ERROR_CODE,
            desktop,
        )
    return reconciled


__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "IN_FLIGHT_RUN_STATUSES",
    "INTERRUPTED_ERROR_CODE",
    "INTERRUPTED_MESSAGE",
    "reconcile_stale_running_runs",
]
