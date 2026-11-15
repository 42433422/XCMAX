"""Public agent-run lifecycle composed from planning, execution, usage and repair services."""

from __future__ import annotations

import copy
import logging
from typing import Any, cast

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.budget import (
    apply_ai_budget_metadata,
    budget_exceeded_payload,
    refresh_ai_budget_metadata,
)
from app.application.agent_orchestrator.clarification import (
    apply_clarification_answer,
    find_waiting_step,
    pause_for_clarification,
)
from app.application.agent_orchestrator.param_references import refuse_unresolved_step
from app.application.agent_orchestrator.repair_advisor import (
    is_llm_repair_enabled,
    llm_repair_attempt_limit,
    request_llm_repair,
)
from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    RunEvent,
    ToolCall,
    utc_now_iso,
)
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
    plan_from_dict,
    plan_to_dict,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_INTERNAL_RUN_ERROR = "agent_run_internal_error"


def _authorized_step_matches_plan(run: AgentRun, step: AgentStep) -> bool:
    """The frozen plan is the authorization. A later param or dependency edit cannot reuse it."""
    stored = run.metadata.get("plan")
    if not isinstance(stored, dict):
        return True
    nodes = stored.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return True
    node = next(
        (item for item in nodes if isinstance(item, dict) and item.get("node_id") == step.node_id),
        None,
    )
    if not isinstance(node, dict):
        return False
    return (
        node.get("tool_id") == step.tool_id
        and node.get("action") == step.action
        and dict(node.get("params") or {}) == dict(step.params or {})
        and list(node.get("depends_on") or []) == list(step.depends_on or [])
    )


def _mark_prior_effects_for_reconciliation(run: AgentRun, error_code: str) -> list[str]:
    """Prevent replay when a resumed graph is rejected after unsafe work completed."""
    unsafe: list[str] = []
    for step in run.steps:
        if step.status != "completed":
            continue
        spec = get_tool_action_spec(step.tool_id, step.action)
        if not step.idempotent or spec is None or spec.idempotent is not True:
            unsafe.append(step.step_id)
    if not unsafe:
        return []
    previous = run.metadata.get("recovery")
    previous_ids = (
        previous.get("step_ids", [])
        if isinstance(previous, dict) and previous.get("state") == "manual_reconciliation_required"
        else []
    )
    unsafe = sorted({str(item) for item in (*previous_ids, *unsafe) if str(item)})
    run.metadata["non_retryable"] = True
    run.metadata["recovery"] = {
        "state": "manual_reconciliation_required",
        "error_code": str(error_code or "workflow_plan_rejected"),
        "step_ids": unsafe,
    }
    return unsafe


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
        context = dict(runtime_context or {})
        from app.application.agent_orchestrator.business_action_ledger import canonical_hash

        plan = copy.deepcopy(plan)
        self._apply_approval_risk_policy(plan)
        plan_sha256 = canonical_hash(plan_to_dict(plan))
        idempotency_key = canonical_hash(
            {
                "plan_id": str(plan.plan_id or ""),
                "plan_sha256": plan_sha256,
                "user_id": str(user_id or ""),
                "tenant_id": str(context.get("tenant_id") or ""),
                "session_id": str(
                    context.get("session_id") or context.get("conversation_id") or ""
                ),
            }
        )
        run_id = f"run_{idempotency_key[:32]}"
        existing = self._repo.get(run_id)
        if existing is not None:
            if (
                existing.user_id == str(user_id or "")
                and existing.plan_id == str(plan.plan_id or "")
                and existing.metadata.get("plan_sha256") == plan_sha256
                and existing.metadata.get("execution_idempotency_key") == idempotency_key
            ):
                return cast("AgentRun", existing)
            logger.error("plan idempotency collision; refusing to start run_id=%s", run_id)
            conflict = AgentRun(user_id=str(user_id or ""), message=str(message or ""))
            conflict.status = "blocked"
            conflict.error = "execution_idempotency_conflict"
            conflict.metadata["persistence"] = dict(self._repository_status)
            conflict.add_event(
                "run.idempotency_conflict",
                "执行幂等键发生冲突，已拒绝启动",
                {"plan_id": str(plan.plan_id or ""), "execution_started": False},
            )
            return cast("AgentRun", self._repo.save(conflict))
        run = AgentRun(user_id=str(user_id or ""), message=str(message or ""), run_id=run_id)
        run.metadata["persistence"] = dict(self._repository_status)
        run.metadata["runtime_context"] = context
        run.metadata["plan_sha256"] = plan_sha256
        run.metadata["execution_idempotency_key"] = idempotency_key
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
            self._apply_plan(run, plan, stable_step_ids=True)
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
        approval_request_id: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status == "cancelled":
            return cast("AgentRun | None", run)
        waiting_step = self._find_waiting_step(run, approved_step_id=approved_step_id)
        if waiting_step is None:
            run.add_event(
                "run.continue_ignored",
                "没有等待确认的步骤",
                {"approved_by": approved_by, "approved_step_id": approved_step_id},
            )
            return cast("AgentRun | None", self._repo.save(run))
        previous = copy.deepcopy(run)
        from app.application.agent_orchestrator.tool_permission import overlay_resume_context

        context = overlay_resume_context(run.metadata.get("runtime_context") or {}, runtime_context)
        plan_error = self._preflight_resume_plan(run, context)
        if plan_error:
            run.status = "blocked"
            run.error = plan_error
            run.add_event(
                "approval.resume_plan_rejected",
                "待恢复计划与当前完整计划/工具契约不一致，未执行等待步骤",
                {
                    "run_id": run.run_id,
                    "step_id": waiting_step.step_id,
                    "node_id": waiting_step.node_id,
                    "execution_started": False,
                },
            )
            if not self._repo.save_if_unchanged(run, previous):
                return None
            return cast("AgentRun | None", self._repo.get(run_id))
        plan = self._durable_plan(run)
        if plan is None:
            return None
        required = set((plan.metadata or {}).get("approval_required_node_ids") or [])
        approval_plan_sha256 = ""
        if waiting_step.node_id in required:
            from app.application.workflow.approval_persistence import (
                load_workflow_snapshot_for_execution,
            )
            from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict

            request_id = str(approval_request_id or "").strip()
            snapshot = load_workflow_snapshot_for_execution(request_id) if request_id else None
            snapshot_plan = (
                plan_from_dict(snapshot.get("plan")) if isinstance(snapshot, dict) else None
            )
            expected_step = str(snapshot.get("approved_step_id") or "") if snapshot else ""
            if (
                not isinstance(snapshot, dict)
                or str(snapshot.get("agent_run_id") or "") != run.run_id
                or expected_step not in {waiting_step.step_id, waiting_step.node_id}
                or snapshot_plan is None
                or plan_fingerprint(snapshot_plan) != plan_fingerprint(plan)
            ):
                run.status = "blocked"
                run.error = "持久化审批与当前完整执行计划不匹配"
                run.add_event(
                    "approval.resume_proof_missing",
                    "审批凭据或计划摘要不匹配，未执行等待步骤",
                    {
                        "run_id": run.run_id,
                        "step_id": waiting_step.step_id,
                        "node_id": waiting_step.node_id,
                        "execution_started": False,
                    },
                )
                if not self._repo.save_if_unchanged(run, previous):
                    return None
                return cast("AgentRun | None", self._repo.get(run_id))
            approval_plan_sha256 = plan_fingerprint(plan)
        if waiting_step.node_id in required and not approval_request_id.strip():
            run.status = "blocked"
            run.error = "该步骤需要审批工作台的持久化审批凭据"
            run.add_event(
                "approval.resume_proof_missing",
                "审批凭据缺失，未执行等待步骤",
                {
                    "run_id": run.run_id,
                    "step_id": waiting_step.step_id,
                    "node_id": waiting_step.node_id,
                    "execution_started": False,
                },
            )
            if not self._repo.save_if_unchanged(run, previous):
                return None
            return cast("AgentRun | None", self._repo.get(run_id))
        run.metadata["runtime_context"] = context
        apply_ai_budget_metadata(run, context)
        if not _authorized_step_matches_plan(run, waiting_step):
            waiting_step.status = "waiting_user"
            run.status = "waiting_user"
            run.add_event(
                "approval.authorization_mismatch",
                "步骤参数或依赖与已授权计划不一致，未执行",
                {
                    "step_id": waiting_step.step_id,
                    "node_id": waiting_step.node_id,
                    "tool_id": waiting_step.tool_id,
                    "action": waiting_step.action,
                },
            )
            return cast("AgentRun | None", self._repo.save(run))
        waiting_step.status = "pending"
        run.status = "running"
        run.error = ""
        run.metadata["approval_receipt"] = {
            "task_id": str((context or {}).get("task_id") or run.run_id),
            "step_id": waiting_step.step_id,
            "tool_id": waiting_step.tool_id,
            "action": waiting_step.action,
            "approved_by": str(approved_by or ""),
            "approval_request_id": str(approval_request_id or ""),
            "plan_sha256": approval_plan_sha256,
        }
        run.add_event(
            "step.approved",
            f"步骤 {waiting_step.node_id} 已确认继续",
            {
                "step_id": waiting_step.step_id,
                "node_id": waiting_step.node_id,
                "tool_id": waiting_step.tool_id,
                "action": waiting_step.action,
                "approved_by": approved_by,
                "task_id": run.metadata["approval_receipt"]["task_id"],
            },
        )
        if not self._repo.save_if_unchanged(run, previous):
            return None
        self._execute_with_durable_lease(
            run, runtime_context=context, approved_step_id=waiting_step.step_id
        )
        return cast("AgentRun | None", self._repo.save(run))

    def resume_failed_safe_steps(self, run_id: str) -> AgentRun | None:
        """Re-run only failed low-risk idempotent steps. Completed business writes stay completed."""
        run = self._repo.get(run_id)
        if run is None or run.status not in {"failed", "blocked"}:
            return cast("AgentRun | None", run)
        requeued = False
        for step in run.steps:
            if step.status == "completed":
                continue
            if step.status == "failed" and self._can_auto_execute(step):
                step.status = "pending"
                step.error = ""
                step.output = {}
                requeued = True
                continue
            if step.status == "failed":
                return cast("AgentRun | None", self._repo.save(run))
        if not requeued:
            return cast("AgentRun | None", self._repo.save(run))
        run.status = "running"
        run.error = ""
        context = dict(run.metadata.get("runtime_context") or {})
        self._execute_with_durable_lease(run, runtime_context=context)
        return cast("AgentRun | None", self._repo.save(run))

    @staticmethod
    def _durable_plan(run: AgentRun) -> PlanGraph | None:

        return plan_from_dict((run.metadata or {}).get("plan"))

    @staticmethod
    def _preflight_resume_plan(run: AgentRun, context: dict[str, Any]) -> str:
        """Revalidate the complete persisted plan and live tool contracts before resume."""
        from app.application.agent_orchestrator.tool_permission import actor_tool_denial
        from app.application.workflow.planning_graph_policy import validate_required_params
        from app.application.workflow.workflow_types import validate_plan_graph
        from app.application.workflow_registry_app import get_workflow_tool_registry

        plan = AgentOrchestrator._durable_plan(run)
        if plan is None or not plan.nodes or plan.plan_id != run.plan_id:
            return "持久化执行计划缺失或标识不匹配，拒绝续跑"
        if validate_plan_graph(plan):
            return "持久化执行计划图校验失败，拒绝续跑"
        steps = {step.node_id: step for step in run.steps}
        if set(steps) != {node.node_id for node in plan.nodes}:
            return "持久化计划与执行步骤不一致，拒绝续跑"
        if any(
            (node.tool_id, node.action, node.params, node.depends_on)
            != (
                steps[node.node_id].tool_id,
                steps[node.node_id].action,
                steps[node.node_id].params,
                steps[node.node_id].depends_on,
            )
            for node in plan.nodes
        ):
            return "持久化计划参数或依赖已变化，拒绝续跑"
        registry = get_workflow_tool_registry()
        if validate_required_params(plan, registry):
            return "计划不再符合当前工具注册表或参数契约，拒绝续跑"
        approval_ids = plan.metadata.get("approval_required_node_ids") or []
        if not isinstance(approval_ids, list) or any(
            str(value) not in steps for value in approval_ids
        ):
            return "计划审批节点清单无效，拒绝续跑"
        approval_ids = {str(value) for value in approval_ids}
        for node in plan.nodes:
            step = steps[node.node_id]
            expected_risk = "high" if node.node_id in approval_ids else node.risk
            if step.risk != expected_risk or step.idempotent != node.idempotent:
                return "计划风险或幂等属性与当前工具契约不一致，拒绝续跑"
            if node.tool_id == "clarify" and node.action == "ask":
                continue
            denial = actor_tool_denial(node.tool_id, node.action, context, step.params)
            if denial is not None:
                return "计划权限复核未通过，拒绝续跑"
        return ""

    def continue_after_clarification(
        self,
        run_id: str,
        *,
        answered_by: str,
        clarification_step_id: str,
        parameters: dict[str, Any],
        confirmed: bool = False,
        allowed_fields: set[str] | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        """Apply a validated answer to the durable graph, then resume LangGraph once."""
        run = self._repo.get(run_id)
        if run is None or run.status != "waiting_user":
            return cast("AgentRun | None", run)
        if str(answered_by or "") != run.user_id:
            return None
        waiting_step = find_waiting_step(run, approved_step_id=clarification_step_id)
        if waiting_step is None or (waiting_step.tool_id, waiting_step.action) != (
            "clarify",
            "ask",
        ):
            return None
        previous = copy.deepcopy(run)
        from app.application.agent_orchestrator.tool_permission import overlay_resume_context

        context = overlay_resume_context(run.metadata.get("runtime_context") or {}, runtime_context)
        apply_clarification_answer(
            run,
            step_id=waiting_step.step_id,
            parameters=parameters,
            confirmed=confirmed,
            allowed_fields=allowed_fields,
        )
        run.metadata["runtime_context"] = context
        apply_ai_budget_metadata(run, context)
        run.status = "running"
        run.error = ""
        run.add_event(
            "run.clarification_resumed",
            "已将澄清答案绑定到持久化计划并恢复执行",
            {"answered_by": answered_by, "step_id": waiting_step.step_id},
        )
        if not self._repo.save_if_unchanged(run, previous):
            return None
        self._execute_with_durable_lease(run, runtime_context=context)
        return cast("AgentRun", self._repo.save(run))

    def reject_waiting_step(self, run_id: str, *, rejector: str, reason: str) -> AgentRun | None:
        """Stop a waiting sensitive step. Rejection records who, when, and why, and does not execute."""
        run = self._repo.get(run_id)
        if run is None or run.status != "waiting_user":
            return cast("AgentRun | None", run)
        step = self._find_waiting_step(run)
        if step is None:
            return cast("AgentRun | None", run)
        step.status = "failed"
        step.error = reason or "approval_rejected"
        run.status = "failed"
        run.error = step.error
        run.metadata["approval_decision"] = {
            "decision": "rejected",
            "rejector": str(rejector or ""),
            "reason": str(reason or ""),
            "rejected_at": utc_now_iso(),
            "task_id": run.run_id,
            "step_id": step.step_id,
            "tool_id": step.tool_id,
        }
        run.add_event(
            "approval.rejected",
            "审批已拒绝，未执行工具",
            dict(run.metadata["approval_decision"]),
        )
        return cast("AgentRun | None", self._repo.save(run))

    def note_approval_timeout(self, run_id: str) -> AgentRun | None:
        """An expired approval window does not approve or execute the step."""
        run = self._repo.get(run_id)
        if run is None or run.status != "waiting_user":
            return cast("AgentRun | None", run)
        run.metadata["approval_timeout"] = {
            "auto_approved": False,
            "at": utc_now_iso(),
            "task_id": run.run_id,
        }
        run.add_event(
            "approval.timed_out",
            "审批超时，未自动执行",
            dict(run.metadata["approval_timeout"]),
        )
        return cast("AgentRun | None", self._repo.save(run))

    def start_employee_handoff(
        self,
        parent: AgentRun,
        *,
        employee_id: str,
        allowlist: list[str],
        message: str,
        plan: PlanGraph,
    ) -> AgentRun:
        """Start a child run that keeps the parent tenant and task, with the child's own tools."""
        from app.application.agent_orchestrator.tool_permission import (
            attach_child_result,
            handoff_runtime_context,
        )

        stored = dict(parent.metadata.get("runtime_context") or {})
        raw_task = parent.metadata.get("task_context")
        task = raw_task if isinstance(raw_task, dict) else {}
        parent_task_id = str(task.get("task_id") or stored.get("task_id") or parent.run_id)
        context = handoff_runtime_context(
            stored,
            employee_id=employee_id,
            allowlist=allowlist,
            parent_task_id=parent_task_id,
            parent_run_id=parent.run_id,
        )
        child = self.start_run_from_plan(
            user_id=parent.user_id,
            message=message,
            plan=plan,
            runtime_context=context,
        )
        attach_child_result(parent, child)
        self._repo.save(parent)
        return child

    def attach_child_run(self, parent_run_id: str, child: AgentRun) -> bool:
        """Persist a same-tenant child run receipt on its durable parent run."""
        from app.application.agent_orchestrator.tool_permission import attach_child_result

        parent = self._repo.get(str(parent_run_id or ""))
        child_context = child.metadata.get("runtime_context") or {}
        if (
            parent is None
            or str(child_context.get("parent_run_id") or "") != parent.run_id
            or not attach_child_result(parent, child)
        ):
            return False
        parent.add_event(
            "task.child_run_attached",
            "员工协作子运行已关联到父任务",
            {
                "child_run_id": child.run_id,
                "employee_id": str(child_context.get("employee_id") or ""),
                "status": child.status,
            },
        )
        self._repo.save(parent)
        return True

    def list_runs(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        return cast("list[AgentRun]", self._repo.list_recent(user_id=user_id, limit=limit))

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]:
        return cast("list[RunEvent]", self._repo.list_events(run_id, after_event_id=after_event_id))

    def _apply_plan(self, run: AgentRun, plan: PlanGraph, *, stable_step_ids: bool = False) -> None:
        self._apply_approval_risk_policy(plan)
        run.plan_id = plan.plan_id
        run.intent = plan.intent
        plan_metadata = dict(plan.metadata or {})
        run.metadata["plan"] = plan_to_dict(plan)
        self._attach_memory_recall(run, plan_metadata.get("memory_recall"))
        from app.application.workflow.workflow_types import step_plan_nodes

        nodes, graph_error = step_plan_nodes(plan)
        run.steps = [self._step_from_node(node) for node in nodes]
        if stable_step_ids:
            from app.application.agent_orchestrator.business_action_ledger import canonical_hash

            for step in run.steps:
                step.step_id = f"step_{canonical_hash([run.run_id, step.node_id])[:32]}"
        required_approvals = plan_metadata.get("approval_required_node_ids")
        if isinstance(required_approvals, list):
            required_ids = {str(value) for value in required_approvals}
            for step in run.steps:
                if step.node_id in required_ids:
                    step.risk = "high"
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
            from app.application.workflow.sql_execution_policy import (
                REFUSAL_CODE,
                REFUSAL_MESSAGE,
            )

            refused = plan_metadata.get("refusal_code") == REFUSAL_CODE
            run.error = REFUSAL_CODE if refused else "planner returned no executable steps"
            if refused:
                run.final_output = {
                    "message": REFUSAL_MESSAGE,
                    "refusal_code": REFUSAL_CODE,
                }
            run.add_event("planner.blocked", "计划没有可执行节点")

    @staticmethod
    def _apply_approval_risk_policy(plan: PlanGraph) -> None:
        """Persist approval elevations in the graph itself before hashing or execution."""
        metadata = plan.metadata if isinstance(plan.metadata, dict) else {}
        required = metadata.get("approval_required_node_ids")
        if not isinstance(required, list):
            return
        required_ids = {str(value) for value in required if str(value)}
        for node in plan.nodes:
            if node.node_id in required_ids:
                node.risk = "high"

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
        from app.application.agent_orchestrator.tool_permission import seal_server_context

        runtime_context = seal_server_context(runtime_context)
        node_outputs: dict[str, Any] = {
            step.node_id: dict(step.output or {})
            for step in run.steps
            if step.status == "completed"
        }
        # LangGraph is the single scheduler for business plans. Its node callback
        # delegates each side effect to StepExecution, retaining the existing
        # permission, idempotency, billing, approval and audit boundaries.
        from app.application.agent_orchestrator.tool_permission import actor_tool_denial
        from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime

        approved = str(approved_step_id or "").strip()
        steps_by_node = {step.node_id: step for step in run.steps}
        from app.application.workflow.workflow_types import plan_to_dict

        plan = plan_from_dict(run.metadata.get("plan"))
        if plan is None or not plan.nodes:
            run.status, run.error = "blocked", "持久化计划图缺失，拒绝执行"
            _mark_prior_effects_for_reconciliation(run, "workflow_plan_missing")
            run.add_event("workflow.graph_rejected", run.error, {"run_id": run.run_id})
            self._repo.save(run)
            return
        if {node.node_id for node in plan.nodes} != set(steps_by_node):
            run.status, run.error = "blocked", "计划图节点与已保存执行步骤不一致，拒绝执行"
            unsafe = _mark_prior_effects_for_reconciliation(run, "workflow_node_set_mismatch")
            run.add_event(
                "workflow.graph_rejected",
                run.error,
                {
                    "run_id": run.run_id,
                    "reconciliation_required": bool(unsafe),
                    "completed_non_idempotent_step_ids": unsafe,
                },
            )
            self._repo.save(run)
            return
        for node in plan.nodes:
            step = steps_by_node[node.node_id]
            if (node.tool_id, node.action, node.params, node.depends_on) != (
                step.tool_id,
                step.action,
                step.params,
                step.depends_on,
            ):
                run.status, run.error = "blocked", "计划节点与已持久化执行步骤不一致，拒绝执行"
                unsafe = _mark_prior_effects_for_reconciliation(run, "workflow_plan_mismatch")
                run.add_event(
                    "workflow.plan_audit_rejected",
                    run.error,
                    {
                        "run_id": run.run_id,
                        "node_id": node.node_id,
                        "reconciliation_required": bool(unsafe),
                        "completed_non_idempotent_step_ids": unsafe,
                        "execution_started": False,
                    },
                )
                self._repo.save(run)
                return
        from app.application.agent_orchestrator.reply_plan import execute_reply_plan
        from app.application.workflow.planning_graph_policy import validate_required_params
        from app.application.workflow.workflow_types import validate_plan_graph
        from app.application.workflow_registry_app import get_workflow_tool_registry

        if execute_reply_plan(run, plan, runtime_context):
            self._repo.save(run)
            return
        registry = get_workflow_tool_registry()
        plan_error = validate_plan_graph(plan) or validate_required_params(plan, registry)
        if plan_error:
            run.status, run.error = "blocked", f"执行前计划审核未通过：{plan_error}"
            unsafe = _mark_prior_effects_for_reconciliation(run, "workflow_plan_audit_rejected")
            run.add_event(
                "workflow.plan_audit_rejected",
                run.error,
                {
                    "run_id": run.run_id,
                    "reconciliation_required": bool(unsafe),
                    "completed_non_idempotent_step_ids": unsafe,
                    "execution_started": False,
                },
            )
            self._repo.save(run)
            return
        approval_ids = plan.metadata.get("approval_required_node_ids") or []
        if not isinstance(approval_ids, list) or any(
            str(node_id) not in steps_by_node for node_id in approval_ids
        ):
            run.status, run.error = "blocked", "审批计划节点清单无效，拒绝执行"
            unsafe = _mark_prior_effects_for_reconciliation(run, "approval_plan_invalid")
            run.add_event(
                "workflow.plan_audit_rejected",
                run.error,
                {
                    "run_id": run.run_id,
                    "reconciliation_required": bool(unsafe),
                    "completed_non_idempotent_step_ids": unsafe,
                    "execution_started": False,
                },
            )
            self._repo.save(run)
            return
        approval_ids = {str(node_id) for node_id in approval_ids}
        for node in plan.nodes:
            step = steps_by_node[node.node_id]
            expected_risk = "high" if node.node_id in approval_ids else node.risk
            if step.risk != expected_risk or step.idempotent != node.idempotent:
                run.status, run.error = (
                    "blocked",
                    "计划风险/幂等策略与持久化执行步骤不一致，拒绝执行",
                )
                unsafe = _mark_prior_effects_for_reconciliation(run, "workflow_policy_mismatch")
                run.add_event(
                    "workflow.plan_audit_rejected",
                    run.error,
                    {
                        "run_id": run.run_id,
                        "node_id": node.node_id,
                        "expected_risk": expected_risk,
                        "step_risk": step.risk,
                        "plan_idempotent": node.idempotent,
                        "step_idempotent": step.idempotent,
                        "reconciliation_required": bool(unsafe),
                        "completed_non_idempotent_step_ids": unsafe,
                        "execution_started": False,
                    },
                )
                self._repo.save(run)
                return
            if node.node_id in approval_ids:
                node.risk = "high"
        for node in plan.nodes:
            if node.tool_id == "clarify" and node.action == "ask":
                continue
            step = steps_by_node[node.node_id]
            denial = actor_tool_denial(node.tool_id, node.action, runtime_context, step.params)
            if denial is not None:
                code = str(denial.get("error_code") or "tool_permission_denied")
                run.status, run.error = "blocked", str(denial.get("message") or "权限校验失败")
                unsafe = _mark_prior_effects_for_reconciliation(run, code)
                # Preflight denial is a non-execution receipt, not a generic
                # tool failure. Never overwrite an already executed receipt.
                reason = str(denial.get("reason") or code)
                if step.status in {"pending", "waiting_user"}:
                    step.error = run.error
                    step.output = {
                        "success": False,
                        "error_code": code,
                        "reason": reason,
                        "message": run.error,
                        "user_id": str(runtime_context.get("user_id") or ""),
                        "tool_id": node.tool_id,
                        "action": node.action,
                        "task_id": run.run_id,
                    }
                run.add_event(
                    "tool.permission_denied",
                    run.error,
                    {
                        "step_id": step.step_id,
                        "tool_id": node.tool_id,
                        "action": node.action,
                        "reason": reason,
                        "user_id": str(runtime_context.get("user_id") or ""),
                        "execution_started": False,
                    },
                )
                run.add_event(
                    "workflow.plan_audit_rejected",
                    "完整计划权限预检未通过，未执行任何节点",
                    {
                        "run_id": run.run_id,
                        "node_id": node.node_id,
                        "tool_id": node.tool_id,
                        "action": node.action,
                        "error_code": code,
                        "reconciliation_required": bool(unsafe),
                        "completed_non_idempotent_step_ids": unsafe,
                        "execution_started": False,
                    },
                )
                self._repo.save(run)
                return
        from app.application.agent_orchestrator.business_action_ledger import canonical_hash

        run.add_event(
            "workflow.plan_audited",
            "完整计划已通过服务端注册表和参数预检",
            {
                "run_id": run.run_id,
                "plan_sha256": canonical_hash(plan_to_dict(plan)),
                "node_count": len(plan.nodes),
                "execution_started": False,
                "permissions_preflighted": True,
                "approval_required_node_ids": sorted(approval_ids),
            },
        )
        run.metadata["plan"] = plan_to_dict(plan)
        stopped_for_interaction = False

        def sync_step_plan(step: AgentStep, reason: str) -> bool:
            plan_node = next((node for node in plan.nodes if node.node_id == step.node_id), None)
            if plan_node is None or (plan_node.tool_id, plan_node.action) != (
                step.tool_id,
                step.action,
            ):
                run.status, run.error = "blocked", "运行时步骤无法绑定到已审核计划"
                return False
            if plan_node.params == step.params:
                return True
            plan_node.params = copy.deepcopy(step.params)
            run.metadata["plan"] = plan_to_dict(plan)
            run.add_event(
                "workflow.plan_node_updated",
                reason,
                {
                    "node_id": step.node_id,
                    "plan_sha256": canonical_hash(plan_to_dict(plan)),
                },
            )
            self._repo.save(run)
            return True

        def dispatch(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal stopped_for_interaction
            state = params.get("_runtime_context")
            state = state if isinstance(state, dict) else {}
            node_id = str(state.get("_langgraph_node_id") or "")
            step = next(
                (item for item in run.steps if item.node_id == node_id),
                None,
            )
            if step is None:
                candidates = [
                    item
                    for item in run.steps
                    if item.tool_id == tool_id
                    and item.action == action
                    and item.status not in {"completed", "skipped"}
                ]
                step = candidates[0] if len(candidates) == 1 else None
            if step is None:
                return {
                    "success": False,
                    "error_code": "plan_node_binding_invalid",
                    "message": "计划节点绑定校验失败",
                }
            if (step.tool_id, step.action) != (tool_id, action):
                run.status, run.error = "blocked", "计划节点动作与已审批步骤不一致"
                return {
                    "success": False,
                    "error_code": "plan_node_binding_invalid",
                    "message": run.error,
                }
            validation = validate_tool_call(
                tool_id,
                action,
                step.params,
                allow_references_from=set(step.depends_on),
            )
            if not validation.ok or validation.spec is None:
                step.status = "failed"
                step.output = {
                    "success": False,
                    "error_code": validation.error_code or "unknown_tool_action",
                    "message": validation.message or "工具动作当前不可用",
                }
                step.error = str(step.output["message"])
                run.status, run.error = "failed", step.error
                run.add_event(
                    "workflow.plan_policy_rejected",
                    "计划工具动作未通过服务端注册表校验",
                    {
                        "step_id": step.step_id,
                        "tool_id": tool_id,
                        "action": action,
                        "error_code": step.output["error_code"],
                    },
                )
                return dict(step.output)
            contract_risk = (
                validation.spec.risk
                if validation.spec.risk in {"low", "medium", "high"}
                else "high"
            )
            # A server policy may elevate a node to require approval. Runtime
            # normalization must never lower that reviewed high-risk boundary
            # back to the base ToolSpec risk after the plan audit.
            server_risk = "high" if step.node_id in approval_ids else contract_risk
            server_idempotent = bool(validation.spec.idempotent)
            if step.risk != server_risk or step.idempotent != server_idempotent:
                run.add_event(
                    "workflow.plan_policy_normalized",
                    "计划风险和幂等属性已按服务端工具契约复核",
                    {
                        "step_id": step.step_id,
                        "claimed_risk": step.risk,
                        "risk": server_risk,
                        "claimed_idempotent": step.idempotent,
                        "idempotent": server_idempotent,
                    },
                )
                step.risk, step.idempotent = server_risk, server_idempotent
                plan_node = next(
                    (node for node in plan.nodes if node.node_id == step.node_id), None
                )
                if plan_node is not None:
                    plan_node.risk, plan_node.idempotent = server_risk, server_idempotent
                    run.metadata["plan"] = plan_to_dict(plan)
            outputs = state.get("node_outputs")
            outputs = outputs if isinstance(outputs, dict) else node_outputs
            if self._apply_requested_control(run):
                stopped_for_interaction = True
                return {"success": True, "requires_confirmation": True}
            original_params = copy.deepcopy(step.params)
            if refuse_unresolved_step(run, step, outputs):
                stopped_for_interaction = True
                return dict(
                    step.output
                    or {
                        "success": False,
                        "error_code": "unresolved_param_reference",
                        "message": step.error or "前序参数引用无法唯一解析",
                    }
                )
            clarification_paused = pause_for_clarification(run, step, outputs)
            if not sync_step_plan(step, "引用/澄清参数已更新并写回完整计划"):
                return {
                    "success": False,
                    "error_code": "plan_node_binding_invalid",
                    "message": run.error,
                }
            if step.params != original_params:
                run.add_event(
                    "workflow.plan_reference_resolved",
                    "前序结果已解析并绑定到完整计划",
                    {
                        "node_id": step.node_id,
                        "plan_sha256": canonical_hash(plan_to_dict(plan)),
                    },
                )
                self._repo.save(run)
            if clarification_paused:
                stopped_for_interaction = True
                return {"success": True, "requires_confirmation": True}
            # Preflight permits only well-formed references to direct dependencies.
            # Once those dependencies have completed, validate the concrete payload
            # again before approval or any side effect can proceed.
            concrete_validation = validate_tool_call(tool_id, action, step.params)
            if not concrete_validation.ok:
                step.status = "failed"
                step.error = concrete_validation.message or "工具参数未通过执行前复核"
                step.output = {
                    "success": False,
                    "error_code": concrete_validation.error_code or "schema_validation_failed",
                    "message": step.error,
                }
                run.status, run.error = "failed", step.error
                run.add_event(
                    "workflow.concrete_params_rejected",
                    "引用解析后的真实参数未通过工具契约复核，未执行本节点",
                    {"node_id": step.node_id, "tool_id": tool_id, "action": action},
                )
                self._repo.save(run)
                return dict(step.output)
            if not self._can_auto_execute(step) and not (
                approved and approved in {step.step_id, step.node_id}
            ):
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
                stopped_for_interaction = True
                return {"success": True, "requires_approval": True, "step_id": step.step_id}
            denial = actor_tool_denial(tool_id, action, runtime_context, step.params)
            if denial is not None:
                step.status, step.output = "failed", denial
                step.error = str(denial.get("message") or "tool_permission_denied")
                run.status, run.error = "failed", step.error
                run.add_event(
                    "tool.permission_denied",
                    step.error,
                    {
                        "step_id": step.step_id,
                        "tool_id": tool_id,
                        "action": action,
                        "reason": str(denial.get("reason") or denial.get("error_code") or ""),
                    },
                )
                return denial
            while True:
                budget = budget_exceeded_payload(
                    run,
                    additional_cost_units=self._step_cost_units(step),
                    scope=f"{tool_id}.{action}",
                )
                if budget is not None:
                    self._mark_budget_exceeded(run, step, budget, node_outputs=outputs)
                    return {"success": False, "error_code": "budget_exceeded", "message": run.error}
                self._execute_step(run, step, runtime_context=runtime_context, node_outputs=outputs)
                if run.metadata.get("non_retryable"):
                    terminal = _verified_catalog_terminal(run, step)
                    if terminal is None:
                        run.status, run.error = "blocked", step.error
                        return {
                            "success": False,
                            "outcome": "unknown",
                            "message": step.error or "结果需要人工核对",
                        }
                    # Readback is a current projection, not a rewrite of the
                    # immutable execution fact shared with the tool-call audit.
                    return {"success": True, "business_outcome": dict(terminal)}
                if self._apply_requested_control(run):
                    stopped_for_interaction = True
                    return {"success": True, "requires_confirmation": True}
                if step.status == "completed":
                    node_outputs[step.node_id] = dict(step.output or {})
                    return dict(step.output or {"success": True})
                if self._prepare_repair_or_retry(run, step, runtime_context=runtime_context):
                    if not sync_step_plan(step, "受控修复后的参数已写回完整计划"):
                        return {
                            "success": False,
                            "error_code": "plan_node_binding_invalid",
                            "message": run.error,
                        }
                    repaired = validate_tool_call(step.tool_id, step.action, step.params)
                    if not repaired.ok:
                        step.status = "failed"
                        step.error = f"修复参数预检失败：{repaired.message}"
                        run.status, run.error = "failed", step.error
                        return {
                            "success": False,
                            "error_code": repaired.error_code,
                            "message": run.error,
                        }
                    continue
                run.status, run.error = "failed", step.error or f"step {step.node_id} failed"
                return {**dict(step.output or {}), "success": False, "message": run.error}

        try:
            graph_result = XCAGILangGraphRuntime(tool_dispatcher=dispatch).run(
                plan,
                runtime_context={
                    **runtime_context,
                    "node_outputs": node_outputs,
                    "executed": [step.node_id for step in run.steps if step.status == "completed"],
                    "blocked": [step.node_id for step in run.steps if step.status == "skipped"],
                },
                max_retries=0,
                parallel=False,
            )
        except (ValueError, RuntimeError) as exc:
            run.status, run.error = "blocked", f"计划图校验或执行失败：{exc}"
            run.add_event("workflow.graph_rejected", run.error, {"run_id": run.run_id})
            self._repo.save(run)
            return
        for node_id, output in (graph_result.final_context.get("node_outputs") or {}).items():
            if node_id in steps_by_node and isinstance(output, dict):
                step = steps_by_node[node_id]
                business_outcome = output.get("business_outcome")
                node_outputs[node_id] = (
                    dict(business_outcome) if isinstance(business_outcome, dict) else output
                )
                if step.tool_id == "clarify" and output.get("requires_confirmation"):
                    pause_for_clarification(run, step, node_outputs)
                    step.output = {**output, **step.output}
                    run.final_output = {"clarification": {"step_id": step.step_id, **step.output}}
                    stopped_for_interaction = True
        if stopped_for_interaction or run.status in {"waiting_user", "blocked"}:
            self._repo.save(run)
            return
        if not graph_result.success:
            failed = next((item for item in run.steps if item.status == "failed"), None)
            run.status = "failed"
            run.error = run.error or (
                failed.error if failed else graph_result.message or "workflow graph failed"
            )
            budget_event = next(
                (event for event in reversed(run.events) if event.event_type == "budget.exceeded"),
                None,
            )
            if failed is not None and budget_event is not None:
                # The normal cost refresh recomputes the actual spent amount (zero
                # for a preflight rejection); preserve the fact that the requested
                # operation was blocked because its projected cost crossed budget.
                self._mark_budget_exceeded(
                    run, failed, dict(budget_event.data), node_outputs=node_outputs
                )
                self._repo.save(run)
                return
            self._refresh_run_cost_metadata(run)
            self._refresh_repair_metadata(run)
            run.final_output = {
                "node_outputs": node_outputs,
                "tool_calls": [call.to_dict() for call in run.tool_calls],
                "artifacts": [artifact.to_dict() for artifact in run.artifacts],
                "cost_units_total": run.metadata["cost_units_total"],
                "ai_cost_units_total": run.metadata["ai_cost_units_total"],
                "failed_step_id": failed.step_id if failed else "",
                "error": run.error,
                "repair_count": run.metadata.get("repair_count", 0),
            }
            self._append_llm_summary_to_final_output(run)
            self._remember_run_outcome_for(run)
            self._repo.save(run)
            return
        executed_nodes = set(graph_result.final_context.get("executed") or [])
        for step in run.steps:
            if step.status == "pending" and step.node_id not in executed_nodes:
                step.status = "skipped"
                step.error = "条件路由未选中该步骤"
                run.add_event(
                    "step.skipped", step.error, {"step_id": step.step_id, "node_id": step.node_id}
                )
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
