"""Bind operating objectives to existing entity projections and strategic-plan evidence."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import utc_now_iso
from app.db.models.enterprise_goal import EnterpriseGoalBinding
from app.domain.enterprise_cognition.goal_contract import GoalDefinition
from app.domain.enterprise_cognition.goals import GoalBindingError, metric_value


def _decode_goal(record: EnterpriseGoalBinding) -> dict[str, Any]:
    data = json.loads(record.definition_json)
    if not isinstance(data, dict):
        raise GoalBindingError("goal_binding_invalid")
    content = {
        key: value for key, value in data.items() if key not in {"binding_sha256", "created_at"}
    }
    if (
        canonical_hash(content) != record.binding_sha256
        or data.get("binding_sha256") != record.binding_sha256
        or (data.get("tenant_id"), data.get("actor_id"), data.get("mod_id"), data.get("goal_id"))
        != (record.tenant_id, record.actor_id, record.mod_id, record.goal_id)
        or (data.get("entity_type"), data.get("entity_id"))
        != (record.entity_type, record.entity_id)
    ):
        raise GoalBindingError("goal_binding_invalid")
    return data


class GoalService:
    def __init__(self, session_factory=None, *, projections=None, strategic_reader=None):
        if session_factory is None:
            from app.db import HostSessionLocal

            session_factory = HostSessionLocal
        if projections is None:
            from app.application.enterprise_cognition.projection import get_projection_service

            projections = get_projection_service()
        if strategic_reader is None:
            from app.application.autonomy.strategic_plan_app_service import latest_plan

            strategic_reader = latest_plan
        self.session_factory = session_factory
        self.projections = projections
        self.strategic_reader: Callable[[], dict[str, Any] | None] = strategic_reader

    @staticmethod
    def _scope(tenant_id, actor_id, mod_id):
        if isinstance(tenant_id, bool) or not str(tenant_id).isdigit() or int(tenant_id) < 1:
            raise GoalBindingError("tenant_required")
        if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 128:
            raise GoalBindingError("actor_required")
        if not isinstance(mod_id, str) or len(mod_id) > 128:
            raise GoalBindingError("invalid_mod_scope")
        return int(tenant_id), actor_id, mod_id

    def _query(self, tenant_id, actor_id, mod_id):
        tenant, actor, mod = self._scope(tenant_id, actor_id, mod_id)
        return select(EnterpriseGoalBinding).where(
            EnterpriseGoalBinding.tenant_id == tenant,
            EnterpriseGoalBinding.actor_id == actor,
            EnterpriseGoalBinding.mod_id == mod,
        )

    def state(self, goal, *, tenant_id, actor_id, mod_id="", force_refresh=False):
        return self.projections.get(
            goal["entity_type"],
            goal["entity_id"],
            tenant_id=tenant_id,
            actor_id=actor_id,
            mod_id=mod_id,
            force_refresh=force_refresh,
        )

    def _source(self, definition: GoalDefinition, actor_id: str) -> dict[str, Any]:
        digest, index = definition.strategic_plan_sha256, definition.strategic_feature_index
        if (digest is None) != (index is None):
            raise GoalBindingError("strategic_plan_and_feature_required")
        source: dict[str, Any] = {"kind": "user_goal", "asserted_by": actor_id}
        if digest is None:
            return source
        plan = self.strategic_reader()
        if not isinstance(plan, dict) or canonical_hash(plan) != digest:
            raise GoalBindingError("strategic_plan_changed_or_unavailable")
        features = plan.get("features")
        if not isinstance(features, list) or index is None or index >= len(features):
            raise GoalBindingError("strategic_feature_missing")
        feature = features[index]
        if not isinstance(feature, dict) or not feature.get("title"):
            raise GoalBindingError("strategic_feature_missing")
        # A selected strategy is provenance for the proposed objective, not proof
        # of an operational outcome or permission to execute a workflow.
        source.update(
            {
                "kind": "strategic_plan",
                "authority": "strategic_plan_app_service.latest_plan",
                "plan_sha256": digest,
                "feature_index": index,
                "quarter": plan.get("quarter"),
                "generated_at": plan.get("generated_at"),
                "title": feature["title"],
                "success_metric": feature.get("success_metric"),
            }
        )
        return source

    def create(self, definition, *, tenant_id, actor_id, mod_id="") -> dict[str, Any]:
        tenant, actor, mod = self._scope(tenant_id, actor_id, mod_id)
        parsed = GoalDefinition.model_validate(definition)
        data: dict[str, Any] = parsed.model_dump(mode="json")
        snapshot = self.state(
            data, tenant_id=tenant, actor_id=actor, mod_id=mod, force_refresh=True
        )
        metric_value(snapshot, parsed.metric, parsed.unit)
        data["source"] = self._source(parsed, actor)
        data.update(tenant_id=tenant, actor_id=actor, mod_id=mod)
        binding = canonical_hash(data)
        query = self._query(tenant, actor, mod).where(
            EnterpriseGoalBinding.goal_id == parsed.goal_id
        )
        with self.session_factory() as db:
            existing = db.execute(query).scalar_one_or_none()
            if existing is None:
                data.update(binding_sha256=binding, created_at=utc_now_iso())
                db.add(
                    EnterpriseGoalBinding(
                        tenant_id=tenant,
                        actor_id=actor,
                        mod_id=mod,
                        goal_id=parsed.goal_id,
                        entity_type=parsed.entity_type,
                        entity_id=parsed.entity_id,
                        definition_json=json.dumps(data, ensure_ascii=False, allow_nan=False),
                        binding_sha256=binding,
                        created_at=data["created_at"],
                    )
                )
                try:
                    db.commit()
                    return data
                except IntegrityError:
                    db.rollback()
                    existing = db.execute(query).scalar_one_or_none()
                    if existing is None:
                        raise
            if existing.binding_sha256 != binding:
                raise GoalBindingError("goal_id_already_bound")
            return _decode_goal(existing)

    def get(self, goal_id, *, tenant_id, actor_id, mod_id="") -> dict[str, Any]:
        query = self._query(tenant_id, actor_id, mod_id).where(
            EnterpriseGoalBinding.goal_id == str(goal_id)
        )
        with self.session_factory() as db:
            record = db.execute(query).scalar_one_or_none()
            if record is None:
                raise GoalBindingError("goal_not_found")
            goal = _decode_goal(record)
        # Cached goal metadata never grants access after a permission revocation.
        self.state(goal, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id)
        return goal

    def list(
        self,
        *,
        tenant_id,
        actor_id,
        mod_id="",
        limit=50,
        entity_type=None,
        entity_ids=None,
    ) -> list[dict[str, Any]]:
        query = self._query(tenant_id, actor_id, mod_id)
        if entity_type is not None or entity_ids is not None:
            if entity_type is None or entity_ids is None:
                raise GoalBindingError("goal_entity_filter_incomplete")
            query = query.where(
                EnterpriseGoalBinding.entity_type == entity_type,
                EnterpriseGoalBinding.entity_id.in_(entity_ids),
            )
        query = query.order_by(EnterpriseGoalBinding.id.desc()).limit(max(1, min(int(limit), 100)))
        with self.session_factory() as db:
            goals = [_decode_goal(row) for row in db.execute(query).scalars()]
        for goal in goals:
            self.state(goal, tenant_id=tenant_id, actor_id=actor_id, mod_id=mod_id)
        return goals


def get_goal_service() -> GoalService:
    return GoalService()
