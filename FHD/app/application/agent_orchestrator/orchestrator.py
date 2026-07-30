from __future__ import annotations

import copy
import time
from collections.abc import Callable
from typing import Any

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.budget import (
    apply_ai_budget_metadata,
    budget_exceeded_payload,
    refresh_ai_budget_metadata,
)
from app.application.agent_orchestrator.execution_verifier import (
    summarize_run_verification,
    verify_tool_execution,
)
from app.application.agent_orchestrator.orchestration_evidence import (
    build_orchestration_evidence,
)
from app.application.agent_orchestrator.orchestrator_repair import AgentOrchestratorRepairMixin
from app.application.agent_orchestrator.repair_advisor import (
    is_llm_repair_enabled,
    llm_repair_attempt_limit,
    request_llm_repair,
)
from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    LLMCall,
    RunEvent,
    ToolCall,
    artifact_from_dict,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import (
    get_tool_action_spec,
    normalize_tool_call_params,
    validate_tool_call,
)
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.utils.operational_errors import RECOVERABLE_ERRORS


class AgentOrchestrator(AgentOrchestratorRepairMixin):
    def __init__(
        self,
        *,
        repository: AgentRunRepository | None = None,
        tool_executor: AgentToolExecutor | None = None,
    ) -> None:
        self._repo = repository or get_agent_run_repository()
        self._tool_executor = tool_executor or AgentToolExecutor()

    def submit_run(
        self,
        *,
        user_id: str,
        message: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Persist a run immediately and plan/execute it outside the request."""
        run = AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        run.metadata["runtime_context"] = dict(runtime_context or {})
        run.metadata["background_execution"] = True
        run.add_event("run.created", "Agent run 已创建")
        self._checkpoint(run, phase="queued")
        saved = self._repo.save(run)

        from app.application.agent_orchestrator.runtime import get_agent_run_runtime

        return get_agent_run_runtime().submit(saved.run_id) or saved

    def submit_run_from_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Persist a prepared plan and schedule its execution in the worker pool."""
        run = AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        context = dict(runtime_context or {})
        run.metadata["runtime_context"] = context
        run.metadata["background_execution"] = True
        run.add_event("run.created", "Agent run 已创建")
        run.add_event(
            "planner.completed",
            "Agent 计划已接管",
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "nodes": len(plan.nodes),
                "source": "provided_plan",
                "planner_mode": plan.metadata.get("planner_mode"),
                "degraded": bool(plan.metadata.get("degraded")),
                "degraded_reason": plan.metadata.get("degraded_reason"),
            },
        )
        self._apply_plan(run, plan)
        apply_ai_budget_metadata(run, dict(plan.metadata or {}), context)
        run.status = "queued"
        self._checkpoint(run, phase="planned")
        saved = self._repo.save(run)

        from app.application.agent_orchestrator.runtime import get_agent_run_runtime

        return get_agent_run_runtime().submit(saved.run_id) or saved

    def start_run(
        self,
        *,
        user_id: str,
        message: str,
        runtime_context: dict[str, Any] | None = None,
        auto_execute: bool = True,
    ) -> AgentRun:
        run = AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        run.metadata["runtime_context"] = dict(runtime_context or {})
        run.add_event("run.created", "Agent run 已创建")
        self._repo.save(run)

        try:
            plan = self._plan(run, runtime_context=dict(runtime_context or {}))
            self._apply_plan(run, plan)
            apply_ai_budget_metadata(run, dict(plan.metadata or {}), dict(runtime_context or {}))
            self._repo.save(run)
            if auto_execute:
                self._execute_ready_steps(run, runtime_context=dict(runtime_context or {}))
            return self._repo.save(run)
        except RECOVERABLE_ERRORS as exc:
            run.status = "failed"
            run.error = str(exc)
            run.add_event("run.failed", "Agent run 失败", {"error": str(exc)})
            return self._repo.save(run)

    def start_run_from_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        auto_execute: bool = True,
    ) -> AgentRun:
        run = AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        run.metadata["runtime_context"] = dict(runtime_context or {})
        run.add_event("run.created", "Agent run 已创建")
        run.add_event(
            "planner.completed",
            "Agent 计划已接管",
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "nodes": len(plan.nodes),
                "source": "provided_plan",
                "planner_mode": plan.metadata.get("planner_mode"),
                "degraded": bool(plan.metadata.get("degraded")),
                "degraded_reason": plan.metadata.get("degraded_reason"),
            },
        )
        try:
            self._apply_plan(run, plan)
            apply_ai_budget_metadata(run, dict(plan.metadata or {}), dict(runtime_context or {}))
            self._repo.save(run)
            if auto_execute:
                self._execute_ready_steps(run, runtime_context=dict(runtime_context or {}))
            return self._repo.save(run)
        except RECOVERABLE_ERRORS as exc:
            run.status = "failed"
            run.error = str(exc)
            run.add_event("run.failed", "Agent run 失败", {"error": str(exc)})
            return self._repo.save(run)

    def get_run(self, run_id: str) -> AgentRun | None:
        return self._repo.get(run_id)

    def execute_existing_run(
        self,
        run_id: str,
        *,
        control_check: Callable[[AgentRun], str | None] | None = None,
        worker_instance_id: str = "",
    ) -> AgentRun | None:
        """Continue a durable run from its latest completed checkpoint."""
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled", "blocked", "waiting_user", "paused"}:
            return run

        context = dict(run.metadata.get("runtime_context") or {})
        runtime = self._runtime_metadata(run)
        runtime["worker_instance_id"] = worker_instance_id
        runtime["queue_state"] = "running"
        if self._honor_control(run, control_check):
            return self._repo.get(run.run_id)

        try:
            if not run.plan_id:
                plan = self._plan(run, runtime_context=context)
                if self._honor_control(run, control_check):
                    return self._repo.get(run.run_id)
                self._apply_plan(run, plan)
                apply_ai_budget_metadata(run, dict(plan.metadata or {}), context)
                self._checkpoint(run, phase="planned")
                self._repo.save(run)
            if run.status == "blocked":
                self._checkpoint(run, phase="blocked")
                return self._repo.save(run)
            run.status = "running"
            approved_step_id = str(run.metadata.pop("approved_step_id", "") or "")
            self._execute_ready_steps(
                run,
                runtime_context=context,
                approved_step_id=approved_step_id,
                control_check=control_check,
            )
            phase = {
                "completed": "completed",
                "failed": "failed",
                "cancelled": "cancelled",
                "paused": "paused",
                "waiting_user": "waiting_user",
                "blocked": "blocked",
            }.get(run.status, "running")
            runtime = self._runtime_metadata(run)
            runtime["queue_state"] = run.status
            runtime["worker_finished_at"] = utc_now_iso()
            self._checkpoint(run, phase=phase)
            return self._repo.save(run)
        except RECOVERABLE_ERRORS as exc:
            run.status = "failed"
            run.error = str(exc)
            run.add_event("run.failed", "Agent run 失败", {"error": str(exc)})
            self._runtime_metadata(run)["queue_state"] = "failed"
            self._checkpoint(run, phase="failed")
            return self._repo.save(run)

    def continue_run(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        runtime_context: dict[str, Any] | None = None,
        auto_execute: bool = True,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None

        waiting_step = self._find_waiting_step(run, approved_step_id=approved_step_id)
        # A SQL-backed run can be observed at the durable ``pending`` snapshot
        # between plan persistence and the approval transition.  Route callers
        # pass an exact node/step id, so it is safe to resume that one pending
        # step instead of returning a false "still running" response.
        if waiting_step is None and str(approved_step_id or "").strip():
            wanted = str(approved_step_id).strip()
            waiting_step = next(
                (
                    step
                    for step in run.steps
                    if step.status == "pending" and wanted in {step.step_id, step.node_id}
                ),
                None,
            )
        if waiting_step is None:
            run.add_event(
                "run.continue_ignored",
                "没有等待确认的步骤",
                {"approved_by": approved_by, "approved_step_id": approved_step_id},
            )
            return self._repo.save(run)

        context = dict(run.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        run.metadata["runtime_context"] = context
        apply_ai_budget_metadata(run, context)
        waiting_step.status = "pending"
        run.status = "running"
        run.error = ""
        run.add_event(
            "step.approved",
            f"步骤 {waiting_step.node_id} 已确认继续",
            {
                "step_id": waiting_step.step_id,
                "node_id": waiting_step.node_id,
                "tool_id": waiting_step.tool_id,
                "action": waiting_step.action,
                "approved_by": approved_by,
            },
        )
        if auto_execute:
            self._execute_ready_steps(
                run,
                runtime_context=context,
                approved_step_id=waiting_step.step_id,
            )
        else:
            run.status = "queued"
            run.metadata["background_execution"] = True
            run.metadata["approved_step_id"] = waiting_step.step_id
            self._checkpoint(run, phase="approved")
        return self._repo.save(run)

    def list_runs(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        return self._repo.list_recent(user_id=user_id, limit=limit)

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]:
        return self._repo.list_events(run_id, after_event_id=after_event_id)

    def _plan(self, run: AgentRun, *, runtime_context: dict[str, Any]) -> PlanGraph:
        from app.application.agent_orchestrator.multimodal_planner import (
            build_multimodal_autonomous_plan,
        )
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry

        run.status = "planning"
        run.add_event("planner.started", "开始生成 Agent 计划")
        self._repo.save(run)

        context = dict(runtime_context or {})
        context.setdefault("message", run.message)
        multimodal_plan = build_multimodal_autonomous_plan(
            user_id=run.user_id,
            message=run.message,
            runtime_context=context,
        )
        if multimodal_plan is not None:
            run.add_event(
                "planner.completed",
                "多模态 Artifact 自主计划生成完成",
                {
                    "plan_id": multimodal_plan.plan_id,
                    "intent": multimodal_plan.intent,
                    "nodes": len(multimodal_plan.nodes),
                    "source": "multimodal_autonomous_planner",
                    "artifact_count": multimodal_plan.metadata.get("artifact_count", 0),
                },
            )
            return multimodal_plan

        planner = LLMWorkflowPlanner()
        plan = planner.plan(run.user_id, run.message, get_workflow_tool_registry(), context)
        if plan.metadata.get("degraded"):
            run.add_event(
                "planner.degraded",
                "LLM 规划不可用，已进入受限降级模式",
                {
                    "plan_id": plan.plan_id,
                    "intent": plan.intent,
                    "planner_mode": plan.metadata.get("planner_mode"),
                    "reason": plan.metadata.get("degraded_reason"),
                    "execution_policy": plan.metadata.get("execution_policy"),
                },
            )
        run.add_event(
            "planner.completed",
            "Agent 计划生成完成",
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "nodes": len(plan.nodes),
                "planner_mode": plan.metadata.get("planner_mode"),
                "degraded": bool(plan.metadata.get("degraded")),
            },
        )
        return plan

    def _apply_plan(self, run: AgentRun, plan: PlanGraph) -> None:
        run.plan_id = plan.plan_id
        run.intent = plan.intent
        run.metadata["plan"] = {
            "todo_steps": list(plan.todo_steps or []),
            "risk_level": plan.risk_level,
            "metadata": dict(plan.metadata or {}),
        }
        run.metadata["planner_mode"] = str(
            plan.metadata.get("planner_mode") or plan.metadata.get("planner") or "unknown"
        )
        run.metadata["degraded"] = bool(plan.metadata.get("degraded"))
        run.metadata["degraded_reason"] = str(plan.metadata.get("degraded_reason") or "")
        run.steps = [self._step_from_node(node) for node in plan.nodes]
        self._apply_repair_policy(run, dict(plan.metadata or {}))
        self._attach_artifacts_from_payload(
            run,
            getattr(plan, "metadata", {}) or {},
            source="plan.metadata",
        )
        self._refresh_artifact_metadata(run)
        run.status = "running" if run.steps else "blocked"
        if not run.steps:
            execution_policy = str(plan.metadata.get("execution_policy") or "")
            if execution_policy == "blocked_no_safe_action":
                run.error = "需要补充明确目标、对象或必要参数后才能执行"
                run.add_event("planner.blocked", "目标信息不足，未执行任何工具")
            else:
                run.error = "planner returned no executable steps"
                run.add_event("planner.blocked", "计划没有可执行节点")

    @staticmethod
    def _step_from_node(node: WorkflowNode) -> AgentStep:
        spec = get_tool_action_spec(node.tool_id, node.action)
        action = spec.action if spec is not None else node.action
        return AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=action,
            params=normalize_tool_call_params(node.tool_id, action, node.params),
            risk=spec.risk if spec is not None else str(node.risk or "low"),
            idempotent=bool(spec.idempotent) if spec is not None else bool(node.idempotent),
            description=str(node.description or ""),
            depends_on=list(node.depends_on or []),
        )

    @staticmethod
    def _find_waiting_step(
        run: AgentRun,
        *,
        approved_step_id: str = "",
    ) -> AgentStep | None:
        wanted = str(approved_step_id or "").strip()
        for step in run.steps:
            if step.status != "waiting_user":
                continue
            if wanted and wanted not in {step.step_id, step.node_id}:
                continue
            return step
        return None

    def _execute_ready_steps(
        self,
        run: AgentRun,
        *,
        runtime_context: dict[str, Any],
        approved_step_id: str = "",
        control_check: Callable[[AgentRun], str | None] | None = None,
    ) -> None:
        if not run.steps:
            run.status = "blocked"
            return

        approved = str(approved_step_id or "").strip()
        completed_node_ids: set[str] = {
            step.node_id for step in run.steps if step.status == "completed"
        }
        node_outputs: dict[str, Any] = {
            step.node_id: dict(step.output or {})
            for step in run.steps
            if step.status == "completed"
        }

        for step in run.steps:
            if self._honor_control(run, control_check):
                return
            if step.status == "completed":
                continue
            if any(dep not in completed_node_ids for dep in step.depends_on):
                run.status = "blocked"
                step.status = "skipped"
                step.error = "dependencies are not completed"
                run.add_event(
                    "step.blocked",
                    f"步骤 {step.node_id} 依赖未满足",
                    {"step_id": step.step_id, "depends_on": step.depends_on},
                )
                self._checkpoint(run, phase="blocked", current_step=step)
                self._repo.save(run)
                return

            step_is_approved = bool(approved and approved in {step.step_id, step.node_id})
            if not self._can_auto_execute(step) and not step_is_approved:
                step.status = "waiting_user"
                run.status = "waiting_user"
                run.add_event(
                    "step.waiting_user",
                    f"步骤 {step.node_id} 需要用户确认",
                    {
                        "step_id": step.step_id,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "risk": step.risk,
                        "idempotent": step.idempotent,
                    },
                )
                self._checkpoint(run, phase="waiting_user", current_step=step)
                self._repo.save(run)
                return

            while True:
                if self._honor_control(run, control_check):
                    return
                budget_payload = budget_exceeded_payload(
                    run,
                    additional_cost_units=self._step_cost_units(step),
                    scope=f"{step.tool_id}.{step.action}",
                )
                if budget_payload is not None:
                    self._mark_budget_exceeded(run, step, budget_payload, node_outputs=node_outputs)
                    return
                self._execute_step(
                    run, step, runtime_context=runtime_context, node_outputs=node_outputs
                )
                self._checkpoint(
                    run,
                    phase="step_completed" if step.status == "completed" else "step_failed",
                    current_step=step,
                )
                self._repo.save(run)
                if self._honor_control(run, control_check):
                    return
                if step.status == "completed":
                    break
                if self._prepare_repair_or_retry(run, step, runtime_context=runtime_context):
                    self._checkpoint(run, phase="retrying", current_step=step)
                    self._repo.save(run)
                    continue
                run.status = "failed"
                run.error = step.error or f"step {step.node_id} failed"
                self._refresh_run_cost_metadata(run)
                self._refresh_repair_metadata(run)
                run.final_output = {
                    "node_outputs": node_outputs,
                    "tool_calls": [call.to_dict() for call in run.tool_calls],
                    "artifacts": [artifact.to_dict() for artifact in run.artifacts],
                    "cost_units_total": run.metadata["cost_units_total"],
                    "ai_cost_units_total": run.metadata["ai_cost_units_total"],
                    "failed_step_id": step.step_id,
                    "error": run.error,
                    "repair_count": run.metadata.get("repair_count", 0),
                }
                self._attach_verification_summary(run)
                self._append_llm_summary_to_final_output(run)
                self._checkpoint(run, phase="failed", current_step=step)
                self._repo.save(run)
                return
            completed_node_ids.add(step.node_id)

        run.status = "completed"
        self._refresh_run_cost_metadata(run)
        self._refresh_repair_metadata(run)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": run.metadata["cost_units_total"],
            "ai_cost_units_total": run.metadata["ai_cost_units_total"],
            "repair_count": run.metadata.get("repair_count", 0),
        }
        verification_summary = self._attach_verification_summary(run)
        self._append_llm_summary_to_final_output(run)
        if verification_summary["status"] == "inconclusive":
            run.add_event(
                "run.verification_inconclusive",
                "Agent run 执行结束，但部分结果缺少独立业务回执",
                verification_summary,
            )
        run.add_event(
            "run.completed",
            (
                "Agent run 已执行并通过验收"
                if verification_summary["goal_verified"]
                else "Agent run 执行结束，结果待核验"
            ),
            run.final_output,
        )
        self._checkpoint(run, phase="completed")
        self._repo.save(run)

    def _honor_control(
        self,
        run: AgentRun,
        control_check: Callable[[AgentRun], str | None] | None,
    ) -> bool:
        if control_check is None:
            return False
        action = str(control_check(run) or "")
        runtime = self._runtime_metadata(run)
        if action == "cancel":
            run.status = "cancelled"
            run.error = ""
            runtime["cancel_requested"] = False
            runtime["queue_state"] = "cancelled"
            run.add_event("run.cancelled", "后台任务已取消")
            self._checkpoint(run, phase="cancelled")
            self._repo.save(run)
            return True
        if action == "pause":
            run.status = "paused"
            runtime["pause_requested"] = True
            runtime["queue_state"] = "paused"
            run.add_event("run.paused", "后台任务已暂停")
            self._checkpoint(run, phase="paused")
            self._repo.save(run)
            return True
        return False

    def _checkpoint(
        self,
        run: AgentRun,
        *,
        phase: str,
        current_step: AgentStep | None = None,
    ) -> None:
        checkpoint = run.metadata.get("checkpoint")
        checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
        sequence = int(checkpoint.get("sequence") or 0) + 1
        next_step = next(
            (step for step in run.steps if step.status not in {"completed", "skipped"}),
            None,
        )
        run.metadata["checkpoint"] = {
            "schema_version": "1.0",
            "sequence": sequence,
            "phase": str(phase),
            "saved_at": utc_now_iso(),
            "current_step_id": current_step.step_id if current_step is not None else "",
            "next_step_id": next_step.step_id if next_step is not None else "",
            "completed_step_ids": [
                step.step_id for step in run.steps if step.status == "completed"
            ],
            "last_event_id": run.events[-1].event_id if run.events else "",
        }

    @staticmethod
    def _runtime_metadata(run: AgentRun) -> dict[str, Any]:
        runtime = run.metadata.get("runtime")
        if not isinstance(runtime, dict):
            runtime = {}
            run.metadata["runtime"] = runtime
        runtime.setdefault("schema_version", "1.0")
        return runtime

    @staticmethod
    def _can_auto_execute(step: AgentStep) -> bool:
        return str(step.risk or "").lower() == "low" and bool(step.idempotent)

    def _execute_step(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
        node_outputs: dict[str, Any],
    ) -> None:
        started = time.perf_counter()
        normalized_params = normalize_tool_call_params(
            step.tool_id,
            step.action,
            step.params,
        )
        if normalized_params != step.params:
            step.params = normalized_params
            run.add_event(
                "step.params_normalized",
                f"步骤 {step.node_id} 参数已按工具契约规范化",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "tool_id": step.tool_id,
                    "action": step.action,
                },
            )
        step.attempt_count += 1
        step.status = "running"
        step.started_at = utc_now_iso()
        run.status = "running"
        attempt_count = step.attempt_count
        spec = get_tool_action_spec(step.tool_id, step.action)
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
        self._refresh_run_cost_metadata(run)
        orchestration = build_orchestration_evidence(
            step.tool_id,
            step.action,
            step.params,
            runtime_context=runtime_context,
            status="running",
        )
        tool_call.metadata["orchestration"] = orchestration
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
                "orchestration": orchestration,
            },
        )
        self._repo.save(run)

        ctx = dict(runtime_context or {})
        ctx.update(
            {
                "run_id": run.run_id,
                "step_id": step.step_id,
                "node_id": step.node_id,
                "message": run.message,
                "user_id": run.user_id,
                "node_outputs": dict(node_outputs),
            }
        )
        validation = validate_tool_call(step.tool_id, step.action, step.params)
        if not validation.ok:
            output = {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        elif not self._record_tool_usage_entry(run, tool_call):
            output = {
                "success": False,
                "error_code": "tool_billing_blocked",
                "message": run.error or "AI tool billing failed",
                "tool_id": step.tool_id,
                "action": step.action,
            }
        else:
            try:
                output = self._tool_executor.execute(step, runtime_context=ctx)
            except RECOVERABLE_ERRORS as exc:
                output = {
                    "success": False,
                    "error_code": "tool_exception",
                    "message": str(exc),
                }
        step.output = dict(output or {})
        step.finished_at = utc_now_iso()
        step.duration_ms = int((time.perf_counter() - started) * 1000)
        tool_call.output = copy.deepcopy(step.output)
        tool_call.finished_at = step.finished_at
        tool_call.duration_ms = step.duration_ms
        verification = verify_tool_execution(
            step.tool_id,
            step.action,
            step.params,
            step.output,
        )
        verification_payload = verification.to_dict()
        tool_call.metadata["verification"] = verification_payload
        if not verification.accepted:
            raw_output = copy.deepcopy(step.output)
            step.output = {
                "success": False,
                "error_code": "semantic_verification_failed",
                "message": verification.reason,
                "raw_success": raw_output.get("success"),
                "raw_output": raw_output,
                "verification": verification_payload,
            }
            tool_call.output = copy.deepcopy(step.output)
        completed_status = "completed" if bool(step.output.get("success", False)) else "failed"
        orchestration = build_orchestration_evidence(
            step.tool_id,
            step.action,
            step.params,
            step.output,
            runtime_context,
            status=completed_status,
        )
        tool_call.metadata["orchestration"] = orchestration
        self._attach_artifacts_from_payload(
            run,
            step.output,
            source=f"{step.tool_id}.{step.action}",
            extra_metadata={"step_id": step.step_id, "call_id": tool_call.call_id},
        )
        success = bool(step.output.get("success", False))
        observation = self._record_observation(
            run,
            step,
            tool_call=tool_call,
            success=success,
        )
        run.add_event(
            (
                "verification.verified"
                if verification.verified
                else "verification.failed"
                if not verification.accepted
                else "verification.inconclusive"
            ),
            verification.reason,
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "verification": verification_payload,
            },
        )
        if success:
            step.status = "completed"
            tool_call.status = "completed"
            self._refresh_run_cost_metadata(run)
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
                    "orchestration": orchestration,
                    "verification": verification_payload,
                },
            )
            return

        step.status = "failed"
        step.error = str(step.output.get("message") or step.output.get("error") or "tool failed")
        tool_call.status = "failed"
        tool_call.error = step.error
        if str(step.output.get("error_code") or "") != "tool_billing_blocked":
            self._record_tool_usage_refund(run, tool_call, reason=step.error)
        self._refresh_run_cost_metadata(run)
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
                "orchestration": orchestration,
                "verification": verification_payload,
            },
        )

    def _record_tool_usage_entry(self, run: AgentRun, tool_call: ToolCall) -> bool:
        if tool_call.cost_units <= 0:
            tool_call.metadata["usage_ledger"] = {"status": "not_required", "cost_units": 0}
            return True
        if isinstance(tool_call.metadata.get("usage_ledger"), dict):
            return True
        try:
            from app.infrastructure.billing.model_usage import record_tool_usage

            entry = record_tool_usage(
                run_id=run.run_id,
                user_id=run.user_id,
                tool_id=tool_call.tool_id,
                action=tool_call.action,
                call_id=tool_call.call_id,
                permission=tool_call.permission,
                status="pre_execution",
                cost_units=tool_call.cost_units,
                source="agent_orchestrator.tool_call",
                usage_key=f"{run.run_id}:{tool_call.call_id}:tool_call",
                metadata={
                    "step_id": tool_call.step_id,
                    "node_id": tool_call.node_id,
                    "attempt_count": tool_call.metadata.get("attempt_count"),
                    "risk": tool_call.metadata.get("risk"),
                    "idempotent": tool_call.metadata.get("idempotent"),
                },
            )
        except RECOVERABLE_ERRORS as exc:
            tool_call.metadata["usage_ledger"] = {"status": "failed", "message": str(exc)}
            run.metadata["tool_usage_ledger_status"] = "failed"
            run.add_event(
                "billing.record_failed",
                "工具调用用量账本写入失败",
                {
                    "call_id": tool_call.call_id,
                    "tool_id": tool_call.tool_id,
                    "action": tool_call.action,
                    "cost_units": tool_call.cost_units,
                    "error": str(exc),
                },
            )
            return True

        tool_call.metadata["usage_ledger"] = {
            "usage_id": entry.get("usage_id"),
            "usage_key": entry.get("usage_key"),
            "entry_type": entry.get("entry_type"),
            "status": "recorded",
        }
        wallet_debit = (
            entry.get("wallet_debit") if isinstance(entry.get("wallet_debit"), dict) else {}
        )
        if wallet_debit:
            tool_call.metadata["wallet_debit"] = wallet_debit
        tool_call.metadata["billing_status"] = entry.get("billing_status")
        tool_call.metadata["billing_source"] = entry.get("billing_source")
        self._refresh_tool_usage_metadata(run, entry)

        event_payload = {
            "usage_id": entry.get("usage_id"),
            "call_id": tool_call.call_id,
            "tool_id": tool_call.tool_id,
            "action": tool_call.action,
            "cost_units": entry.get("cost_units"),
            "billing_status": entry.get("billing_status"),
            "billing_source": entry.get("billing_source"),
            "wallet_debit": wallet_debit,
            "source": "agent_orchestrator.tool_call",
        }
        billing_status = str(entry.get("billing_status") or "")
        if billing_status == "debited":
            self._refresh_wallet_balance_metadata(run, wallet_debit)
            run.add_event("billing.debited", "工具调用用量已从 AI 钱包扣减", event_payload)
            return True
        if billing_status == "insufficient_balance":
            self._refresh_wallet_balance_metadata(run, wallet_debit)
            run.status = "failed"
            run.error = "AI tool wallet balance insufficient"
            run.add_event("billing.insufficient_balance", run.error, event_payload)
            return False
        if billing_status == "market_debit_failed":
            run.status = "failed"
            run.error = "AI tool market wallet debit failed"
            run.add_event("billing.debit_failed", run.error, event_payload)
            return False
        run.add_event("billing.recorded", "工具调用用量已写入 AI 账本", event_payload)
        return True

    def _record_tool_usage_refund(
        self,
        run: AgentRun,
        tool_call: ToolCall,
        *,
        reason: str,
    ) -> None:
        usage_ledger = (
            tool_call.metadata.get("usage_ledger")
            if isinstance(tool_call.metadata.get("usage_ledger"), dict)
            else {}
        )
        usage_key = str(usage_ledger.get("usage_key") or "")
        if not usage_key or isinstance(tool_call.metadata.get("wallet_refund"), dict):
            return
        try:
            from app.infrastructure.billing.model_usage import refund_tool_usage

            entry = refund_tool_usage(
                usage_key=usage_key,
                refund_key=f"{usage_key}:refund",
                reason=reason,
            )
        except RECOVERABLE_ERRORS as exc:
            tool_call.metadata["wallet_refund"] = {"status": "failed", "message": str(exc)}
            run.add_event(
                "billing.refund_failed",
                "工具调用失败补偿记录失败",
                {
                    "call_id": tool_call.call_id,
                    "tool_id": tool_call.tool_id,
                    "action": tool_call.action,
                    "usage_key": usage_key,
                    "error": str(exc),
                },
            )
            return
        refund = entry.get("refund") if isinstance(entry.get("refund"), dict) else {}
        if not refund:
            return
        tool_call.metadata["wallet_refund"] = refund
        self._refresh_tool_refund_metadata(run, refund)
        self._refresh_wallet_balance_metadata(run, refund)
        status = str(refund.get("status") or "")
        event_type = (
            "billing.refunded"
            if status == "refunded"
            else "billing.refund_pending"
            if status == "refund_pending"
            else "billing.refund_recorded"
        )
        run.add_event(
            event_type,
            "工具调用失败已记录补偿",
            {
                "call_id": tool_call.call_id,
                "tool_id": tool_call.tool_id,
                "action": tool_call.action,
                "usage_key": usage_key,
                "refund_status": status,
                "cost_units": refund.get("cost_units"),
                "wallet_refund": refund,
            },
        )

    @staticmethod
    def _refresh_wallet_balance_metadata(run: AgentRun, wallet_debit: dict[str, Any]) -> None:
        if "balance_after_units" in wallet_debit:
            run.metadata["model_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
            run.metadata["ai_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
        if "balance_after_yuan" in wallet_debit:
            run.metadata["model_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")
            run.metadata["ai_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")

    @staticmethod
    def _refresh_tool_usage_metadata(run: AgentRun, entry: dict[str, Any]) -> None:
        run.metadata["tool_usage_entry_count"] = (
            int(run.metadata.get("tool_usage_entry_count") or 0) + 1
        )
        run.metadata["tool_usage_cost_units_total"] = int(
            run.metadata.get("tool_usage_cost_units_total") or 0
        ) + int(entry.get("cost_units") or 0)
        run.metadata["tool_usage_ledger_status"] = "recorded"

    @staticmethod
    def _refresh_tool_refund_metadata(run: AgentRun, refund: dict[str, Any]) -> None:
        run.metadata["tool_usage_refund_count"] = (
            int(run.metadata.get("tool_usage_refund_count") or 0) + 1
        )
        if str(refund.get("status") or "") == "refunded":
            run.metadata["tool_usage_refund_cost_units_total"] = int(
                run.metadata.get("tool_usage_refund_cost_units_total") or 0
            ) + int(refund.get("cost_units") or 0)
        run.metadata["tool_usage_refund_status"] = str(refund.get("status") or "")

    @staticmethod
    def _cost_units_total(run: AgentRun) -> int:
        return sum(int(call.cost_units or 0) for call in run.tool_calls)

    @staticmethod
    def _step_cost_units(step: AgentStep) -> int:
        spec = get_tool_action_spec(step.tool_id, step.action)
        try:
            return int(getattr(spec, "cost_units", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _refresh_run_cost_metadata(self, run: AgentRun) -> None:
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = self._cost_units_total(run)
        run.metadata["ai_cost_units_total"] = int(run.metadata["cost_units_total"]) + int(
            run.metadata.get("llm_cost_units_total") or 0
        )
        refresh_ai_budget_metadata(run)

    def _mark_budget_exceeded(
        self,
        run: AgentRun,
        step: AgentStep,
        payload: dict[str, Any],
        *,
        node_outputs: dict[str, Any],
    ) -> None:
        step.status = "failed"
        step.error = str(payload.get("message") or "AI cost budget exceeded")
        run.status = "failed"
        run.error = step.error
        self._refresh_run_cost_metadata(run)
        run.metadata["ai_cost_budget_exceeded"] = True
        self._refresh_repair_metadata(run)
        payload = dict(payload)
        payload["step_id"] = step.step_id
        payload["node_id"] = step.node_id
        payload["tool_id"] = step.tool_id
        payload["action"] = step.action
        run.add_event("budget.exceeded", step.error, payload)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": run.metadata["cost_units_total"],
            "ai_cost_units_total": run.metadata["ai_cost_units_total"],
            "ai_cost_budget_units": run.metadata.get("ai_cost_budget_units"),
            "ai_cost_budget_remaining_units": run.metadata.get("ai_cost_budget_remaining_units"),
            "ai_cost_budget_exceeded": True,
            "failed_step_id": step.step_id,
            "error": run.error,
            "repair_count": run.metadata.get("repair_count", 0),
        }
        self._attach_verification_summary(run)
        self._append_llm_summary_to_final_output(run)

    @staticmethod
    def _attach_verification_summary(run: AgentRun) -> dict[str, Any]:
        summary = summarize_run_verification(run.tool_calls)
        run.metadata.update(summary)
        if isinstance(run.final_output, dict):
            run.final_output["verification"] = dict(summary)
            run.final_output["goal_verified"] = bool(summary["goal_verified"])
            verification_by_step = {
                str(call.step_id): dict(call.metadata.get("verification") or {})
                for call in run.tool_calls
                if isinstance(call.metadata, dict)
            }
            ledger = {
                "schema_version": "1.0",
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "goal": run.message,
                "intent": run.intent,
                "planner_mode": run.metadata.get("planner_mode"),
                "degraded": bool(run.metadata.get("degraded")),
                "status": run.status,
                "goal_verified": bool(summary["goal_verified"]),
                "verification_status": summary["status"],
                "steps": [
                    {
                        "step_id": step.step_id,
                        "node_id": step.node_id,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "status": step.status,
                        "attempt_count": step.attempt_count,
                        "verification": verification_by_step.get(step.step_id, {}),
                        "error": step.error,
                    }
                    for step in run.steps
                ],
            }
            run.final_output["task_ledger"] = ledger
            run.metadata["task_ledger_schema_version"] = "1.0"
            run.add_event(
                "ledger.updated",
                "任务账本已更新",
                {
                    "goal_verified": ledger["goal_verified"],
                    "verification_status": ledger["verification_status"],
                    "step_count": len(ledger["steps"]),
                    "degraded": ledger["degraded"],
                },
            )
        return summary

    def _record_observation(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        tool_call: ToolCall,
        success: bool,
    ) -> dict[str, Any]:
        output_message = str(step.output.get("message") or "")
        output_error = str(
            step.output.get("message")
            or step.output.get("error")
            or step.output.get("error_code")
            or ""
        )
        observation = {
            "observation_id": f"obs_{tool_call.call_id}",
            "step_id": step.step_id,
            "node_id": step.node_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "call_id": tool_call.call_id,
            "attempt_count": step.attempt_count,
            "success": success,
            "message": output_message,
            "error": "" if success else output_error,
            "status": "completed" if success else "failed",
            "verification": copy.deepcopy(
                tool_call.metadata.get("verification")
                if isinstance(tool_call.metadata.get("verification"), dict)
                else {}
            ),
        }
        step.observations.append(observation)
        run.metadata["observation_count"] = sum(len(item.observations) for item in run.steps)
        run.add_event(
            "observation.recorded",
            f"记录 {step.node_id} 执行观察",
            observation,
        )
        return observation

    @staticmethod
    def _coerce_positive_int(value: Any) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    def _apply_repair_policy(self, run: AgentRun, plan_metadata: dict[str, Any]) -> None:
        repair_policy = plan_metadata.get("repair_policy")
        repair_policy = repair_policy if isinstance(repair_policy, dict) else {}
        global_limit = self._coerce_positive_int(
            repair_policy.get("max_attempts") or plan_metadata.get("max_repair_attempts")
        )
        overrides = plan_metadata.get("repair_overrides")
        overrides = overrides if isinstance(overrides, dict) else {}
        for step in run.steps:
            node_policy = repair_policy.get(step.node_id)
            node_policy = node_policy if isinstance(node_policy, dict) else {}
            node_limit = self._coerce_positive_int(node_policy.get("max_attempts"))
            has_override = self._repair_override_for_step(step, overrides) is not None
            has_llm_repair = is_llm_repair_enabled(run, plan_metadata)
            step.max_repair_attempts = (
                node_limit or global_limit or (1 if has_override or has_llm_repair else 0)
            )
