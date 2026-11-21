"""Re-read a stopped task's evidence without dispatching its business actions."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.result_verification import (
    pending_execution_receipt,
    restore_verified_artifacts,
    summarize_verification,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.runtime_context import (
    RuntimeContextOwnershipError,
)
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_models import _task_id_of
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.domain.task_lifecycle.results import execution_result_error


class VerificationRecoveryError(ValueError):
    """The original task cannot safely accept a new verification observation."""


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
        or (
            "_credential_authorization" in current
            and current["_credential_authorization"] != context.get("_credential_authorization")
        )
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
    repository: AgentRunRepository, run: AgentRun, *, optional: bool = False
) -> tuple[Any, Any] | None:
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
        if optional:
            return None
        raise VerificationRecoveryError("核验缺少原执行租约的权威终止记录")
    execution = queue.get(run.run_id)
    if execution is None and optional:
        return None
    if (
        execution is None
        or (execution.run_id, execution.task_id, execution.user_id, execution.tenant_id)
        != (run.run_id, _task_id_of(run), run.user_id, tenant_id_of_run(run))
        or execution.state not in {"unknown", "failed"}
        or execution.last_error_code != "needs_verification"
        or execution.lease_owner
        or execution.lease_expires_at
        or (execution.state == "failed" and not execution.finished_at)
    ):
        raise VerificationRecoveryError("执行租约尚未确认终止，不能接管核验")
    return queue, execution


def _can_settle_queue(run: AgentRun, body: dict[str, Any]) -> bool:
    """Every open effect must name a verified original step, never a guessed dispatch."""
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    return bool(
        run.steps
        and verification_report(run).get("accepted") is True
        and all(step.status in {"completed", "skipped"} for step in run.steps)
        and not safe_continuation_error(run)
        and set(body.get("effects") or [])
        <= {step.step_id for step in run.steps if step.status == "completed"}
    )


def _settlement_body(body: dict[str, Any], run: AgentRun, state: str, now: str) -> None:
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.domain.task_lifecycle.control import remember

    body["effects"] = []
    body["verification_receipt_sha256"] = canonical_hash(verification_report(run))
    remember(
        body, at=now, source=state, target="blocked", code="result_verified", actor=run.user_id
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
        from sqlalchemy import or_

        from app.db.models.agent import AgentTaskExecutionRecord as Record
        from app.domain.task_lifecycle.control import SessionBook

        with repository.transaction() as db:
            # Fencing uses the original queue identity and generation in the same
            # transaction as the run CAS. Merely observing an expired clock is insufficient.
            query = db.query(Record).filter(
                Record.run_id == execution.run_id,
                Record.task_id == execution.task_id,
                Record.user_id == execution.user_id,
                Record.tenant_id == execution.tenant_id,
                Record.state == execution.state,
                Record.last_error_code == "needs_verification",
                Record.execution_count == execution.execution_count,
                Record.updated_at == execution.updated_at,
                or_(Record.lease_owner.is_(None), Record.lease_owner == ""),
                or_(Record.lease_expires_at.is_(None), Record.lease_expires_at == ""),
            )
            if (
                query.update({Record.updated_at: execution.updated_at}, synchronize_session=False)
                != 1
            ):
                return False
            book = SessionBook(db)
            body = book.get("agent", execution.tenant_id, execution.run_id)
            settle = _can_settle_queue(run, body)
            run.metadata["verification_queue_state"] = "blocked" if settle else execution.state
            if not repository.save_if_unchanged_in_session(db, run, previous):
                return False
            if settle:
                now = utc_now_iso()
                if (
                    query.update(
                        {
                            Record.state: "blocked",
                            Record.last_error_code: "result_verified",
                            Record.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                    != 1
                ):
                    raise VerificationRecoveryError("核验期间原执行队列已变化")
                _settlement_body(body, run, execution.state, now)
                book.put("agent", execution.tenant_id, execution.run_id, body)
            return True
    with queue._lock:
        latest = queue.get(previous.run_id)
        if latest is None or latest.to_dict() != execution.to_dict():
            return False
        body = queue._book.get("agent", execution.tenant_id, execution.run_id)
        settle = _can_settle_queue(run, body)
        run.metadata["verification_queue_state"] = "blocked" if settle else execution.state
        if not repository.save_if_unchanged(run, previous):
            return False
        if settle:
            now = utc_now_iso()
            latest.state, latest.last_error_code, latest.updated_at = (
                "blocked",
                "result_verified",
                now,
            )
            queue._rows[latest.run_id] = copy.deepcopy(latest)
            _settlement_body(body, run, execution.state, now)
            queue._book.put("agent", execution.tenant_id, execution.run_id, body)
        return True


def reverify_run(
    repository: AgentRunRepository,
    run_id: str,
    *,
    runtime_context: dict[str, Any] | None = None,
) -> AgentRun | None:
    """Persist only observations with the existing run CAS and original receipts.

    Business dispatch, billing and approval renewal remain with the original task
    runtime. Only proven original step effects may settle under the queue CAS.
    """
    previous = repository.get(run_id)
    if previous is None:
        return None
    if previous.status not in {"blocked", "failed", "running"}:
        raise VerificationRecoveryError("只有已停止的失败或待核验任务可以重新核验")
    context = _read_context(previous, runtime_context)
    proof = (
        _stopped_queue_proof(repository, previous)
        if previous.status == "running"
        or (previous.metadata.get("execution") or {}).get("state") == "active"
        or previous.metadata.get("verification_queue_state") == "unknown"
        else None
    )
    run = copy.deepcopy(previous)
    steps = {step.step_id: step for step in run.steps}
    latest = {call.step_id: call for call in run.tool_calls}
    contracted = [call for call in latest.values() if call.metadata.get("verification_contract")]
    if not contracted:
        raise VerificationRecoveryError("原任务没有冻结的核验契约，不能补造核验证据")
    if any(call.step_id not in steps for call in contracted):
        raise VerificationRecoveryError("原执行回执缺少对应步骤，不能推定成功")
    # Independent parallel steps may have failed while another completed action
    # awaits readback. Keep failed/unknown receipts intact; observing the completed
    # action must not require replaying or accepting those other steps.
    calls = [
        call
        for call in contracted
        if steps[call.step_id].status == call.status == "completed"
        and (
            pending_execution_receipt(call.output)
            or (call.output.get("success") is True and not execution_result_error(call.output))
        )
    ]
    if not calls:
        raise VerificationRecoveryError("原任务没有可重新核验的完整成功回执")
    if proof is None and any(pending_execution_receipt(call.output) for call in calls):
        proof = _stopped_queue_proof(repository, previous, optional=True)
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
    if (
        report.get("accepted") is True
        and any(pending_execution_receipt(call.output) for call in calls)
        and all(step.status in {"completed", "skipped"} for step in run.steps)
        and (run.metadata.get("recovery") or {}).get("state") == "result_pending"
    ):
        # Only the original accepted effects are settled. Their immutable raw
        # receipts stay pending; the host's bound readback is the current result.
        run.metadata.pop("non_retryable", None)
        run.metadata.pop("recovery", None)
    if proof is not None:
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
        and run.metadata.get("verification_queue_state") != "unknown"
        and verification_report(run).get("accepted") is True
        and all(step.status in {"completed", "skipped"} for step in run.steps)
        and not safe_continuation_error(run)
    )
