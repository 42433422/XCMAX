"""Compose current facts, governed goals and original execution receipts for XiaoC."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enterprise_cognition.contracts import INPUT_MODELS


def _order_observation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Report observed fulfillment facts without inventing a promised date or cause."""
    if snapshot.get("freshness") != "fresh":
        return {"status": "unknown", "reason": "当前权威状态不可读，不能判断订单进度。"}
    state = snapshot.get("state") or {}
    remaining = state.get("remaining_quantity")
    try:
        unfulfilled = remaining is not None and Decimal(str(remaining)) > 0
    except InvalidOperation:
        unfulfilled = False
    return {
        "status": "observed",
        "facts": {
            "commercial_state": state.get("state"),
            "fulfillment": state.get("fulfillment"),
            "remaining_quantity": remaining,
            "quantity_unit": state.get("quantity_unit"),
        },
        "delay_status": "unknown",
        "root_cause": "unknown",
        "reason": "订单源未提供承诺交期和经核验的延期原因，未交数量不能单独证明已延期。",
        "suggestion": (
            "先核对约定交期、库存和履约条件；对已绑定目标生成方案后沿原任务审批链派发。"
            if unfulfilled
            else "核对目标和当前履约回执；缺少可比指标时不声称经营目标已经达成。"
        ),
        "evidence": snapshot.get("evidence") or [],
    }


def _goal_progress(goal: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    from app.application.enterprise_cognition.goals import GoalBindingError, metric_value

    try:
        value = metric_value(snapshot, goal["metric"], goal["unit"])
        target = Decimal(str(goal["target"]))
        met = value >= target if goal["direction"] == "increase" else value <= target
        deadline = (
            datetime.fromisoformat(goal["deadline"].replace("Z", "+00:00"))
            if goal.get("deadline")
            else None
        )
        return {
            "goal_id": goal["goal_id"],
            "current": str(value),
            "target": str(target),
            "unit": goal["unit"],
            "target_met": met,
            "goal_deadline_missed": deadline <= datetime.now(UTC) and not met if deadline else None,
            "deadline_source": "user_goal" if deadline else None,
            "order_promised_date_inferred": False,
            "source_version": snapshot["source_version"],
            "observed_at": snapshot["observed_at"],
        }
    except (GoalBindingError, ValueError, TypeError, InvalidOperation):
        return {"goal_id": goal["goal_id"], "status": "unknown", "target_met": None}


class EnterpriseCognitionService:
    def __init__(self, *, projections=None, goals=None, execution=None, outcomes=None):
        self._projections = projections
        self._goals = goals
        self._execution = execution
        self._outcomes = outcomes

    @property
    def projections(self):
        if self._projections is None:
            from app.application.enterprise_cognition.projection import get_projection_service

            self._projections = get_projection_service()
        return self._projections

    @property
    def goals(self):
        if self._goals is None:
            from app.application.enterprise_cognition.goals import get_goal_service

            self._goals = get_goal_service()
        return self._goals

    def query(self, params: dict, **scope) -> dict[str, Any]:
        entity_type, entity_id = params["entity_type"], params.get("entity_id")
        references: dict[str, Any] = (
            {"refs": [{"entity_type": entity_type, "entity_id": entity_id}], "has_more": False}
            if entity_id
            else self.projections.list_refs(entity_type, limit=params["limit"], **scope)
        )
        snapshots = [
            self.projections.get(
                entity_type,
                ref["entity_id"],
                force_refresh=params["force_refresh"],
                **scope,
            )
            for ref in references["refs"]
        ]
        ids = {snapshot["entity_id"] for snapshot in snapshots}
        goals = self.goals.list(entity_type=entity_type, entity_ids=ids, **scope) if ids else []
        states = {row["entity_id"]: row for row in snapshots}
        return {
            "snapshots": snapshots,
            "goals": goals,
            "goal_scope": "current_actor_visible_recent_50_for_selected_entities",
            "goals_may_be_truncated": len(goals) == 50,
            "goal_progress": [_goal_progress(goal, states[goal["entity_id"]]) for goal in goals],
            "observations": [
                {"entity_id": row["entity_id"], **_order_observation(row)}
                for row in snapshots
                if entity_type == "order"
            ],
            "scope": "current_actor_visible_recent" if not entity_id else "requested_entity",
            "has_more": references.get("has_more", False),
            "current_state_verified": references.get("freshness", "fresh") == "fresh"
            and all(row["freshness"] == "fresh" for row in snapshots),
            "reference_status": references.get("freshness", "fresh"),
            "business_data_written": False,
        }

    def invoke(self, action: str, params: dict, *, context: dict[str, Any]) -> Any:
        from app.infrastructure.auth.agent_mod_scope import (
            _bound_actor,
            agent_mod_execution_scope,
        )
        from app.infrastructure.tenant_scope import owned_tenant_scope

        model = INPUT_MODELS.get(action)
        if model is None:
            raise ValueError("unsupported_enterprise_operation")
        parsed = model.model_validate(params).model_dump(mode="json")
        actor = _bound_actor(context)
        tenant = str(context.get("tenant_id") or "")
        if not tenant.isdigit() or int(tenant) <= 0 or str(actor.tenant_id) != tenant:
            raise PermissionError("enterprise_tenant_mismatch")
        scope = {
            "tenant_id": tenant,
            "actor_id": str(actor.id),
            "mod_id": str(context.get("mod_id") or ""),
        }
        with (
            owned_tenant_scope(int(tenant)),
            agent_mod_execution_scope(context.get("_mod_authorization")),
        ):
            if action == "catalog":
                from app.domain.enterprise_cognition.catalog import entity_catalog

                return {"entities": entity_catalog(), "read_only_sources": True}
            if action == "query":
                return self.query(parsed, **scope)
            if action == "goals":
                return (
                    self.goals.get(parsed["goal_id"], **scope)
                    if parsed["goal_id"]
                    else self.goals.list(**scope)
                )
            if action == "bind_goal":
                return self.goals.create(parsed, **scope)
            if action == "plan":
                if self._execution is None:
                    from app.application.enterprise_cognition.execution import get_execution_service

                    self._execution = get_execution_service()
                return self._execution.plan(**parsed, runtime_context=context, **scope)
            if self._outcomes is None:
                from app.application.enterprise_cognition.outcomes import OutcomeService

                self._outcomes = OutcomeService()
            observation = self._outcomes.evaluate(**parsed, **scope)
            if observation.get("observation_verified") is True:
                from app.application.business_harness_projection import (
                    project_enterprise_outcome_to_conversation,
                )

                project_enterprise_outcome_to_conversation(
                    parsed["run_id"], observation, repository=self._outcomes.repository
                )
            return observation


def get_cognition_service() -> EnterpriseCognitionService:
    return EnterpriseCognitionService()
