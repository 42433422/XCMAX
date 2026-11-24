"""Compose current facts, governed goals and original execution receipts for XiaoC."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.domain.enterprise_cognition.contracts import INPUT_MODELS
from app.domain.enterprise_cognition.world_observation import (
    delivery_scenario,
    public_snapshot,
    relationship_references,
)


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
        source = public_snapshot(snapshot)
        if source["knowledge_kind"] != "fact":
            raise GoalBindingError("goal_metric_evidence_unavailable")
        value = metric_value(source, goal["metric"], goal["unit"])
        target = Decimal(str(goal["target"]))
        met = value >= target if goal["direction"] == "increase" else value <= target
        deadline = (
            datetime.fromisoformat(goal["deadline"].replace("Z", "+00:00"))
            if goal.get("deadline")
            else None
        )
        declared_source = goal.get("source")
        declared_kind = (
            declared_source.get("kind") if isinstance(declared_source, dict) else None
        )
        return {
            "goal_id": goal["goal_id"],
            "knowledge_kind": "inference",
            "derivation": "deterministic_metric_target_comparison",
            "source_knowledge_kind": "fact",
            "goal_assertion_kind": (
                declared_kind if declared_kind in {"user_goal", "strategic_plan"} else "unknown"
            ),
            "evidence": source["evidence"],
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
        return {
            "goal_id": goal["goal_id"],
            "status": "unknown",
            "knowledge_kind": "unknown",
            "target_met": None,
        }


def _goal_gap(
    goal: dict[str, Any], snapshot: dict[str, Any], progress: dict[str, Any]
) -> dict[str, Any] | None:
    """A read-only candidate on an existing actor-bound objective, never a new approval."""
    if (
        progress.get("target_met") is not False
        or progress.get("goal_id") != goal.get("goal_id")
        or snapshot.get("freshness") != "fresh"
        or str(goal.get("tenant_id")) != snapshot.get("tenant_id")
        or goal.get("actor_id") != snapshot.get("actor_id")
        or goal.get("mod_id") != snapshot.get("mod_id")
        or goal.get("entity_type") != snapshot.get("entity_type")
        or goal.get("entity_id") != snapshot.get("entity_id")
        or not snapshot.get("evidence")
    ):
        return None
    try:
        now = datetime.now(UTC)
        observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(snapshot["expires_at"].replace("Z", "+00:00"))
        version = snapshot["source_version"]
        binding = goal["binding_sha256"]
        if (
            not observed <= now < expires
            or progress["source_version"] != version
            or not isinstance(version, str)
            or not version.startswith("sha256:")
            or len(version) != 71
            or any(char not in "0123456789abcdef" for char in version[7:])
            or not isinstance(binding, str)
            or len(binding) != 64
            or any(char not in "0123456789abcdef" for char in binding)
        ):
            return None
        current, target = Decimal(progress["current"]), Decimal(progress["target"])
        gap = target - current if goal["direction"] == "increase" else current - target
        if not gap.is_finite() or gap <= 0:
            return None
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation):
        return None
    evidence = {
        "goal_binding_sha256": binding,
        "source_version": version,
        "observed_at": snapshot["observed_at"],
        "expires_at": snapshot["expires_at"],
        "current": progress["current"],
        "target": progress["target"],
        "unit": progress["unit"],
        "gap": str(gap),
    }
    return {
        "candidate_id": "erp-gap:" + canonical_hash([binding, version]),
        "goal_id": goal["goal_id"],
        "entity_type": goal["entity_type"],
        "entity_id": goal["entity_id"],
        "status": "review_only",
        "reason": "bound_objective_not_met",
        "deadline_missed": progress.get("goal_deadline_missed"),
        "deadline_source": progress.get("deadline_source"),
        "evidence": evidence,
        "evidence_sha256": canonical_hash(evidence),
        "requires_original_approval": True,
        "execution_authorized": False,
    }


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
        if params.get("as_of") is not None:
            observation = self.projections.get(
                entity_type, entity_id, as_of=params["as_of"], **scope
            )
            return {
                "history": observation,
                "historical_observation_verified": observation.get("knowledge_kind") == "fact",
                "current_state_verified": False,
                "business_data_written": False,
            }
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
        progress = [_goal_progress(goal, states[goal["entity_id"]]) for goal in goals]
        gaps = [
            candidate
            for goal, measured in zip(goals, progress, strict=True)
            if (candidate := _goal_gap(goal, states[goal["entity_id"]], measured)) is not None
        ]
        return {
            "snapshots": snapshots,
            "relationships": [
                {"source_entity_id": row["entity_id"], **relation}
                for row in snapshots
                for relation in relationship_references(row)
            ],
            "scenario": (
                delivery_scenario(snapshots[0], params["scenario_delivery_quantity"])
                if params.get("scenario_delivery_quantity") is not None and snapshots
                else None
            ),
            "goals": goals,
            "goal_scope": "current_actor_visible_recent_50_for_selected_entities",
            "goals_may_be_truncated": len(goals) == 50,
            "goal_progress": progress,
            "operating_gap_candidates": gaps,
            "gap_scope": "current_actor_visible_bound_goals_not_company_wide_scan",
            "observations": [
                {"entity_id": row["entity_id"], **_order_observation(row)}
                for row in snapshots
                if entity_type == "order"
            ],
            "scope": "current_actor_visible_recent" if not entity_id else "requested_entity",
            "has_more": references.get("has_more", False),
            # Empty SELECT results are not positive evidence of an enterprise state.
            "current_state_verified": bool(snapshots)
            and references.get("freshness", "fresh") == "fresh"
            and all(row["freshness"] == "fresh" for row in snapshots),
            "reference_status": references.get("freshness", "fresh"),
            "reason_code": "no_visible_source_records" if not snapshots else None,
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

                return {
                    "entities": entity_catalog(),
                    "read_only_sources": True,
                    # Exposing transaction and journal rows does not prove an aggregate.
                    "unverified_aggregate_metrics": [
                        {
                            "metric": metric,
                            "knowledge_kind": "unknown",
                            "reason_code": "not_verified_by_current_projection",
                        }
                        for metric in (
                            "cash_balance",
                            "accounts_receivable_balance",
                            "accounts_payable_balance",
                            "available_inventory_balance",
                            "production_capacity",
                            "customer_satisfaction",
                        )
                    ],
                }
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


def cognition_result_verified(action: str, params: dict, result: dict) -> bool:
    """HTTP and model tools share the same epistemic success semantics."""
    if action == "evaluate":
        return result.get("observation_verified") is True
    if action != "query":
        return True
    if params.get("as_of") is not None:
        return result.get("historical_observation_verified") is True
    if params.get("scenario_delivery_quantity") is not None:
        return (result.get("scenario") or {}).get("knowledge_kind") == "prediction"
    return result.get("current_state_verified") is True


def get_cognition_service() -> EnterpriseCognitionService:
    return EnterpriseCognitionService()
