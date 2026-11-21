"""Prepare an entity-bound plan and admit it through the existing atomic task API."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.enterprise_cognition.goals import (
    GoalBindingError,
    get_goal_service,
    metric_value,
)
from app.application.workflow.goal_coverage import (
    GoalCoverage,
    coverage_error,
    review_goal_coverage,
)
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.workflow_types import validate_plan_graph
from app.infrastructure.auth.agent_mod_scope import validate_actor_context


class EnterpriseExecutionService:
    """No dispatch, approval decisions, or business writes exist in this adapter."""

    def __init__(self, *, goals=None, orchestrator=None, planner=None):
        self.goals = goals if goals is not None else get_goal_service()
        self.orchestrator = orchestrator if orchestrator is not None else AgentOrchestrator()
        self.planner = planner if planner is not None else LLMWorkflowPlanner()

    @staticmethod
    def _identity(context, tenant_id, actor_id, mod_id):
        if (
            str(context.get("tenant_id") or "") != str(tenant_id)
            or context.get("user_id") != actor_id
            or str(context.get("mod_id") or "") != mod_id
            or validate_actor_context(context) is not None
        ):
            raise GoalBindingError("execution_identity_invalid")

    def _verify_run(
        self, run: AgentRun, *, task_id, digest, tenant_id, actor_id, mod_id
    ) -> AgentRun:
        context = run.metadata.get("runtime_context") or {}
        binding = context.get("enterprise_cognition") or {}
        task = run.metadata.get("task_context") or {}
        if (
            run.user_id != actor_id
            or str(context.get("tenant_id") or "") != str(tenant_id)
            or str(context.get("mod_id") or "") != mod_id
            or task.get("task_id") != task_id
            or binding.get("request_sha256") != digest
        ):
            raise GoalBindingError("request_id_already_bound")
        # Losing concurrent planners must never save their candidate over the winner.
        parent_id = str(context.get("parent_run_id") or "")
        if parent_id:
            parent = self.orchestrator.get_run(parent_id)
            parent_task = (parent.metadata.get("task_context") or {}) if parent else {}
            if not parent or parent_task.get("task_id") != context.get("parent_task_id"):
                raise GoalBindingError("parent_task_binding_missing")
            if run.run_id not in (parent.metadata.get("child_results") or {}):
                if not self.orchestrator.attach_child_run(parent_id, run):
                    raise GoalBindingError("parent_task_binding_invalid")
        return run

    def plan(
        self,
        goal_id: str,
        request_id: str,
        message: str,
        *,
        tenant_id,
        actor_id: str,
        mod_id: str = "",
        runtime_context: dict[str, Any],
    ) -> AgentRun:
        tenant_id, actor_id, mod_id = self.goals._scope(tenant_id, actor_id, mod_id)
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 160:
            raise GoalBindingError("request_id_required")
        if not isinstance(message, str) or not message.strip() or len(message) > 12000:
            raise GoalBindingError("planning_message_required")
        context = copy.deepcopy(runtime_context)
        self._identity(context, tenant_id, actor_id, mod_id)
        goal = self.goals.get(goal_id, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id)
        task_id = "enterprise_" + canonical_hash([tenant_id, actor_id, mod_id, request_id])[:40]
        digest = canonical_hash(
            {
                "goal": goal["binding_sha256"],
                "message": message,
                "task_id": task_id,
                "parent_run_id": context.get("parent_run_id"),
                "parent_task_id": context.get("parent_task_id"),
            }
        )
        binding_args = {
            "task_id": task_id,
            "digest": digest,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "mod_id": mod_id,
        }
        current = self.orchestrator.get_task(
            user_id=actor_id, tenant_id=str(tenant_id), task_id=task_id
        )
        if current is not None:
            run = self.orchestrator.get_run(current.active_run_id)
            if run is None:
                raise GoalBindingError("task_run_missing")
            return self._verify_run(run, **binding_args)
        if not callable(getattr(self.orchestrator, "create_task_run", None)):
            raise GoalBindingError("phase_one_atomic_admission_required")

        baseline = self.goals.state(
            goal, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id, force_refresh=True
        )
        metric_value(baseline, goal["metric"], goal["unit"])
        for key in (
            "enterprise_cognition",
            "task_id",
            "task_attempt",
            "run_id",
            "task_model_version",
            "approved",
            "approved_by",
            "approved_step_id",
            "approval_receipt",
            "_tool_approval_grants",
        ):
            context.pop(key, None)
        context.update(
            task_id=task_id,
            task_title=goal["objective"][:80],
            task_attempt=1,
            task_model_version=1,
            task_source="enterprise_cognition",
        )
        # A task workspace is not a persisted chat. Inventing a conversation ID
        # would require a nonexistent conversation revision on the second approval.
        if not str(context.get("workspace_id") or ""):
            context["workspace_id"] = task_id
        context["enterprise_cognition"] = {
            "goal": goal,
            "baseline": baseline,
            "bound_at": utc_now_iso(),
            "request_sha256": digest,
        }
        from app.application.workflow_registry_app import get_workflow_tool_registry
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        planning_message = (
            f"{message}\n本次经营目标（仅生成待审批方案）：{goal['objective']}"
            f"\n目标实体：{goal['entity_type']}:{goal['entity_id']}"
        )
        context["enterprise_goal_review"] = (
            "目标覆盖核对必须包含经营目标 objective 的完整原文，并关联实际计划节点。"
            "实体状态是只读事实，经营目标是本账号给定的目标，不代表已完成或已批准。"
        )
        with model_rate_limit_scope(context):
            candidate = self.planner.plan(
                actor_id, planning_message, get_workflow_tool_registry(), copy.deepcopy(context)
            )
        if candidate.metadata.get("planning_rejected") or not candidate.nodes:
            raise GoalBindingError("goal_plan_rejected")
        if validate_plan_graph(candidate):
            raise GoalBindingError("goal_plan_invalid")
        raw_review = candidate.metadata.get("goal_coverage")
        if not isinstance(raw_review, dict):
            with model_rate_limit_scope(context):
                review, error = review_goal_coverage(
                    candidate, planning_message, context, self.planner.complete_messages
                )
            if review is None or error:
                raise GoalBindingError("goal_coverage_unverified")
        else:
            review = GoalCoverage.model_validate(raw_review)
        if coverage_error(review, candidate, planning_message):
            raise GoalBindingError("goal_coverage_unverified")
        candidate.metadata["goal_coverage"] = review.model_dump()
        if not any(
            goal["objective"] in disposition.source and disposition.outcome == "execute"
            for disposition in review.goals
        ):
            raise GoalBindingError("operating_goal_not_covered")
        required_ids = candidate.metadata.get("approval_required_node_ids") or []
        if not isinstance(required_ids, list) or any(
            item not in {node.node_id for node in candidate.nodes} for item in required_ids
        ):
            raise GoalBindingError("goal_plan_approval_invalid")
        required = set(required_ids)
        action_bindings = []
        for node in candidate.nodes:
            spec = get_tool_action_spec(node.tool_id, node.action)
            if spec is None or actor_tool_denial(node.tool_id, node.action, context, node.params):
                raise GoalBindingError("goal_plan_permission_denied")
            if node.tool_id == "enterprise_cognition" and node.action == "plan":
                raise GoalBindingError("recursive_goal_plan_forbidden")
            if not spec.read_only:
                # Existing sales lifecycle operations explicitly target one original
                # order. New-order/refund/delegation actions need their own reviewed
                # selector contract before this adapter may bind them to an old KPI.
                if not (
                    goal["entity_type"] == "order"
                    and node.tool_id == "sales"
                    and node.action
                    in {"confirm", "deliver", "invoice", "payment", "cancel", "credit_note"}
                    and str(node.params.get("order_id")) == goal["entity_id"]
                ):
                    raise GoalBindingError("goal_action_target_unsupported_or_mismatched")
                required.add(node.node_id)
                action_bindings.append(
                    {
                        "node_id": node.node_id,
                        "entity_type": goal["entity_type"],
                        "entity_id": goal["entity_id"],
                        "tool_id": spec.tool_id,
                        "action": spec.action,
                        "selector": "order_id",
                        "params_sha256": canonical_hash(node.params),
                    }
                )
            node.risk, node.idempotent = spec.risk, spec.idempotent
        if not action_bindings:
            raise GoalBindingError("goal_plan_has_no_bound_action")
        candidate.metadata["approval_required_node_ids"] = sorted(required)
        context["enterprise_cognition"]["action_bindings"] = action_bindings
        # Re-read once after planning: an intervening source change invalidates the
        # proposal; it must not silently replace the state the planner reasoned from.
        fresh = self.goals.state(
            goal, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id, force_refresh=True
        )
        metric_value(fresh, goal["metric"], goal["unit"])
        if fresh["source_version"] != baseline["source_version"]:
            raise GoalBindingError("entity_changed_during_planning")
        now = utc_now_iso()
        try:
            observed = datetime.fromisoformat(fresh["observed_at"].replace("Z", "+00:00"))
            expires = datetime.fromisoformat(fresh["expires_at"].replace("Z", "+00:00"))
            bound = datetime.fromisoformat(now.replace("Z", "+00:00"))
            if not observed <= bound < expires:
                raise GoalBindingError("entity_projection_expired")
        except (KeyError, TypeError) as exc:
            raise GoalBindingError("entity_projection_time_invalid") from exc
        context["enterprise_cognition"].update(baseline=fresh, bound_at=now)
        self._identity(context, tenant_id, actor_id, mod_id)
        candidate.metadata["enterprise_cognition"] = copy.deepcopy(context["enterprise_cognition"])
        run = self.orchestrator.start_task_from_plan(
            user_id=actor_id,
            message=planning_message,
            plan=candidate,
            runtime_context=context,
            persist=False,
        )
        if run.status != "waiting_user":
            raise GoalBindingError("goal_plan_not_at_approval_checkpoint")
        run.metadata["task_request_fingerprint"] = digest
        winner, _created = self.orchestrator.create_task_run(run)
        return self._verify_run(winner, **binding_args)


def get_execution_service() -> EnterpriseExecutionService:
    return EnterpriseExecutionService()
