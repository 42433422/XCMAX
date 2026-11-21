"""Employee execution, canonical admission and tenant-scoped receipt recovery."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.application.admin_control.protocols import JsonObject
from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import authorization_scope_hash
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall, utc_now_iso
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.trace_payloads import _payload_status
from app.application.agent_orchestrator.unified_task import (
    UnifiedTaskConflictError,
    _assert_reused_run_scope,
    publish_task_run,
)
from app.application.employee_runtime.result_verifier import pending_employee_result
from app.domain.task_lifecycle.control import RETRYABLE_CODES, failure_retries, jittered_delay
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_outcome_unknown,
    execution_result_pending_state,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class EmployeeWork:
    employee_id: str
    task: str
    payload: JsonObject
    user_id: int
    tenant_id: int
    session_id: str
    workspace_root: str | None
    idempotency_key: str = ""
    runtime_context: JsonObject = field(default_factory=dict)


class EmployeeBackend(Protocol):
    def start(self, work: EmployeeWork) -> int: ...
    def execute(self, work: EmployeeWork, run_id: int) -> object: ...
    def verify(self, employee_id: str, result: JsonObject) -> tuple[bool, str]: ...
    def requires_reconciliation(self, result: JsonObject) -> bool: ...
    def awaits_approval(self, result: JsonObject) -> bool: ...
    def finish(
        self,
        run_id: int,
        *,
        tenant_id: int,
        status: str,
        output: JsonObject,
        error: str,
        verified: bool,
        attempts: int = 1,
        error_code: str = "",
        approver: str = "",
    ) -> None: ...


class EmployeeRunner:
    def __init__(self, backend: EmployeeBackend) -> None:
        self._backend = backend

    def run(self, work: EmployeeWork) -> JsonObject:
        run_id = self._backend.start(work)
        work.payload["run_id"] = run_id
        attempts = 1
        while True:
            # Unknown and approval results are not retried. A retryable failure
            # runs again on this same run, up to three attempts.
            raw = self._backend.execute(work, run_id)
            result = (
                raw
                if isinstance(raw, dict)
                else {
                    "success": False,
                    "error": "invalid employee result",
                    "execution_state": "unknown",
                    "reconciliation_required": True,
                }
            )
            ok, reason = self._backend.verify(work.employee_id, result)
            pending = pending_employee_result(result)
            success = ok and result.get("success") is not False and not pending
            error = (
                ""
                if success
                else reason or str(result.get("message") or result.get("error") or "执行失败")
            )
            status = (
                "success"
                if success
                else "unknown"
                if self._backend.requires_reconciliation(result)
                else "awaiting_approval"
                if self._backend.awaits_approval(result)
                else "failed"
            )
            if pending:
                state = str(pending["execution_state"])
                status = {
                    "waiting_approval": "awaiting_approval",
                    "accepted": "running",
                    "pending": "running",
                    "queued": "running",
                    "planning": "running",
                    "retrying": "running",
                    "processing": "running",
                }.get(state, state)
            error_code = (
                str(result.get("error_code") or "")
                if status == "failed" and str(result.get("error_code") or "") in RETRYABLE_CODES
                else ""
            )
            if failure_retries(attempts, error_code):
                time.sleep(jittered_delay(attempts, jitter_ratio=0.2, rng=_rng()))
                attempts += 1
                continue
            if status == "failed" and error_code == "timeout":
                status = "timed_out"
            break
        self._backend.finish(
            run_id,
            tenant_id=work.tenant_id,
            status=status,
            output=result,
            error=error,
            verified=False,
            attempts=attempts,
            error_code=error_code,
            approver=str(work.user_id) if status == "awaiting_approval" else "",
        )
        from app.application.employee_runtime.run_ledger import employee_result_validation

        # Project verification only after retry classification and ledger completion.
        # Keep the original receipt intact; this route has no independent readback.
        response: JsonObject = {
            "success": success,
            "source": "local",
            "run_id": run_id,
            "attempts": attempts,
            "data": result,
            "execution_state": "completed" if success else status,
            **{key: value for key, value in pending.items() if key != "run_id"},
            **employee_result_validation(status=status),
        }
        if not success:
            response["message"] = error
        return response


def _rng():
    import random

    return random.Random()


def employee_task_id(context: dict[str, Any], key: str) -> str:
    return (
        "admin_employee_"
        + canonical_hash(
            ["admin_employee_execute.v1", str(context["tenant_id"]), str(context["user_id"]), key]
        )[:40]
    )


def _scope(context: dict[str, Any]) -> dict[str, Any]:
    actor = context.get("_actor_authorization") or {}
    binding = context.get("_mod_authorization") or {}
    return {
        "user_id": str(context.get("user_id") or ""),
        "tenant_id": str(context.get("tenant_id") or ""),
        "mod_id": str(binding.get("mod_id") or context.get("mod_id") or ""),
        "role": actor.get("role"),
        "workspace_root": context.get("workspace_root"),
    }


def _assert_employee_identity(
    run: AgentRun, employee_id: str, key: str, context: dict[str, Any]
) -> None:
    if (
        run.metadata.get("admin_employee_id") != employee_id
        or run.metadata.get("admin_employee_scope") != _scope(context)
        or run.metadata.get("admin_employee_key") != key
    ):
        raise UnifiedTaskConflictError("原请求已绑定不同员工或授权范围")
    _assert_reused_run_scope(
        run,
        user_id=str(context["user_id"]),
        tenant_id=str(context["tenant_id"]),
        runtime_context=context,
    )


def _settle_receipt(run: AgentRun, result: dict[str, Any]) -> None:
    state = execution_result_pending_state(result) or _payload_status(result)
    terminal = state in {"completed", "failed", "cancelled", "rejected"}
    run.status = _payload_status(result)
    step, call = run.steps[0], run.tool_calls[0]
    step.status = "completed" if state == "completed" else "failed" if terminal else "waiting_user"
    call.status = "completed" if state == "completed" else "failed" if terminal else "running"
    step.output = call.output = result
    if terminal:
        call.finished_at = utc_now_iso()
        step.finished_at = call.finished_at
    if state == "unknown":
        run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    run.final_output.update(
        admin_employee_receipt=result,
        node_outputs={**run.final_output.get("node_outputs", {}), step.node_id: result},
    )


def _delegated_result(
    stored: dict[str, Any], child_id: str, child: dict[str, Any]
) -> dict[str, Any]:
    return {
        "employee_run_id": stored.get("employee_run_id"),
        "attempts": stored.get("attempts", 1),
        "source": "local",
        "agent_run_id": child_id,
        "child_receipt": child,
        "data": child.get("final_output", {}),
        "execution_state": child["execution_state"],
        "success": child["execution_state"] == "completed",
        **({"requires_reconciliation": True} if child["execution_state"] == "unknown" else {}),
    }


def _refresh_receipt(service: AgentOrchestrator, run: AgentRun) -> AgentRun:
    """Reconcile only this one-call wrapper via the existing run/task snapshot CAS."""
    stored = run.final_output.get("admin_employee_receipt")
    child_id = str(run.metadata.get("admin_employee_child_run_id") or "")
    if run.status in {"completed", "failed", "cancelled", "rejected"}:
        return run
    result: dict[str, Any] | None = None
    if child_id:
        from app.application.agent_orchestrator.run_audit_scope import project_child_results

        child = project_child_results(run, service.get_run).get(child_id)
        # A child cannot settle an unrelated/open parent effect. The wrapper itself
        # is non-retryable by design; manual recovery and interruption evidence stay.
        complete_delegation = (
            isinstance(stored, dict)
            and stored.get("agent_run_id") == child_id
            and set(run.metadata.get("child_results") or {}) == {child_id}
            and len(run.steps) == len(run.tool_calls) == 1
            and (run.steps[0].tool_id, run.steps[0].action) == ("employee", "execute")
            and run.tool_calls[0].step_id == run.steps[0].step_id
            and run.steps[0].output == run.tool_calls[0].output == stored
            and set(run.final_output) <= {"admin_employee_receipt", "node_outputs"}
            and set(run.final_output.get("node_outputs") or {}) == {run.steps[0].node_id}
            and not run.metadata.get("stream_interruption")
            and (run.metadata.get("recovery") or {}).get("state")
            != "manual_reconciliation_required"
            and not execution_result_outcome_unknown(run.final_output)
        )
        if (
            complete_delegation
            and isinstance(stored, dict)
            and child
            and child["execution_state"] != "unknown"
        ):
            result = _delegated_result(stored, child_id, child)
        elif not execution_result_outcome_unknown(run.final_output):
            result = {
                **(stored if isinstance(stored, dict) else {}),
                "success": False,
                "execution_state": "unknown",
                "requires_reconciliation": True,
            }
    elif not stored:
        deadline = str(run.metadata.get("admin_employee_receipt_deadline") or "")
        if not deadline or deadline <= utc_now_iso():
            result = {
                "success": False,
                "execution_state": "unknown",
                "requires_reconciliation": True,
            }
    if result is None or result == stored or not run.steps or not run.tool_calls:
        return run
    previous = copy.deepcopy(run)
    _settle_receipt(run, result)
    run.add_event("employee.receipt_reconciled", "已核对原员工回执，未重新执行员工")
    try:
        if service._repo.save_if_unchanged(run, previous):
            return run
    except RECOVERABLE_ERRORS:
        pass
    # Another writer owns the changed snapshot. Never return our uncommitted
    # completion as if the canonical run/task accepted it.
    return service.get_run(previous.run_id) or previous


def _receipt(run: AgentRun, *, replay: bool) -> dict[str, Any]:
    stored = run.final_output.get("admin_employee_receipt")
    result = copy.deepcopy(stored) if isinstance(stored, dict) else {}
    state = execution_result_pending_state(result) or _payload_status(
        {"agent_status": run.status, "output": result}
    )
    if (run.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required":
        state = "unknown"
    if not stored:
        deadline = str(run.metadata.get("admin_employee_receipt_deadline") or "")
        if not deadline or deadline <= utc_now_iso():
            state = "unknown"
    original_child = result.get("agent_run_id")
    result.update(
        run_id=run.run_id,
        agent_run_id=run.run_id,
        task_id=(run.metadata.get("task_context") or {}).get("task_id"),
        idempotency_key=run.metadata["admin_employee_key"],
        turn_id=run.metadata["admin_employee_key"],
        execution_state=state,
        success=state == "completed",
        deduplicated=replay,
        execution_accepted=state not in {"completed", "failed", "cancelled", "rejected"},
        retryable=False,
    )
    if original_child and str(original_child) != run.run_id:
        result["child_run_id"] = str(original_child)
    if state == "unknown":
        result.update(
            requires_reconciliation=True, message="执行结果待核对，请读取原任务，勿重复提交。"
        )
    return result


def read_employee_receipt(
    employee_id: str,
    key: str,
    context: dict[str, Any],
    *,
    orchestrator: AgentOrchestrator | None = None,
) -> dict[str, Any] | None:
    service = orchestrator or AgentOrchestrator()
    task = service.get_task(
        user_id=str(context["user_id"]),
        tenant_id=str(context["tenant_id"]),
        task_id=employee_task_id(context, key),
    )
    if task is None:
        return None
    run = service.get_run(task.root_run_id or task.active_run_id)
    if run is None:
        # Without the original run its Mod binding cannot be authenticated. The
        # route returns an unavailable/unknown receipt, never another active run.
        return None
    _assert_employee_identity(run, employee_id, key, context)
    return _receipt(_refresh_receipt(service, run), replay=True)


def execute_admitted_employee(
    work: EmployeeWork,
    execute: Callable[[EmployeeWork], dict[str, Any]],
    *,
    orchestrator: AgentOrchestrator | None = None,
) -> dict[str, Any]:
    service = orchestrator or AgentOrchestrator()
    context = dict(work.runtime_context)
    task_id = employee_task_id(context, work.idempotency_key)
    context.update(
        task_id=task_id,
        turn_id=work.idempotency_key,
        idempotency_key=work.idempotency_key,
        conversation_id=task_id,
        session_id=task_id,
        source="admin_employee_execute",
        task_type="employee",
    )
    # Authenticated identity is bound separately. Do not persist session credentials
    # or approval tokens in task params; the digest still detects changed tokens/input.
    inputs = {key: value for key, value in work.payload.items() if key != "session_id"}
    params = {
        "employee_id": work.employee_id,
        "task": work.task,
        "input_sha256": canonical_hash(inputs),
        "authorization": _scope(context),
    }
    run = AgentRun(user_id=str(work.user_id), message=work.task, status="running")
    scope = dict(context)
    if not isinstance(scope.get("_actor_authorization"), dict):
        scope["user_id"] = run.user_id
    from app.application.agent_orchestrator.tool_spec import (
        DEFAULT_TIMEOUT_SECONDS,
        get_tool_action_spec,
    )
    from app.domain.task_lifecycle.machine import DEFAULT_MAX_ATTEMPTS, retry_delay_seconds

    spec = get_tool_action_spec("employee", "execute")
    timeout = spec.timeout_seconds if spec else DEFAULT_TIMEOUT_SECONDS
    receipt_budget = timeout * DEFAULT_MAX_ATTEMPTS + sum(
        retry_delay_seconds(attempt) * 1.2 for attempt in range(1, DEFAULT_MAX_ATTEMPTS)
    )
    run.metadata.update(
        runtime_context=context,
        execution_authorization_scope=authorization_scope_hash(scope),
        admin_employee_key=work.idempotency_key,
        admin_employee_id=work.employee_id,
        admin_employee_scope=_scope(context),
        non_retryable=True,
        admin_employee_receipt_deadline=(
            datetime.now(UTC) + timedelta(seconds=receipt_budget)
        ).isoformat(),
    )
    apply_task_context(run, context)
    step = AgentStep(
        "employee", "employee", "execute", params=params, risk="high", status="running"
    )
    denial = actor_tool_denial(step.tool_id, step.action, scope, step.params)
    if denial is not None:
        return {**denial, "execution_state": "blocked", "execution_status": "not_started"}
    call = ToolCall(step.step_id, step.node_id, step.tool_id, step.action, params=params)
    run.steps, run.tool_calls = [step], [call]
    run.add_event("run.created", "管理端员工任务已登记，等待原调用回执")
    publication = publish_task_run(
        orchestrator=service,
        run=run,
        tool_id="employee",
        action="execute",
        params=params,
        risk="high",
        idempotent=False,
        runtime_context=context,
    )
    if publication.deduplicated:
        _assert_employee_identity(publication.run, work.employee_id, work.idempotency_key, context)
        return _receipt(_refresh_receipt(service, publication.run), replay=True)
    run = publication.run
    work.runtime_context.update(context, run_id=run.run_id, agent_run_id=run.run_id)
    try:
        result = execute(work)
        result = copy.deepcopy(result)
        if isinstance(result.get("run_id"), int):
            result["employee_run_id"] = result.pop("run_id")
    except RECOVERABLE_ERRORS:
        result = {
            "success": False,
            "execution_state": "unknown",
            "requires_reconciliation": True,
            "retryable": False,
        }
    state = execution_result_pending_state(result) or _payload_status(result)
    child_ids = {
        str(receipt["agent_run_id"])
        for receipt in execution_result_envelopes(result)
        if receipt.get("agent_run_id") and str(receipt["agent_run_id"]) != run.run_id
    }
    child_id = next(iter(child_ids), "") if len(child_ids) == 1 else ""
    if len(child_ids) > 1:
        result.update(success=False, execution_state="unknown", requires_reconciliation=True)
    if child_id and child_id != run.run_id:
        from app.application.agent_orchestrator.run_audit_scope import (
            attach_child_result,
            project_child_results,
        )

        run.metadata["admin_employee_child_run_id"] = child_id
        result["agent_run_id"] = child_id
        child = service.get_run(child_id)
        if not (
            child is not None
            and (child.metadata.get("runtime_context") or {}).get("parent_run_id") == run.run_id
            and attach_child_result(run, child)
        ):
            result.update(success=False, execution_state="unknown", requires_reconciliation=True)
        elif state not in {"unknown", "failed", "cancelled", "rejected"}:
            # Even the first response must read the exact child: a claimed success
            # cannot complete a missing, foreign, waiting or uncertain child.
            projected = project_child_results(run, service.get_run).get(child_id) or {
                "execution_state": "unknown"
            }
            result = _delegated_result(result, child_id, projected)
    state = execution_result_pending_state(result) or _payload_status(result)
    _settle_receipt(run, result)
    run.add_event("employee.receipt", "原员工调用回执已返回", {"execution_state": state})
    try:
        run = service.save_run(run)
    except RECOVERABLE_ERRORS:
        result = _receipt(run, replay=False)
        result.update(success=False, execution_state="unknown", requires_reconciliation=True)
        return result
    return _receipt(_refresh_receipt(service, run), replay=False)
