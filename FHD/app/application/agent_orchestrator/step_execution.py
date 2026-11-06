"""Execute one validated tool step, recording charges, artifacts and observations."""

from __future__ import annotations

import copy
import logging
import time
from typing import Any, cast

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall, utc_now_iso
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import (
    ArtifactSink,
    ObservationSink,
    RuntimeDependencies,
)
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _confirm_customer_create(
    step: AgentStep, output: dict[str, Any], runtime_context: dict[str, Any]
) -> dict[str, Any]:
    """A child success payload is not proof the caller database contains the row."""
    if step.tool_id != "customers" or step.action != "create" or output.get("success") is not True:
        return output
    name = str(
        (step.params or {}).get("unit_name")
        or (step.params or {}).get("customer_name")
        or (step.params or {}).get("name")
        or ""
    ).strip()
    claimed = output.get("id")
    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    if claimed is None:
        claimed = data.get("id")
    unverified = {
        **output,
        "success": False,
        "error_code": "customer_receipt_unverified",
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        "message": "客户写入未在调用方数据库确认",
    }
    if not name or type(claimed) is not int:
        return unverified
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.models.purchase_unit import PurchaseUnit
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        from app.application.customer_app_service import get_customers_session

        session = get_customers_session()
    except RECOVERABLE_ERRORS:
        return unverified
    try:
        rows = (
            session.execute(
                select(PurchaseUnit)
                .where(PurchaseUnit.unit_name == name)
                .execution_options(skip_tenant_filter=True)
            )
            .scalars()
            .all()
        )
    except RECOVERABLE_ERRORS + (SQLAlchemyError,):
        return unverified
    finally:
        session.close()
    tenant = str((runtime_context or {}).get("tenant_id") or "")
    matched = [
        row
        for row in rows
        if row.unit_name == name
        and int(row.id) == claimed
        and (not tenant or str(row.tenant_id) == tenant)
    ]
    if len(matched) != 1:
        return unverified
    row = matched[0]
    confirmed = dict(data)
    confirmed.update(
        {
            "id": int(row.id),
            "customer_name": row.unit_name,
            "tenant_id": row.tenant_id,
        }
    )
    return {**output, "success": True, "id": int(row.id), "data": confirmed}


class StepExecution:
    def __init__(
        self,
        repository: AgentRunRepository,
        executor: AgentToolExecutor,
        usage: RunUsageLedger,
        dependencies: RuntimeDependencies,
        *,
        attach_artifacts: ArtifactSink,
        observe: ObservationSink,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.usage = usage
        self.dependencies = dependencies
        self.attach_artifacts = attach_artifacts
        self.observe = observe

    def execute_step(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
        node_outputs: dict[str, Any],
    ) -> None:
        started = time.perf_counter()
        step.attempt_count += 1
        step.status = "running"
        step.started_at = utc_now_iso()
        run.status = "running"
        attempt_count = step.attempt_count
        spec = self.dependencies.action_spec(step.tool_id, step.action)
        tool_call = ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=copy.deepcopy(step.params or {}),
            cost_units=int(getattr(spec, "cost_units", 0) or 0),
            permission=str(getattr(spec, "permission", "") or ""),
            metadata={
                "risk": step.risk,
                "idempotent": step.idempotent,
                "timeout_seconds": int(getattr(spec, "timeout_seconds", 0) or 0),
                "attempt_count": attempt_count,
            },
        )
        run.tool_calls.append(tool_call)
        self.usage.refresh_run_cost_metadata(run)
        trace = self._trace(
            run,
            step,
            runtime_context,
            execution_id=tool_call.call_id,
            execution_status="running",
            error_code="",
            retry_count=max(0, attempt_count - 1),
            started_at=step.started_at or "",
            finished_at="",
            spec=spec,
        )
        run.add_event(
            "tool.started",
            f"开始执行 {step.tool_id}.{step.action}",
            {
                **trace,
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "cost_units": tool_call.cost_units,
                "permission": tool_call.permission,
                "attempt_count": attempt_count,
                "params": self._redacted_params(step.params),
            },
        )
        self.repository.save(run)
        ctx = dict(runtime_context or {})
        execution_scope = {
            "run_id": run.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
            "message": run.message,
            "node_outputs": dict(node_outputs),
            **task_execution_context(run, step),
        }
        # Chat runs are keyed by the conversation owner. A sealed session binding
        # already carries the account id, and replacing it makes the binding fail.
        if not isinstance(ctx.get("_actor_authorization"), dict):
            execution_scope["user_id"] = run.user_id
        ctx.update(execution_scope)
        tool_call.metadata["idempotency_key"] = ctx["idempotency_key"]
        validation = self.dependencies.validate(step.tool_id, step.action, step.params)
        if not validation.ok:
            output = {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        elif not self.usage.record_tool_usage_entry(run, tool_call):
            output = {
                "success": False,
                "error_code": "tool_billing_blocked",
                "message": run.error or "AI tool billing failed",
                "tool_id": step.tool_id,
                "action": step.action,
            }
        else:
            if not step.idempotent:
                from app.application.agent_orchestrator.task_dispatcher import note_open_effect

                note_open_effect(run.run_id, step.step_id)
            try:
                from app.application.agent_orchestrator.tool_executor import (
                    execute_with_tool_deadline,
                )

                output = execute_with_tool_deadline(
                    self.executor,
                    step,
                    runtime_context=ctx,
                    timeout_seconds=float(getattr(spec, "timeout_seconds", 0) or 0),
                )
            except RECOVERABLE_ERRORS:
                logger.exception("agent tool execution failed")
                output = {
                    "success": False,
                    "error_code": "tool_exception",
                    "message": "工具执行失败",
                }
            except BOUNDARY_ERRORS:
                logger.exception("agent tool execution failed")
                output = {
                    "success": False,
                    "error_code": "tool_exception",
                    "message": "工具执行失败",
                }
        step.output = _confirm_customer_create(step, dict(output or {}), runtime_context)
        if step.output.get("success") is not True:
            step.output["success"] = False
        from app.application.agent_orchestrator.tool_permission import absorb_tool_output

        run.metadata["runtime_context"] = absorb_tool_output(
            dict(run.metadata.get("runtime_context") or {}), step.output
        )
        if step.output.get("retryable") is False:
            run.metadata["non_retryable"] = True
        if step.output.get("outcome") == "unknown" or step.output.get("reconciliation_required"):
            run.metadata["non_retryable"] = True
            run.metadata["recovery"] = {
                "state": "manual_reconciliation_required",
                "error_code": str(step.output.get("error_code") or "tool_outcome_unknown"),
                "step_ids": [step.step_id],
                "idempotency_key": ctx["idempotency_key"],
            }
        step.finished_at = utc_now_iso()
        step.duration_ms = int((time.perf_counter() - started) * 1000)
        tool_call.output = copy.deepcopy(step.output)
        tool_call.finished_at = step.finished_at
        tool_call.duration_ms = step.duration_ms
        success = step.output.get("success") is True
        error_code = str(step.output.get("error_code") or "")
        if success:
            execution_status = "succeeded"
        elif error_code == "tool_timeout_unknown":
            execution_status = "timeout"
        elif error_code == "tool_cancelled":
            execution_status = "cancelled"
        else:
            execution_status = "failed"
        step.status = tool_call.status = "completed" if success else "failed"
        tool_call.metadata["execution_status"] = execution_status
        if not success:
            step.error = str(
                step.output.get("message") or step.output.get("error") or "tool failed"
            )
            tool_call.error = step.error
        # Persist the executed call before optional artifact/observation work.
        self.repository.save(run)
        self.attach_artifacts(
            run,
            step.output,
            source=f"{step.tool_id}.{step.action}",
            extra_metadata={"step_id": step.step_id, "call_id": tool_call.call_id},
        )
        observation = self.observe(run, step, tool_call=tool_call, success=success)
        if success:
            self.usage.refresh_run_cost_metadata(run)
            node_outputs[step.node_id] = step.output
            receipt = run.metadata.get("approval_receipt")
            if isinstance(receipt, dict) and receipt.get("step_id") == step.step_id:
                receipt["tool_call_id"] = tool_call.call_id
                receipt["task_id"] = str((runtime_context or {}).get("task_id") or run.run_id)
            run.add_event(
                "tool.completed",
                f"完成 {step.tool_id}.{step.action}",
                {
                    **self._trace(
                        run,
                        step,
                        runtime_context,
                        execution_id=tool_call.call_id,
                        execution_status="succeeded",
                        error_code="",
                        retry_count=max(0, attempt_count - 1),
                        started_at=step.started_at or "",
                        finished_at=step.finished_at or "",
                        spec=spec,
                    ),
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": tool_call.call_id,
                    "duration_ms": step.duration_ms,
                    "cost_units": tool_call.cost_units,
                    "attempt_count": attempt_count,
                    "observation_id": observation.get("observation_id"),
                },
            )
            self.repository.save(run)
            return
        if (
            str(step.output.get("error_code") or "") != "tool_billing_blocked"
            and not step.output.get("reconciliation_required")
            and step.output.get("outcome") != "unknown"
        ):
            self.usage.record_tool_usage_refund(run, tool_call, reason=step.error)
        self.usage.refresh_run_cost_metadata(run)
        run.add_event(
            "tool.failed",
            f"{step.tool_id}.{step.action} 执行失败",
            {
                **self._trace(
                    run,
                    step,
                    ctx,
                    execution_id=tool_call.call_id,
                    execution_status=execution_status,
                    error_code=error_code,
                    retry_count=max(0, attempt_count - 1),
                    started_at=step.started_at or "",
                    finished_at=step.finished_at or "",
                    spec=spec,
                ),
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "error": step.error,
                "reason": step.error,
                "duration_ms": step.duration_ms,
                "cost_units": tool_call.cost_units,
                "attempt_count": attempt_count,
                "observation_id": observation.get("observation_id"),
            },
        )
        self.repository.save(run)

    @staticmethod
    def _redacted_params(params: dict[str, Any] | None) -> dict[str, Any]:
        from app.application.agent_orchestrator.tool_permission import redact

        return cast("dict[str, Any]", redact(dict(params or {})))

    @staticmethod
    def _trace(
        run: AgentRun,
        step: AgentStep,
        runtime_context: dict[str, Any] | None,
        *,
        execution_id: str,
        execution_status: str,
        error_code: str,
        retry_count: int,
        started_at: str,
        finished_at: str,
        spec: Any,
    ) -> dict[str, Any]:
        from app.application.agent_orchestrator.tool_permission import execution_trace

        context = runtime_context or {}
        return execution_trace(
            trace_id=run.run_id,
            task_id=str(context.get("task_id") or run.run_id),
            parent_task_id=str(context.get("parent_task_id") or ""),
            tenant_id=str(context.get("tenant_id") or ""),
            user_id=run.user_id,
            employee_id=str(context.get("employee_id") or ""),
            tool_id=step.tool_id,
            tool_version=str(getattr(spec, "version", "") or ""),
            execution_id=execution_id,
            started_at=started_at,
            finished_at=finished_at,
            execution_status=execution_status,
            error_code=error_code,
            retry_count=retry_count,
        )
