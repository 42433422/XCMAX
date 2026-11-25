"""Admit an entity-bound Codex task and restrict each original approved action."""

from __future__ import annotations

import copy
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.enterprise_cognition.goals import (
    GoalBindingError,
    get_goal_service,
    metric_value,
)
from app.domain.enterprise_cognition.world_observation import delivery_scenario, public_snapshot
from app.infrastructure.auth.agent_mod_scope import validate_actor_context

_ORDER_ACTIONS = frozenset({"confirm", "deliver", "invoice", "payment", "cancel", "credit_note"})


def validate_goal_action(
    context: dict[str, Any], tool_id: str, action: str, params: dict[str, Any], *, read_only: bool
) -> None:
    """The goal narrows an existing grant; it never grants tools or substitutes approval."""
    binding = context.get("enterprise_cognition")
    constraints = context.get("_runtime_goal_constraints") or {}
    if not binding and not constraints:
        return
    if not isinstance(binding, dict) or not isinstance(binding.get("goal"), dict):
        raise GoalBindingError("enterprise_goal_binding_missing")
    goal = binding["goal"]
    if (
        str(goal.get("tenant_id")) != str(context.get("tenant_id"))
        or str(goal.get("actor_id")) != str(context.get("user_id"))
        or str(goal.get("mod_id") or "") != str(context.get("mod_id") or "")
        or canonical_hash(
            {
                key: value
                for key, value in goal.items()
                if key not in {"binding_sha256", "created_at"}
            }
        )
        != goal.get("binding_sha256")
    ):
        raise GoalBindingError("enterprise_goal_scope_changed")
    if constraints and (
        constraints.get("goal_binding_sha256") != goal.get("binding_sha256")
        or constraints.get("request_sha256") != binding.get("request_sha256")
        or constraints.get("entity_id") != goal.get("entity_id")
        or constraints.get("entity_type") != goal.get("entity_type")
        or constraints.get("requires_approval") is not True
    ):
        raise GoalBindingError("enterprise_goal_scope_changed")
    if (tool_id, action) == ("enterprise_cognition", "plan"):
        raise GoalBindingError("recursive_goal_plan_forbidden")
    if not read_only and not (
        goal.get("entity_type") == "order"
        and tool_id == "sales"
        and action in _ORDER_ACTIONS
        and str(params.get("order_id") or "") == goal.get("entity_id")
    ):
        raise GoalBindingError("goal_action_target_unsupported_or_mismatched")


def bind_goal_action_plan(plan: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Bind each new deterministic child to its original entity and exact approval."""
    if not context.get("enterprise_cognition"):
        return context
    context = copy.deepcopy(context)
    binding = context["enterprise_cognition"]
    goal = binding["goal"]
    actions = []
    required = set(plan.metadata.get("approval_required_node_ids") or [])
    for node in plan.nodes:
        spec = get_tool_action_spec(node.tool_id, node.action)
        if spec is None:
            raise GoalBindingError("goal_plan_permission_denied")
        read_only = spec.is_read_only_call(node.params)
        validate_goal_action(context, node.tool_id, node.action, node.params, read_only=read_only)
        if not read_only:
            actions.append(
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
            required.add(node.node_id)
            node.risk = "high"
    binding["action_bindings"] = actions
    plan.metadata["enterprise_cognition"] = copy.deepcopy(binding)
    plan.metadata["approval_required_node_ids"] = sorted(required)
    return context


class EnterpriseExecutionService:
    """No planning model, approval decision, or business dispatch in this adapter."""

    def __init__(self, *, goals=None, orchestrator=None, runtime_gateway=None):
        self.goals = goals if goals is not None else get_goal_service()
        self.orchestrator = orchestrator if orchestrator is not None else AgentOrchestrator()
        self.runtime_gateway = runtime_gateway

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
        """Keep the public admission action while the one Codex kernel chooses actions."""
        from app.application.agent_orchestrator.run_sql_repository import (
            SQLAlchemyAgentRunRepository,
        )
        from app.application.agent_runtime.gateway import run_runtime_task

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
        repository = self.orchestrator._repo
        if not isinstance(repository, SQLAlchemyAgentRunRepository):
            raise GoalBindingError("phase_one_atomic_admission_required")
        baseline = self.goals.state(
            goal, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id, force_refresh=True
        )
        metric_value(baseline, goal["metric"], goal["unit"])
        for key in (
            "enterprise_cognition",
            "_runtime_goal_constraints",
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
            turn_id=task_id,
            task_title=goal["objective"][:80],
            task_attempt=1,
            task_model_version=1,
            task_source="enterprise_cognition",
        )
        if not context.get("parent_run_id"):
            context.setdefault("workspace_id", task_id)
        fresh = self.goals.state(
            goal, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id, force_refresh=True
        )
        metric_value(fresh, goal["metric"], goal["unit"])
        if fresh["source_version"] != baseline["source_version"]:
            raise GoalBindingError("entity_changed_during_admission")
        now = utc_now_iso()
        try:
            observed = datetime.fromisoformat(fresh["observed_at"].replace("Z", "+00:00"))
            expires = datetime.fromisoformat(fresh["expires_at"].replace("Z", "+00:00"))
            if not observed <= datetime.fromisoformat(now.replace("Z", "+00:00")) < expires:
                raise GoalBindingError("entity_projection_expired")
        except (KeyError, TypeError) as exc:
            raise GoalBindingError("entity_projection_time_invalid") from exc
        # This conditional calculation does not prove stock, grant approval
        # or execute a delivery; only the original task may perform writes.
        world_scenario = {
            "knowledge_kind": "unknown",
            "reason_code": "goal_scenario_not_applicable",
        }
        if (
            goal["entity_type"] == "order"
            and goal["metric"] == "remaining_quantity"
            and goal["direction"] == "decrease"
        ):
            current_quantity = metric_value(fresh, goal["metric"], goal["unit"])
            target_quantity = Decimal(str(goal["target"]))
            world_scenario = delivery_scenario(
                public_snapshot(fresh), str(current_quantity - target_quantity)
            )
        context["enterprise_cognition"] = {
            "goal": goal,
            "baseline": fresh,
            "world_scenario": world_scenario,
            "bound_at": now,
            "request_sha256": digest,
        }
        context["_runtime_goal_constraints"] = {
            "objective": goal["objective"],
            "entity_type": goal["entity_type"],
            "entity_id": goal["entity_id"],
            "goal_binding_sha256": goal["binding_sha256"],
            "request_sha256": digest,
            "requires_approval": True,
            "allowed_write_actions": sorted(f"sales.{action}" for action in _ORDER_ACTIONS),
        }
        self._identity(context, tenant_id, actor_id, mod_id)
        result = (self.runtime_gateway or run_runtime_task)(
            task=message,
            system_prompt=(
                "围绕宿主绑定的经营目标观察原实体状态并选择下一步。只能操作该原订单的获准生命周期动作，"
                "每次写入必须由原任务审批；不得新建订单、转派或递归创建经营任务。"
                "world_scenario 只是条件算术推演，不证明库存、可交付性、发生概率或批准；"
                "不得将假设当作业务事实或执行回执。"
            ),
            runtime_context=context,
            input_data={
                "enterprise_goal": copy.deepcopy(goal),
                "baseline": copy.deepcopy(fresh),
                "world_scenario": copy.deepcopy(world_scenario),
            },
            completion_mode="business",
            start_queued=True,
            _task_id=task_id,
            _repository=repository,
        )
        run = self.orchestrator.get_run(str(result.get("run_id") or ""))
        if run is None:
            raise GoalBindingError(str(result.get("error_code") or "goal_runtime_admission_failed"))
        return self._verify_run(run, **binding_args)


def get_execution_service() -> EnterpriseExecutionService:
    return EnterpriseExecutionService()
