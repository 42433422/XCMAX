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


def _task_identity(payload: dict[str, Any], run_id: str) -> tuple[str, str]:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    context = metadata.get("task_context")
    context = context if isinstance(context, dict) else {}
    runtime = metadata.get("runtime_context")
    runtime = runtime if isinstance(runtime, dict) else {}
    return str(context.get("task_id") or run_id), str(runtime.get("tenant_id") or "")


def _desktop_single_process() -> bool:
    raw = os.environ.get("XCAGI_DESKTOP_MODE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
            AgentTaskRecord,
        )

        filters: list[ColumnElement[bool]] = [AgentRunRecord.status.in_(IN_FLIGHT_RUN_STATUSES)]
        if not desktop:
            filters.append(AgentRunRecord.updated_at <= _stale_cutoff(current, stale_after_seconds))
        records = db.query(AgentRunRecord).filter(*filters).all()
        for record in records:
            execution = db.get(AgentTaskExecutionRecord, record.run_id)
            if execution is not None and execution.state == "waiting_approval":
                payload = _load_payload(record.payload_json)
                if (payload.get("metadata") or {}).get("runtime_type") == "xiaox":
                    # An approved child can finish after the model turn. The
                    # original parent is parked on its durable queue receipt,
                    # not owned by the exited process.
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
                (not unknown_effects or checkpoint_id)
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
            record.status = status
            record.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
            record.updated_at = current
            task_id, tenant_id = _task_identity(payload, record.run_id)
            task_record = (
                db.query(AgentTaskRecord)
                .filter(
                    AgentTaskRecord.tenant_id == tenant_id,
                    AgentTaskRecord.user_id == record.user_id,
                    AgentTaskRecord.task_id == task_id,
                )
                .one_or_none()
            )
            if task_record is not None and str(task_record.status or "") in IN_FLIGHT_RUN_STATUSES:
                task_record.status = status
                task_record.attention_state = status
                task_record.updated_at = current
            if (
                desktop
                and execution is not None
                and str(execution.state or "") in {"queued", "claimed", "running"}
            ):
                # 桌面没有第二个 worker。先关掉执行行，dispatcher 不能把这条租约再认领。
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
