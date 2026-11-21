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
    project_verification,
    restore_verified_artifacts,
    step_verification_blocked,
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
from app.application.agent_orchestrator.task_context import ensure_run_trace
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.verification_cognition import verified_plan_admission
from app.domain.task_lifecycle.results import (
    execution_result_outcome_unknown,
    execution_result_requires_reconciliation,
)
from app.infrastructure.observability.genai_spans import (
    record_tool_exception,
    record_tool_result,
    tool_call_span,
)
from app.infrastructure.observability.metrics import observe_tool_call
from app.neuro_bus.tracer import get_trace_context
from app.security.log_redaction import redact_log_text
from app.utils.operational_errors import BOUNDARY_ERRORS

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
        from app.application.agent_orchestrator.verification_continuation import (
            approved_preview_continuation,
            original_preview_step,
            preview_resume_matches,
        )

        prior = latest_step_call(run, step)
        continuation = prior if prior and approved_preview_continuation(run, step, prior) else None
        if (
            prior is not None
            and continuation is None
            and prior.output.get("success") is True
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
            receipt_step = (
                original_preview_step(step, prior) if preview_resume_matches(step, prior) else step
            )
            verify_step_result(run=run, step=receipt_step, call=prior, context=context)
            restore_verified_artifacts(run, step, prior, self.attach_artifacts)
            self._record_verification(run, step, prior)
            if not step_verification_blocked(run, step):
                node_outputs[step.node_id] = dict(step.output)
            self.repository.save(run)
            return
        started = time.perf_counter()
        step.attempt_count += 1
        step.status = "running"
        step.started_at = utc_now_iso()
        step.finished_at, step.error, step.duration_ms = "", "", 0
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
                step.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
                run.add_event(
                    "budget.exceeded",
                    step.error,
                    {
                        **denial,
                        "step_id": step.step_id,
                        "node_id": step.node_id,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "attempt": attempt_count,
                        "duration_ms": step.duration_ms,
                        "error_type": str(denial.get("error_code") or "budget_exceeded"),
                    },
                )
                self.repository.save(run)
                return
            tool_call = ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=copy.deepcopy(step.params or {}),
                started_at=step.started_at,
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
            if continuation is not None:
                tool_call.metadata["continued_from_call_id"] = continuation.call_id
            freeze_verification_contract(run, step, tool_call, spec, runtime_context)
            run.tool_calls.append(tool_call)
            project_verification(run)
            self.usage.refresh_run_cost_metadata(run)
        ctx = dict(runtime_context or {})
        self._execute_call(run, step, tool_call, runtime_context, ctx, node_outputs, spec)
        from app.application.agent_orchestrator.tool_permission import absorb_tool_output

        run.metadata["runtime_context"] = absorb_tool_output(
            dict(run.metadata.get("runtime_context") or {}), step.output
        )
        unresolved = execution_result_requires_reconciliation(
            step.output
        ) and not verified_plan_admission(step, step.output, ctx)
        uncertain = unresolved and execution_result_outcome_unknown(step.output)
        if unresolved or (
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
            step.output.update(
                success=False,
                outcome="unknown",
                retryable=False,
                reconciliation_required=True,
            )
            run.metadata["recovery"] = {
                "state": "manual_reconciliation_required",
                "error_code": str(step.output.get("error_code") or "tool_outcome_unknown"),
                "step_ids": [step.step_id],
                "idempotency_key": ctx["idempotency_key"],
            }
        step.finished_at = utc_now_iso()
        step.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        tool_call.output = copy.deepcopy(step.output)
        tool_call.finished_at = step.finished_at
        tool_call.duration_ms = step.duration_ms
        success = step.output.get("success") is True
        error_code = (
            ""
            if success
            else redact_log_text(str(step.output.get("error_code") or "tool_failed"))[:128]
        )
        error_type = (
            ""
            if success
            else redact_log_text(str(step.output.get("error_type") or error_code))[:128]
        )
        if success:
            execution_status = "succeeded"
        elif error_code == "tool_timeout_unknown":
            execution_status = "timeout"
        elif error_code == "tool_cancelled":
            execution_status = "cancelled"
        else:
            execution_status = "failed"
        step.status = tool_call.status = "completed" if success else "failed"
        if (
            success
            and step.output.get("requires_user_decision") is True
            and step.output.get("question")
        ):
            # Persist a decision pause before completed-step retention runs.
            # The original call receipt remains completed and immutable.
            step.status = run.status = "waiting_user"
        tool_call.metadata.update(
            {
                "execution_status": execution_status,
                "error_code": error_code,
                "error_type": error_type,
            }
        )
        try:
            observe_tool_call(
                tool=step.tool_id,
                status="success" if success else execution_status,
                duration_ms=step.duration_ms,
            )
        except BOUNDARY_ERRORS:
            logger.warning("tool metrics recording failed")
        if not success:
            step.error = redact_log_text(
                str(step.output.get("message") or step.output.get("error") or "tool failed")
            )[:1024]
            tool_call.error = step.error
        # Persist the original executor receipt before independent readback.
        bind_execution_receipt(tool_call)
        project_verification(run)
        self.repository.save(run)
        verify_step_result(run=run, step=step, call=tool_call, context=ctx)
        restore_verified_artifacts(run, step, tool_call, self.attach_artifacts)
        self._record_verification(run, step, tool_call)
        self.repository.save(run)
        if step_verification_blocked(run, step):
            return
        observation = self.observe(run, step, tool_call=tool_call, success=success)
        event_data = self._trace(run, step, ctx, tool_call, spec, execution_status)
        event_data["observation_id"] = observation.get("observation_id")
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
                event_data,
            )
            self.repository.save(run)
            return
        if str(step.output.get("error_code") or "") != "tool_billing_blocked" and not uncertain:
            self.usage.record_tool_usage_refund(run, tool_call, reason=step.error)
        self.usage.refresh_run_cost_metadata(run)
        run.add_event(
            "tool.failed",
            f"{step.tool_id}.{step.action} 执行失败",
            {**event_data, "error": step.error, "reason": step.error},
        )
        self.repository.save(run)

    def _execute_call(
        self,
        run: AgentRun,
        step: AgentStep,
        tool_call: ToolCall,
        runtime_context: dict[str, Any],
        ctx: dict[str, Any],
        node_outputs: dict[str, Any],
        spec: Any,
    ) -> None:
        attempt_count = step.attempt_count
        run_trace = ensure_run_trace(run)
        parent_id = run_trace.get("span_id")
        with tool_call_span(
            tool_id=step.tool_id,
            action=step.action,
            node_id=step.node_id,
            run_id=run.run_id,
            call_id=tool_call.call_id,
            attempt=attempt_count,
            trace_id=run_trace["trace_id"],
            parent_span_id=parent_id,
            trace_flags=run_trace.get("trace_flags"),
            trace_state=run_trace.get("trace_state"),
        ) as span:
            tool_call.metadata.update(
                {
                    **get_trace_context(),
                    "parent_span_id": parent_id or "",
                    "attempt": attempt_count,
                }
            )
            run.add_event(
                "tool.started",
                f"开始执行 {step.tool_id}.{step.action}",
                {
                    **self._trace(run, step, runtime_context, tool_call, spec, "running"),
                    "permission": tool_call.permission,
                    "params": self._redacted_params(step.params),
                },
            )
            self.repository.save(run)
            execution_scope: dict[str, Any] = {
                "run_id": run.run_id,
                "step_id": step.step_id,
                "node_id": step.node_id,
                "message": run.message,
                "node_outputs": dict(node_outputs),
                **task_execution_context(run, step),
                **{
                    key: tool_call.metadata[key]
                    for key in (
                        "trace_id",
                        "span_id",
                        "parent_span_id",
                        "trace_flags",
                        "trace_state",
                    )
                    if key in tool_call.metadata
                },
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
                ctx["_tool_approval_scope"] = {
                    key: receipt.get(key)
                    for key in (
                        "tool_id",
                        "action",
                        "authorization_scope_sha256",
                        "tool_contract_sha256",
                        "tool_version",
                        "kellai_connection_sha256",
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
                from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost

                try:
                    from app.application.agent_orchestrator.tool_executor import (
                        execute_with_tool_deadline,
                    )
                    from app.application.agent_orchestrator.tool_timeouts import (
                        tool_timeout_seconds,
                    )

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
                except (EltCheckpointWorkerExited, WorkerLeaseLost):
                    raise
                except BOUNDARY_ERRORS as exc:
                    record_tool_exception(span, exc)
                    logger.error("agent tool execution failed: %s", type(exc).__name__)
                    output = {
                        "success": False,
                        "error_code": "tool_exception",
                        "error_type": type(exc).__name__,
                        "message": "工具执行失败",
                    }
            # The execution boundary has already normalized the result, including
            # known waits and independently verified cognition-plan admissions.
            step.output = dict(output or {})
            if step.output.get("success") is not True:
                step.output["success"] = False
            record_tool_result(span, step.output)

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
        tool_call: ToolCall,
        spec: Any,
        execution_status: str,
    ) -> dict[str, Any]:
        from app.application.agent_orchestrator.tool_permission import execution_trace

        context = runtime_context or {}
        metadata = tool_call.metadata
        return {
            **execution_trace(
                trace_id=str(metadata.get("trace_id") or run.metadata.get("trace_id") or ""),
                task_id=str(context.get("task_id") or run.run_id),
                parent_task_id=str(context.get("parent_task_id") or ""),
                tenant_id=str(context.get("tenant_id") or ""),
                user_id=run.user_id,
                employee_id=str(context.get("employee_id") or ""),
                tool_id=step.tool_id,
                tool_version=str(getattr(spec, "version", "") or ""),
                execution_id=tool_call.call_id,
                started_at=step.started_at,
                finished_at=step.finished_at,
                execution_status=execution_status,
                error_code=str(metadata.get("error_code") or ""),
                retry_count=max(0, step.attempt_count - 1),
            ),
            "span_id": metadata.get("span_id", ""),
            "parent_span_id": metadata.get("parent_span_id", ""),
            "trace_flags": metadata.get("trace_flags", ""),
            "trace_state": metadata.get("trace_state", ""),
            "step_id": step.step_id,
            "node_id": step.node_id,
            "call_id": tool_call.call_id,
            "action": step.action,
            "attempt": step.attempt_count,
            "attempt_count": step.attempt_count,
            "duration_ms": step.duration_ms,
            "cost_units": tool_call.cost_units,
            "error_type": metadata.get("error_type", ""),
        }
