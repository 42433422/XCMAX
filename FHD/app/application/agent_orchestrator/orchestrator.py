"""Public agent-run lifecycle composed from planning, execution, usage and repair services."""

from __future__ import annotations

import logging
from typing import Any, cast

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.budget import (
    apply_ai_budget_metadata,
    budget_exceeded_payload,
    refresh_ai_budget_metadata,
)
from app.application.agent_orchestrator.clarification import (
    find_waiting_step,
    pause_for_clarification,
)
from app.application.agent_orchestrator.param_references import refuse_unresolved_step
from app.application.agent_orchestrator.repair_advisor import (
    is_llm_repair_enabled,
    llm_repair_attempt_limit,
    request_llm_repair,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, RunEvent, ToolCall
from app.application.agent_orchestrator.run_planning import RunPlanning
from app.application.agent_orchestrator.run_repair import RunRepair
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    SQLAlchemyAgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.task_background import AgentOrchestratorTaskMixin
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_to_dict,
    skip_unselected_step,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_INTERNAL_RUN_ERROR = "agent_run_internal_error"


def _verified_catalog_terminal(run: AgentRun, step: AgentStep) -> dict[str, Any] | None:
    """A terminal receipt is not permission to replay a non-retryable operation."""
    output = step.output
    recovery = run.metadata.get("recovery")
    if (
        len(run.steps) != 1
        or run.steps[0] is not step
        or step.tool_id != "catalog_products_v1"
        or step.action not in {"append_price", "correct_price"}
        or not isinstance(step.params, dict)
        or step.params.get("action") != step.action
        or not isinstance(output, dict)
        or not isinstance(output.get("outcome"), str)
        or not isinstance(output.get("operation_outcome"), str)
        or not isinstance(run.metadata.get("catalog_price_binding"), dict)
        or not isinstance(run.metadata.get("runtime_context"), dict)
        or type(output.get("fresh_save")) is not bool
        or any(
            type(output.get(key)) is not bool
            for key in ("success", "historical_effect_verified", "current_matches")
        )
        or (
            output.get("outcome"),
            output.get("operation_outcome"),
            output.get("success"),
            output.get("historical_effect_verified"),
            output.get("current_matches"),
        )
        not in {
            ("success", "saved", True, True, True),
            ("historical_saved", "saved", False, True, False),
            ("rejected_no_effect", "rejected_no_effect", False, False, False),
        }
        or (output.get("success") is False and output.get("fresh_save") is not False)
        or step.status != ("completed" if output.get("success") is True else "failed")
        or output.get("retryable") is not False
        or not isinstance(output.get("message"), str)
        or not output.get("message")
        or output.get("reconciliation_required")
        or output.get("error")
        or output.get("error_code")
        or (recovery is not None and not isinstance(recovery, dict))
        or (
            isinstance(recovery, dict) and recovery.get("state") == "manual_reconciliation_required"
        )
        or output.get("business_action_id") != f"agent:{run.run_id}:{step.step_id}"
        or output.get("data")
        != {"id": step.params.get("product_id"), "operation_id": step.params.get("operation_id")}
        or len(run.tool_calls) != 1
    ):
        return None
    verification = output.get("business_verification")
    data = output.get("data")
    if (
        not isinstance(verification, dict)
        or verification.get("verified") is not True
        or verification.get("source_binding_verified") is not True
        or not isinstance(data, dict)
        or type(data.get("id")) is not int
        or not isinstance(data.get("operation_id"), str)
    ):
        return None
    call = run.tool_calls[0]
    if (
        (call.step_id, call.node_id, call.tool_id, call.action, call.params)
        != (step.step_id, step.node_id, step.tool_id, step.action, step.params)
        or call.status != step.status
        or call.output != output
    ):
        return None
    try:
        from app.application.agent_orchestrator.catalog_product_edit import (
            action_context,
            original,
            principal_from_context,
        )
        from app.mod_sdk.catalog_product_store import source_view, verify_catalog_action

        if output.get("business_verification") != {
            "verified": True,
            "method": "catalog_price_receipt_v1",
            "source_binding_verified": True,
            **source_view(run.metadata["catalog_price_binding"]),
        }:
            return None
        context = action_context(run)
        stored, claim, state = original(
            principal_from_context(context), step.params["operation_id"]
        )
        if (
            state != ("verified" if output["operation_outcome"] == "saved" else "rejected")
            or (stored.run_id, stored.user_id, stored.steps[0].step_id)
            != (run.run_id, run.user_id, step.step_id)
            or claim["binding"] != run.metadata["catalog_price_binding"]
            or claim["operation_digest"] != run.metadata.get("catalog_operation_digest")
        ):
            return None
        # Pure independent readback re-joins the signed original run/step/approval,
        # ledger owner and source receipt. Never release a head or dispatch here.
        verified = verify_catalog_action(step.params, context)
        if not all(
            output.get(key) == verified.get(key)
            for key in (
                "operation_outcome",
                "historical_effect_verified",
                "retryable",
                "data",
                "business_action_id",
                "business_verification",
            )
        ) or verified.get("reconciliation_required"):
            return None
        if all(
            output.get(key) == verified.get(key)
            for key in ("success", "outcome", "current_matches")
        ):
            return output
        # A concurrent later legitimate edit can make a just-saved receipt
        # historical. Keep the verified original outcome but never claim a fresh
        # current save from that stale projection.
        if output["outcome"] == "success" and verified.get("outcome") == "historical_saved":
            return verified
        return None
    except RECOVERABLE_ERRORS:
        return None


def _runtime_dependencies() -> RuntimeDependencies:
    # Keep the public module's established patch points at the composition root.
    # Components receive explicit ports and never import this module back.
    return RuntimeDependencies(
        action_spec=lambda tool, action: get_tool_action_spec(tool, action),
        validate=lambda tool, action, params: validate_tool_call(tool, action, params),
        refresh_budget=lambda run: refresh_ai_budget_metadata(run),
        repair_enabled=lambda run, context: is_llm_repair_enabled(run, context),
        repair_limit=lambda run, step, context: llm_repair_attempt_limit(run, step, context),
        request_repair=lambda run, step, context: request_llm_repair(run, step, context),
    )


class AgentOrchestrator(AgentOrchestratorTaskMixin):
    def __init__(
        self,
        *,
        repository: AgentRunRepository | None = None,
        tool_executor: AgentToolExecutor | None = None,
        dependencies: RuntimeDependencies | None = None,
    ) -> None:
        self._repo = repository or get_agent_run_repository()
        self._repository_status = {
            "mode": "sqlalchemy"
            if isinstance(self._repo, SQLAlchemyAgentRunRepository)
            else "memory",
            "durable": isinstance(self._repo, SQLAlchemyAgentRunRepository),
        }
        self._tool_executor = tool_executor or AgentToolExecutor()
        runtime = dependencies if dependencies is not None else _runtime_dependencies()
        self._planning = RunPlanning(self._repo)
        self._usage = RunUsageLedger(runtime)
        self._repair = RunRepair(self._repo, self._usage, runtime)
        self._step_execution = StepExecution(
            self._repo,
            self._tool_executor,
            self._usage,
            runtime,
            attach_artifacts=self._attach_artifacts_from_payload,
            observe=self._record_observation,
        )

    _find_waiting_step = staticmethod(find_waiting_step)

    @staticmethod
    def _ingest_artifact_to_dataset(run: AgentRun, artifact: Any) -> None:
        ingest_artifact_to_dataset(run, artifact)

    def start_run(
        self,
        *,
        user_id: str,
        message: str,
        runtime_context: dict[str, Any] | None = None,
        auto_execute: bool = True,
    ) -> AgentRun:
        run = AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        run.metadata["persistence"] = dict(self._repository_status)
        run.metadata["runtime_context"] = dict(runtime_context or {})
        apply_task_context(run, runtime_context)
        run.add_event("run.created", "Agent run 已创建")
        self._repo.save(run)
        try:
            plan = self._plan(run, runtime_context=dict(runtime_context or {}))
            self._apply_plan(run, plan)
            apply_ai_budget_metadata(run, dict(plan.metadata or {}), dict(runtime_context or {}))
            self._repo.save(run)
            if auto_execute:
                self._execute_with_durable_lease(run, runtime_context=dict(runtime_context or {}))
            return cast("AgentRun", self._repo.save(run))
        except RECOVERABLE_ERRORS:
            logger.exception("agent run start failed")
            run.status = "failed"
            run.error = _INTERNAL_RUN_ERROR
            run.add_event("run.failed", "Agent run 失败", {"error_code": _INTERNAL_RUN_ERROR})
            return cast("AgentRun", self._repo.save(run))

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
        run.metadata["persistence"] = dict(self._repository_status)
        run.metadata["runtime_context"] = dict(runtime_context or {})
        apply_task_context(run, runtime_context)
        run.add_event("run.created", "Agent run 已创建")
        run.add_event(
            "planner.completed",
            "Agent 计划已接管",
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "nodes": len(plan.nodes),
                "source": "provided_plan",
            },
        )
        try:
            self._apply_plan(run, plan)
            apply_ai_budget_metadata(run, dict(plan.metadata or {}), dict(runtime_context or {}))
            self._repo.save(run)
            if auto_execute:
                self._execute_with_durable_lease(run, runtime_context=dict(runtime_context or {}))
            return cast("AgentRun", self._repo.save(run))
        except RECOVERABLE_ERRORS:
            logger.exception("agent run from plan failed")
            run.status = "failed"
            run.error = _INTERNAL_RUN_ERROR
            run.add_event("run.failed", "Agent run 失败", {"error_code": _INTERNAL_RUN_ERROR})
            return cast("AgentRun", self._repo.save(run))

    def continue_run(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        waiting_step = self._find_waiting_step(run, approved_step_id=approved_step_id)
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
            return cast("AgentRun | None", self._repo.save(run))
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
        self._execute_with_durable_lease(
            run, runtime_context=context, approved_step_id=waiting_step.step_id
        )
        return cast("AgentRun | None", self._repo.save(run))

    def list_runs(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        return cast("list[AgentRun]", self._repo.list_recent(user_id=user_id, limit=limit))

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]:
        return cast("list[RunEvent]", self._repo.list_events(run_id, after_event_id=after_event_id))

    def _apply_plan(self, run: AgentRun, plan: PlanGraph) -> None:
        run.plan_id = plan.plan_id
        run.intent = plan.intent
        plan_metadata = dict(plan.metadata or {})
        run.metadata["plan"] = plan_to_dict(plan)
        self._attach_memory_recall(run, plan_metadata.get("memory_recall"))
        from app.application.workflow.workflow_types import step_plan_nodes

        nodes, graph_error = step_plan_nodes(plan)
        run.steps = [self._step_from_node(node) for node in nodes]
        if graph_error:
            run.status = "blocked"
            run.error = graph_error
            run.add_event("planner.blocked", graph_error)
            return
        self._apply_repair_policy(run, plan_metadata)
        self._attach_artifacts_from_payload(run, plan_metadata, source="plan.metadata")
        self._refresh_artifact_metadata(run)
        run.status = "running" if run.steps else "blocked"
        if not run.steps:
            from app.application.workflow.sql_execution_policy import REFUSAL_CODE, REFUSAL_MESSAGE

            refused = plan_metadata.get("refusal_code") == REFUSAL_CODE
            run.error = REFUSAL_CODE if refused else "planner returned no executable steps"
            if refused:
                run.final_output = {"message": REFUSAL_MESSAGE, "refusal_code": REFUSAL_CODE}
            run.add_event("planner.blocked", "计划没有可执行节点")

    @staticmethod
    def _step_from_node(node: WorkflowNode) -> AgentStep:
        spec = get_tool_action_spec(node.tool_id, node.action)
        return AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=spec.action if spec is not None else node.action,
            params=dict(node.params or {}),
            risk=spec.risk if spec is not None else str(node.risk or "low"),
            idempotent=bool(spec.idempotent) if spec is not None else bool(node.idempotent),
            description=str(node.description or ""),
            depends_on=list(node.depends_on or []),
        )

    def _execute_ready_steps(
        self,
        run: AgentRun,
        *,
        runtime_context: dict[str, Any],
        approved_step_id: str = "",
    ) -> None:
        if not run.steps:
            run.status = "blocked"
            run.error = run.error or "planner returned no executable steps"
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
            if self._apply_requested_control(run):
                return
            if step.status == "completed" or skip_unselected_step(run, step):
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
                return
            if refuse_unresolved_step(run, step, node_outputs):
                return
            if pause_for_clarification(run, step, node_outputs):
                return
            step_is_approved = bool(approved and approved in {step.step_id, step.node_id})
            if not self._can_auto_execute(step) and (not step_is_approved):
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
                return
            while True:
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
                if run.metadata.get("non_retryable"):
                    terminal = _verified_catalog_terminal(run, step)
                    if terminal is None:
                        run.status = "blocked"
                        run.error = step.error
                        return
                    # Complete only this one-step receipt consumer, not another
                    # business effect. Rejections/history remain unsuccessful
                    # business outputs while the workflow itself is terminal.
                    # Preserve immutable executed step/call facts. A later READ
                    # observation belongs in the final projection, not over the
                    # original successful receipt or its completed status.
                    node_outputs[step.node_id] = dict(terminal)
                    if self._apply_requested_control(run):
                        return
                    break
                if self._apply_requested_control(run):
                    return
                if step.status == "completed":
                    break
                if self._prepare_repair_or_retry(run, step, runtime_context=runtime_context):
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
                self._append_llm_summary_to_final_output(run)
                self._remember_run_outcome_for(run)
                return
            completed_node_ids.add(step.node_id)
        run.status = "completed"
        self._ingest_confirmed_plan_artifacts(run)
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
        self._append_llm_summary_to_final_output(run)
        self._remember_run_outcome_for(run)
        run.add_event("run.completed", "Agent run 执行完成", run.final_output)

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
        self._append_llm_summary_to_final_output(run)

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
        }
        step.observations.append(observation)
        run.metadata["observation_count"] = sum(len(item.observations) for item in run.steps)
        run.add_event("observation.recorded", f"记录 {step.node_id} 执行观察", observation)
        return observation

    def _plan(self, run: AgentRun, *, runtime_context: dict[str, Any]) -> PlanGraph:
        return self._planning.plan(run, runtime_context=runtime_context)

    def _recall_knowledge_for_run(self, run: AgentRun, *, context: dict[str, Any]) -> None:
        return self._planning.recall_knowledge_for_run(run, context=context)

    _attach_memory_recall = staticmethod(RunPlanning.attach_memory_recall)

    def _remember_run_outcome_for(self, run: AgentRun) -> None:
        return self._planning.remember_run_outcome_for(run)

    _run_outcome_summary = staticmethod(RunPlanning.run_outcome_summary)

    def _record_tool_usage_entry(self, run: AgentRun, tool_call: ToolCall) -> bool:
        return self._usage.record_tool_usage_entry(run, tool_call)

    def _record_tool_usage_refund(self, run: AgentRun, tool_call: ToolCall, *, reason: str) -> None:
        return self._usage.record_tool_usage_refund(run, tool_call, reason=reason)

    _refresh_wallet_balance_metadata = staticmethod(RunUsageLedger.refresh_wallet_balance_metadata)

    _refresh_tool_usage_metadata = staticmethod(RunUsageLedger.refresh_tool_usage_metadata)

    _refresh_tool_refund_metadata = staticmethod(RunUsageLedger.refresh_tool_refund_metadata)

    _cost_units_total = staticmethod(RunUsageLedger.cost_units_total)

    def _step_cost_units(self, step: AgentStep) -> int:
        return self._usage.step_cost_units(step)

    def _refresh_run_cost_metadata(self, run: AgentRun) -> None:
        return self._usage.refresh_run_cost_metadata(run)

    def _record_repair_llm_call(
        self, run: AgentRun, step: AgentStep, advice: dict[str, Any]
    ) -> bool:
        return self._usage.record_repair_llm_call(run, step, advice)

    _refresh_model_usage_metadata = staticmethod(RunUsageLedger.refresh_model_usage_metadata)

    def _refresh_llm_metadata(self, run: AgentRun) -> None:
        return self._usage.refresh_llm_metadata(run)

    _append_llm_summary_to_final_output = staticmethod(
        RunUsageLedger.append_llm_summary_to_final_output
    )

    _refresh_repair_metadata = staticmethod(RunUsageLedger.refresh_repair_metadata)

    def _prepare_repair_or_retry(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> bool:
        return self._repair.prepare_repair_or_retry(run, step, runtime_context=runtime_context)

    def _prepare_llm_repair_or_retry(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> bool:
        return self._repair.prepare_llm_repair_or_retry(run, step, runtime_context=runtime_context)

    _coerce_positive_int = staticmethod(RunRepair.coerce_positive_int)

    def _apply_repair_policy(self, run: AgentRun, plan_metadata: dict[str, Any]) -> None:
        return self._repair.apply_repair_policy(run, plan_metadata)

    _repair_override_for_step = staticmethod(RunRepair.repair_override_for_step)

    def _repair_sources(
        self, run: AgentRun, runtime_context: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        return self._repair.repair_sources(run, runtime_context)

    _params_patch_from_repair = staticmethod(RunRepair.params_patch_from_repair)

    _can_auto_execute = staticmethod(RunRepair.can_auto_execute)

    def _execute_step(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
        node_outputs: dict[str, Any],
    ) -> None:
        return self._step_execution.execute_step(
            run, step, runtime_context=runtime_context, node_outputs=node_outputs
        )
