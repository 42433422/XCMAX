"""Execute one validated tool step, recording charges, artifacts and observations."""

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any, cast

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    latest_step_call,
    pending_execution_receipt,
    project_verification,
    restore_verified_artifacts,
    step_verification_blocked,
    verified_step_output,
    verify_step_result,
)
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
from app.application.employee_runtime.result_verifier import (
    execution_result_requires_reconciliation,
)
from app.domain.task_lifecycle.results import execution_result_outcome_unknown
from app.infrastructure.observability.genai_spans import tool_call_span
from app.infrastructure.observability.metrics import observe_tool_call
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
        self._admission_lock = threading.RLock()

    def execute_step(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
        node_outputs: dict[str, Any],
    ) -> None:
        prior = latest_step_call(run, step)
        if (
            prior is not None
            and (prior.output.get("success") is True or pending_execution_receipt(prior.output))
            and prior.metadata.get("verification_contract")
            and prior.metadata.get("verification_output_sha256")
        ):
            # A receipt already exists. This path can only read evidence; neither
            # verification failure nor a graph replay authorizes another effect.
            context = {
                **runtime_context,
                "run_id": run.run_id,
                "step_id": step.step_id,
                "node_id": step.node_id,
                **task_execution_context(run, step),
            }
            verify_step_result(run=run, step=step, call=prior, context=context)
            restore_verified_artifacts(run, step, prior, self.attach_artifacts)
            self._record_verification(run, step, prior)
            if not step_verification_blocked(run, step):
                node_outputs[step.node_id] = verified_step_output(run, step)
            self.repository.save(run)
            return
        started = time.perf_counter()
        step.attempt_count += 1
        step.status = "running"
        step.started_at = utc_now_iso()
        run.status = "running"
        attempt_count = step.attempt_count
        spec = self.dependencies.action_spec(step.tool_id, step.action)
        # Parallel scheduler prechecks can observe the same remaining credit.
        # Reserve each in-flight call in the ordinary ledger before releasing
        # admission; the slow tool execution remains genuinely concurrent.
        with self._admission_lock:
            from app.application.agent_orchestrator.budget import budget_exceeded_payload

            self.usage.refresh_run_cost_metadata(run)
            denial = budget_exceeded_payload(
                run,
                additional_cost_units=int(getattr(spec, "cost_units", 0) or 0),
                scope=f"{step.tool_id}.{step.action}",
            )
            if denial is not None:
                step.status = "failed"
                step.error = str(denial["message"])
                step.output = {"success": False, **denial, "retryable": False}
                step.finished_at = utc_now_iso()
                run.status, run.error = "failed", step.error
                run.metadata["ai_cost_budget_exceeded"] = True
                run.add_event("budget.exceeded", step.error, dict(denial))
                self.repository.save(run)
                return
            tool_call = ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=copy.deepcopy(step.params or {}),
                cost_units=int(getattr(spec, "cost_units", 0) or 0),
                permission=str(
                    getattr(spec, "receipt_permission", getattr(spec, "permission", "")) or ""
                ),
                metadata={
                    "risk": step.risk,
                    "idempotent": step.idempotent,
                    "timeout_seconds": int(getattr(spec, "timeout_seconds", 0) or 0),
                    "attempt_count": attempt_count,
                },
            )
            authorization_permission = getattr(spec, "permission", "")
            if tool_call.permission != authorization_permission:
                tool_call.metadata["authorization_permission"] = authorization_permission
            freeze_verification_contract(run, step, tool_call, spec, runtime_context)
            run.tool_calls.append(tool_call)
            project_verification(run)
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
        receipt = run.metadata.get("approval_receipt")
        if (
            isinstance(receipt, dict)
            and receipt.get("step_id") == step.step_id
            and step.tool_id != "catalog_products_v1"
        ):
            from app.application.agent_orchestrator.approval_grant import execution_scope_claims

            ctx["_tool_approval_scope"] = {
                key: receipt.get(key)
                for key in (
                    "tool_id",
                    "action",
                    *execution_scope_claims(ctx, step.tool_id, step.action),
                )
            }
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
            from app.application.agent_orchestrator.elt_checkpoint_recovery import (
                EltCheckpointWorkerExited,
            )

            if not step.idempotent:
                from app.application.agent_orchestrator.task_dispatcher import note_open_effect

                note_open_effect(run.run_id, step.step_id)
            try:
                from app.application.agent_orchestrator.tool_executor import (
                    execute_with_tool_deadline,
                )
                from app.application.agent_orchestrator.tool_timeouts import (
                    tool_timeout_seconds,
                )

                with tool_call_span(
                    tool_id=step.tool_id,
                    action=step.action,
                    node_id=step.node_id,
                    run_id=run.run_id,
                ):
                    output = execute_with_tool_deadline(
                        self.executor,
                        step,
                        runtime_context=ctx,
                        timeout_seconds=tool_timeout_seconds(
                            step.tool_id,
                            step.action,
                            dict(step.params or {}),
                            float(getattr(spec, "timeout_seconds", 0) or 0),
                        ),
                    )
            except EltCheckpointWorkerExited:
                raise
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
        step.output = dict(output or {})
        if step.output.get("success") is not True:
            step.output["success"] = False
        from app.application.agent_orchestrator.tool_permission import absorb_tool_output

        run.metadata["runtime_context"] = absorb_tool_output(
            dict(run.metadata.get("runtime_context") or {}), step.output
        )
        uncertain = execution_result_requires_reconciliation(step.output)
        if uncertain or (
            step.output.get("retryable") is False
            and (
                step.output.get("success") is not True
                # Catalog terminal receipts retain their independent source
                # readback in AgentOrchestrator._verified_catalog_terminal.
                or step.tool_id == "catalog_products_v1"
            )
        ):
            run.metadata["non_retryable"] = True
        if uncertain:
            unknown = execution_result_outcome_unknown(step.output)
            step.output.update(success=False, retryable=False)
            if unknown:
                step.output.update(outcome="unknown", reconciliation_required=True)
            run.metadata["recovery"] = {
                "state": "manual_reconciliation_required" if unknown else "result_pending",
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
        pending = pending_execution_receipt(step.output)
        error_code = str(step.output.get("error_code") or "")
        if success:
            execution_status = "succeeded"
        elif pending:
            execution_status = "accepted"
        elif error_code == "tool_timeout_unknown":
            execution_status = "timeout"
        elif error_code == "tool_cancelled":
            execution_status = "cancelled"
        else:
            execution_status = "failed"
        step.status = tool_call.status = "completed" if success or pending else "failed"
        tool_call.metadata["execution_status"] = execution_status
        observe_tool_call(
            tool=step.tool_id,
            status="success" if success else execution_status,
            duration_ms=step.duration_ms,
        )
        if not success and not pending:
            step.error = str(
                step.output.get("message") or step.output.get("error") or "tool failed"
            )
            tool_call.error = step.error
        # The executor receipt and its frozen contract survive a crash before
        # verification. ToolCall/step completion records execution, while the
        # independent report gates graph progress and the final run status.
        bind_execution_receipt(tool_call)
        project_verification(run)
        self.repository.save(run)
        verify_step_result(run=run, step=step, call=tool_call, context=ctx)
        restore_verified_artifacts(run, step, tool_call, self.attach_artifacts)
        self._record_verification(run, step, tool_call)
        self.repository.save(run)
        if step_verification_blocked(run, step):
            return
        projected = verified_step_output(run, step)
        success = projected.get("success") is True
        observation = self.observe(run, step, tool_call=tool_call, success=success)
        if success:
            self.usage.refresh_run_cost_metadata(run)
            node_outputs[step.node_id] = projected
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
    def _record_verification(run: AgentRun, step: AgentStep, call: ToolCall) -> None:
        report = copy.deepcopy(call.metadata.get("verification") or {})
        project_verification(run)
        if step_verification_blocked(run, step):
            run.status = "blocked"
            run.error = "执行已返回，独立结果核验尚未通过；请核验原结果，勿重复执行业务"
        run.add_event(
            "verification." + str(report.get("status") or "inconclusive"),
            "独立结果核验" if report.get("status") != "not_required" else "只读输出契约检查",
            {"step_id": step.step_id, "call_id": call.call_id, "verification": report},
        )

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
