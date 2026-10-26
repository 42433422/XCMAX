"""Execute one validated tool step, recording charges, artifacts and observations."""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

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
from app.utils.operational_errors import RECOVERABLE_ERRORS

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
        run.add_event(
            "tool.started",
            f"开始执行 {step.tool_id}.{step.action}",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "cost_units": tool_call.cost_units,
                "permission": tool_call.permission,
                "attempt_count": attempt_count,
            },
        )
        self.repository.save(run)
        ctx = dict(runtime_context or {})
        ctx.update(
            {
                "run_id": run.run_id,
                "step_id": step.step_id,
                "node_id": step.node_id,
                "message": run.message,
                "user_id": run.user_id,
                "node_outputs": dict(node_outputs),
                **task_execution_context(run, step),
            }
        )
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
        step.output = dict(output or {})
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
        success = bool(step.output.get("success", False))
        step.status = tool_call.status = "completed" if success else "failed"
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
            run.add_event(
                "tool.completed",
                f"完成 {step.tool_id}.{step.action}",
                {
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
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "error": step.error,
                "duration_ms": step.duration_ms,
                "cost_units": tool_call.cost_units,
                "attempt_count": attempt_count,
                "observation_id": observation.get("observation_id"),
            },
        )
        self.repository.save(run)
