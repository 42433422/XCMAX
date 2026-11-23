"""Re-read a stopped task's evidence without dispatching its business actions."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from typing import Any

from app.application.agent_orchestrator.result_verification import (
    restore_verified_artifacts,
    summarize_verification,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.runtime_context import (
    RuntimeContextOwnershipError,
)
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_models import _task_id_of
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.domain.task_lifecycle.results import execution_result_error
from app.utils.operational_errors import RECOVERABLE_ERRORS

VERIFICATION_RECOVERY_KEY = "verification_recovery"
_KEY = VERIFICATION_RECOVERY_KEY
_LEASE_SECONDS = 120.0
_DONE = {"queued", "observed", "not_recoverable"}
logger = logging.getLogger(__name__)


class VerificationRecoveryError(ValueError):
    """The original task cannot safely accept a new verification observation."""

    def __init__(self, message: str, *, code: str = "verification_receipt_or_queue_changed"):
        super().__init__(message)
        self.code = code


def verification_report(run: AgentRun) -> dict[str, Any]:
    """An old run without a server contract has no independent verification."""
    if not any(call.metadata.get("verification_contract") for call in run.tool_calls):
        return {"status": "not_verified", "accepted": False, "steps": []}
    return summarize_verification(run)


def _read_context(run: AgentRun, current: dict[str, Any] | None) -> dict[str, Any]:
    context = copy.deepcopy(run.metadata.get("runtime_context") or {})
    if current is None:
        return context
    original_mod = str(
        (context.get("_mod_authorization") or {}).get("mod_id")
        or context.get("mod_id")
        or context.get("active_mod_id")
        or ""
    )
    current_mod = str(
        (current.get("_mod_authorization") or {}).get("mod_id")
        or current.get("mod_id")
        or current.get("active_mod_id")
        or ""
    )
    if (
        str(current.get("user_id") or "") != run.user_id
        or str(current.get("tenant_id") or "") != tenant_id_of_run(run)
        or original_mod != current_mod
    ):
        raise RuntimeContextOwnershipError("核验不能更改原任务的账户、租户或 Mod")
    # The authenticated HTTP principal may have a renewed read session. Use it
    # only for this observation; the original execution identity stays immutable.
    for key in ("_actor_authorization", "_mod_authorization"):
        context.pop(key, None)
        if isinstance(current.get(key), dict):
            context[key] = copy.deepcopy(current[key])
    return context


def _stopped_queue_proof(
    repository: AgentRunRepository, run: AgentRun, *, allow_parked: bool = False
) -> tuple[Any, Any]:
    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
        get_agent_run_repository,
    )
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
        get_task_execution_repository,
    )
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )

    queue: Any
    if isinstance(repository, SQLAlchemyAgentRunRepository):
        queue = SQLAlchemyTaskExecutionRepository(
            session_factory=repository._session_factory, auto_create=False
        )
    elif (
        isinstance(repository, InMemoryAgentRunRepository)
        and repository is get_agent_run_repository()
    ):
        queue = get_task_execution_repository()
        if not isinstance(queue, InMemoryTaskExecutionRepository):
            raise VerificationRecoveryError("核验缺少与原任务配对的执行队列")
    else:
        raise VerificationRecoveryError("核验缺少原执行租约的权威终止记录")
    execution = queue.get(run.run_id)
    if (
        execution is None
        or (execution.run_id, execution.task_id, execution.user_id, execution.tenant_id)
        != (run.run_id, _task_id_of(run), run.user_id, tenant_id_of_run(run))
        or execution.state
        not in ({"unknown", "failed", "blocked"} if allow_parked else {"unknown", "failed"})
        or (not allow_parked and execution.last_error_code != "needs_verification")
        or execution.lease_owner
        or execution.lease_expires_at
        or (execution.state == "failed" and not execution.finished_at)
        or (execution.state in {"unknown", "blocked"} and execution.finished_at)
    ):
        raise VerificationRecoveryError("执行租约尚未确认终止，不能接管核验")
    return queue, execution


def _stopped_queue_conditions(execution: Any) -> tuple[Any, ...]:
    from sqlalchemy import or_

    from app.db.models.agent import AgentTaskExecutionRecord as Record

    return (
        Record.run_id == execution.run_id,
        Record.task_id == execution.task_id,
        Record.user_id == execution.user_id,
        Record.tenant_id == execution.tenant_id,
        Record.state == execution.state,
        Record.last_error_code == execution.last_error_code
        if execution.last_error_code
        else or_(Record.last_error_code.is_(None), Record.last_error_code == ""),
        Record.execution_count == execution.execution_count,
        Record.updated_at == execution.updated_at,
        Record.finished_at == execution.finished_at
        if execution.finished_at
        else or_(Record.finished_at.is_(None), Record.finished_at == ""),
        or_(Record.lease_owner.is_(None), Record.lease_owner == ""),
        or_(Record.lease_expires_at.is_(None), Record.lease_expires_at == ""),
    )


def _save_observation(
    repository: AgentRunRepository,
    run: AgentRun,
    previous: AgentRun,
    proof: tuple[Any, Any] | None,
) -> bool:
    if proof is None:
        return bool(repository.save_if_unchanged(run, previous))
    queue, execution = proof
    if isinstance(repository, SQLAlchemyAgentRunRepository):
        from app.db.models.agent import AgentTaskExecutionRecord as Record

        # Recheck and fence the authoritative queue row in the same transaction
        # as the original run CAS. No clock-based guess can evict a live owner.
        with repository.transaction() as db:
            matched = (
                db.query(Record)
                .filter(*_stopped_queue_conditions(execution))
                .update({Record.updated_at: execution.updated_at}, synchronize_session=False)
            )
            return bool(matched == 1 and repository.save_if_unchanged_in_session(db, run, previous))
    with queue._lock:
        latest = queue.get(previous.run_id)
        return bool(
            latest is not None
            and latest.to_dict() == execution.to_dict()
            and repository.save_if_unchanged(run, previous)
        )


def reverify_run(
    repository: AgentRunRepository,
    run_id: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    require_stopped_queue: bool = False,
) -> AgentRun | None:
    """Persist only observations with the existing run CAS and original receipts.

    Business dispatch, billing, approval renewal and lifecycle transitions remain
    with the original task runtime. A verifier may not clear an unknown effect.
    """
    previous = repository.get(run_id)
    if previous is None:
        return None
    if previous.status not in {"blocked", "failed", "running"}:
        raise VerificationRecoveryError("只有已停止的失败或待核验任务可以重新核验")
    context = _read_context(previous, runtime_context)
    run = copy.deepcopy(previous)
    steps = {step.step_id: step for step in run.steps}
    latest = {call.step_id: call for call in run.tool_calls}
    contracted = [call for call in latest.values() if call.metadata.get("verification_contract")]
    if not contracted:
        raise VerificationRecoveryError(
            "原任务没有冻结的核验契约，不能补造核验证据", code="verification_contract_missing"
        )
    if any(call.step_id not in steps for call in contracted):
        raise VerificationRecoveryError(
            "原执行回执缺少对应步骤，不能推定成功", code="verification_step_missing"
        )
    # Independent parallel steps may have failed while another completed action
    # awaits readback. Keep failed/unknown receipts intact; observing the completed
    # action must not require replaying or accepting those other steps.
    from app.application.agent_orchestrator.verification_cognition import plan_admission_receipt
    from app.application.agent_orchestrator.verification_kellai import can_observe_kellai_delivery

    calls = [
        call
        for call in contracted
        if (
            steps[call.step_id].status == call.status == "completed"
            and call.output.get("success") is True
            and (
                not execution_result_error(call.output)
                or (
                    (call.tool_id, call.action) == ("enterprise_cognition", "plan")
                    and plan_admission_receipt(call.output)
                )
            )
        )
        or can_observe_kellai_delivery(run, steps[call.step_id], call)
    ]
    if not calls:
        raise VerificationRecoveryError(
            "原任务没有可重新核验的完整成功回执", code="verification_receipt_not_observable"
        )
    unknown_delivery = any(
        can_observe_kellai_delivery(run, steps[call.step_id], call) for call in calls
    )
    proof = (
        _stopped_queue_proof(
            repository, previous, allow_parked=require_stopped_queue or unknown_delivery
        )
        if require_stopped_queue
        or unknown_delivery
        or previous.status == "running"
        or (previous.metadata.get("execution") or {}).get("state") == "active"
        else None
    )
    for call in calls:
        step = steps[call.step_id]
        verify_step_result(
            run=run,
            step=step,
            call=call,
            context={
                **context,
                "run_id": run.run_id,
                "step_id": step.step_id,
                "node_id": step.node_id,
                **task_execution_context(run, step),
            },
        )
        restore_verified_artifacts(run, step, call)
    report = verification_report(run)
    if proof is not None and (
        previous.status == "running"
        or (previous.metadata.get("execution") or {}).get("state") == "active"
    ):
        run.status = "blocked"
        run.metadata["execution"] = {**(run.metadata.get("execution") or {}), "state": "idle"}
    run.metadata["verification"] = report
    run.final_output["verification"] = copy.deepcopy(report)
    run.add_event(
        "verification.rechecked",
        "已重新读取原任务结果，未重复执行业务动作",
        {
            "status": report["status"],
            "accepted": report["accepted"],
            "call_ids": [call.call_id for call in calls],
        },
    )
    if not _save_observation(repository, run, previous, proof):
        raise VerificationRecoveryError("核验期间原任务已变化，请刷新后核对")
    return repository.get(run_id)


def verification_can_finalize(run: AgentRun) -> bool:
    """Finalization may revisit the graph only when every action is already done."""
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    return bool(
        run.steps
        and verification_report(run).get("accepted") is True
        and all(step.status in {"completed", "skipped"} for step in run.steps)
        and all(
            not execution_result_error(step.output)
            for step in run.steps
            if step.status == "completed"
        )
        and not safe_continuation_error(run)
    )


def _observed(report: dict[str, Any]) -> bool:
    return bool(report.get("steps")) and all(
        item.get("status") in {"verified", "not_required"}
        or item.get("code") == "original_delivery_observed_execution_unsettled"
        for item in report["steps"]
    )


def _eligible(run, now: float) -> bool:
    from app.application.agent_orchestrator.result_verification import PROTOCOL

    state = run.metadata.get(_KEY) or {}
    return bool(
        run.status in {"blocked", "failed", "running"}
        and (run.metadata.get("verification") or {}).get("protocol") == PROTOCOL
        and state.get("status") not in _DONE
        and float(state.get("next_attempt_at") or 0) <= now
        and float(state.get("lease_until") or 0) <= now
    )


def _candidates(repository, now: float, limit: int):
    """Filter due original rows before LIMIT, including recovery after startup."""
    from sqlalchemy import JSON, Float, and_, case, cast, func, or_
    from sqlalchemy.sql.elements import ColumnElement

    from app.application.agent_orchestrator.result_verification import PROTOCOL
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.db.models.agent import AgentRunRecord as Run
    from app.db.models.agent import AgentTaskExecutionRecord as Execution

    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        # Automatic recovery requires the durable, paired run/queue transaction.
        return []
    repository._ensure_schema()
    SQLAlchemyTaskExecutionRepository(session_factory=repository._session_factory)._ensure_schema()
    with repository._session_scope(read_only=True) as db:
        column = Run.payload_json
        dialect = db.get_bind().dialect.name
        payload: ColumnElement[Any]
        if dialect == "sqlite":
            payload = case((func.json_valid(column) == 1, column), else_="{}")

            def field(*path):
                return func.json_extract(payload, "$." + ".".join(path))

        elif dialect == "postgresql":
            payload = cast(
                case((func.pg_input_is_valid(column, "jsonb"), column), else_="{}"), JSON
            )

            def field(*path):
                value = func.json_extract_path_text(payload, *path)
                return (
                    cast(value, Float) if path[-1] in {"next_attempt_at", "lease_until"} else value
                )

        else:
            return []
        rows = (
            db.query(Run)
            .join(Execution, Execution.run_id == Run.run_id)
            .filter(
                Run.status.in_(("blocked", "failed", "running")),
                Execution.state.in_(("blocked", "failed", "unknown")),
                Execution.user_id == Run.user_id,
                Execution.tenant_id
                == func.coalesce(field("metadata", "runtime_context", "tenant_id"), ""),
                Execution.task_id
                == func.coalesce(
                    func.nullif(field("metadata", "task_context", "task_id"), ""), Run.run_id
                ),
                func.coalesce(Execution.lease_owner, "") == "",
                func.coalesce(Execution.lease_expires_at, "") == "",
                or_(
                    and_(
                        Execution.state == "failed", func.coalesce(Execution.finished_at, "") != ""
                    ),
                    and_(
                        Execution.state.in_(("blocked", "unknown")),
                        func.coalesce(Execution.finished_at, "") == "",
                    ),
                ),
                field("metadata", "verification", "protocol") == PROTOCOL,
                func.coalesce(field("metadata", _KEY, "status"), "").notin_(_DONE),
                func.coalesce(field("metadata", _KEY, "next_attempt_at"), 0) <= now,
                func.coalesce(field("metadata", _KEY, "lease_until"), 0) <= now,
            )
            .order_by(Run.updated_at.asc(), Run.run_id.asc())
            .limit(limit)
        )
        return [
            run
            for row in rows
            if (run := repository._record_to_run(row)) is not None and _eligible(run, now)
        ]


def recover_stopped_verification(
    run_id: str, *, repository=None, now: float | None = None
) -> dict[str, Any] | None:
    """Only read original facts; an unknown queue/effect can never be reopened."""
    from app.application.agent_orchestrator.approval_grant import ApprovalGrantError
    from app.application.agent_orchestrator.resume_transaction import retry_and_enqueue
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    repository = repository or get_agent_run_repository()
    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return None
    current_time = time.time() if now is None else float(now)
    try:
        run = repository.get(run_id)
        if run is None or not _eligible(run, current_time):
            return None
        proof = _stopped_queue_proof(repository, run, allow_parked=True)
        previous = copy.deepcopy(run)
        state = dict(run.metadata.get(_KEY) or {})
        attempt = max(0, int(state.get("attempt") or 0)) + 1
        token = uuid.uuid4().hex
        run.metadata[_KEY] = {
            **state,
            "status": "observing",
            "attempt": attempt,
            "lease_token": token,
            "lease_until": current_time + _LEASE_SECONDS,
        }
        if not _save_observation(repository, run, previous, proof):
            return None
        result = {"status": "pending", "reason_code": "verification_authorization_unavailable"}
        if validate_actor_context(run.metadata.get("runtime_context") or {}) is None:
            try:
                run = reverify_run(repository, run_id, require_stopped_queue=True)
                if run is None:
                    return None
                report = verification_report(run)
                result = {
                    "status": "observed" if report.get("accepted") else "pending",
                    "reason_code": "verified_receipts_only"
                    if report.get("accepted")
                    else "evidence_pending",
                }
                if _observed(report):
                    result = {"status": "observed", "reason_code": "original_receipts_observed"}
                if verification_can_finalize(run):
                    try:
                        finalized = retry_and_enqueue(
                            repository,
                            run_id=run_id,
                            principal_id=run.user_id,
                            runtime_context={},
                            verification_lease_token=token,
                            expected_execution=proof[1],
                            verification_time=now,
                        )
                        if finalized is not None and finalized.status == "queued":
                            return {
                                "status": "queued",
                                "reason_code": "verified_completed_receipts",
                            }
                    except ApprovalGrantError:
                        # A read may confirm a fact without granting authority to
                        # clear an unknown queue/effect or restart a changed task.
                        result["reason_code"] = "verification_finalization_blocked"
            except VerificationRecoveryError as exc:
                result = {
                    "status": (
                        "not_recoverable"
                        if exc.code
                        in {
                            "verification_contract_missing",
                            "verification_step_missing",
                            "verification_receipt_not_observable",
                        }
                        else "pending"
                    ),
                    "reason_code": exc.code,
                }
        current = repository.get(run_id)
        if current is None or (current.metadata.get(_KEY) or {}).get("lease_token") != token:
            return result
        if (
            result["reason_code"]
            not in {
                "verification_authorization_unavailable",
                "verification_receipt_or_queue_changed",
            }
            and result["status"] != "not_recoverable"
        ):
            # A competing valid read can supersede our verdict before the retry
            # transaction. Its retained report determines whether to keep polling.
            result["status"] = "observed" if _observed(verification_report(current)) else "pending"
        previous = copy.deepcopy(current)
        current.metadata[_KEY] = {
            **result,
            "attempt": attempt,
            "lease_until": 0,
            "next_attempt_at": (
                current_time + min(300, 5 * 2 ** min(attempt, 6))
                if result["status"] == "pending"
                else 0
            ),
        }
        # The queue proof is the one acquired before the observation, not a new
        # snapshot that could silently accept a different worker/control result.
        if not _save_observation(repository, current, previous, proof):
            return {"status": "pending", "reason_code": "verification_queue_changed"}
        return result
    except RECOVERABLE_ERRORS:
        logger.warning(
            "Original verification recovery remains pending run=%s", run_id, exc_info=True
        )
        return {"status": "pending", "reason_code": "verification_recovery_unconfirmed"}


def reconcile_pending_verifications(
    *, repository=None, limit: int = 10, now=None, stopped=None
) -> int:
    """One bounded read batch on the existing dispatcher recovery worker."""
    repository = repository or get_agent_run_repository()
    current_time = time.time() if now is None else float(now)
    attempted = 0
    for run in _candidates(repository, current_time, max(1, min(int(limit), 100))):
        if stopped is not None and stopped():
            break
        if recover_stopped_verification(run.run_id, repository=repository, now=now) is not None:
            attempted += 1
    return attempted
