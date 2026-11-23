"""Goals retain source identity, account isolation and comparable metric units."""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.enterprise_cognition.goals import (
    GoalBindingError,
    GoalDefinition,
    GoalService,
    metric_value,
)
from app.db.models.enterprise_goal import EnterpriseGoalBinding


def definition(**overrides):
    return {
        "goal_id": "fulfill-order-42",
        "objective": "把订单 42 的剩余待发数量降为 0 件",
        "entity_type": "order",
        "entity_id": "42",
        "metric": "remaining_quantity",
        "unit": "件",
        "direction": "decrease",
        "target": "0",
        **overrides,
    }


class Projections:
    def __init__(self):
        self.calls = []
        self.version = "original-source-version"
        self.value = "10.125"
        self.freshness = "fresh"
        self.denied = False

    def get(self, entity_type, entity_id, **scope):
        if self.denied:
            raise PermissionError("entity_read_revoked")
        self.calls.append((entity_type, entity_id, dict(scope)))
        now = datetime.now(UTC)
        return {
            "tenant_id": scope["tenant_id"],
            "actor_id": scope["actor_id"],
            "mod_id": scope.get("mod_id", ""),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source": "sales_orders",
            "source_version": self.version,
            "observed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=60)).isoformat(),
            "freshness": self.freshness,
            "state": {"remaining_quantity": self.value, "quantity_unit": "件"},
            "evidence": [{"source": "sales_orders", "entity_id": entity_id}],
        }


@pytest.fixture
def goal_env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'goals.sqlite'}")
    EnterpriseGoalBinding.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    source = Projections()
    service = GoalService(session_factory=factory, projections=source)
    yield service, source, factory
    engine.dispose()


def test_original_goal_is_immutable_and_retry_does_not_create_another_version(goal_env):
    service, projections, factory = goal_env
    original = service.create(definition(), tenant_id=7, actor_id="19", mod_id="erp")
    again = service.create(definition(), tenant_id=7, actor_id="19", mod_id="erp")
    assert original == again
    assert original["source"] == {"kind": "user_goal", "asserted_by": "19"}
    assert original["target"] == "0"
    assert projections.calls[0][2] == {
        "tenant_id": 7,
        "actor_id": "19",
        "mod_id": "erp",
        "force_refresh": True,
    }
    with pytest.raises(GoalBindingError, match="already_bound"):
        service.create(definition(target="3"), tenant_id=7, actor_id="19", mod_id="erp")
    with factory() as db:
        assert db.query(EnterpriseGoalBinding).count() == 1
    assert service.get(original["goal_id"], tenant_id=7, actor_id="19", mod_id="erp") == original


@pytest.mark.parametrize("scope", [{"tenant_id": 8}, {"actor_id": "20"}, {"mod_id": "another-mod"}])
def test_goal_owner_tenant_and_mod_are_independent_boundaries(goal_env, scope):
    service, _projections, _factory = goal_env
    own = {"tenant_id": 7, "actor_id": "19", "mod_id": "erp"}
    service.create(definition(), **own)
    foreign = {**own, **scope}
    assert service.list(**foreign) == []
    with pytest.raises(GoalBindingError, match="not_found"):
        service.get("fulfill-order-42", **foreign)


def test_permission_revocation_is_checked_even_for_persisted_goal_metadata(goal_env):
    service, projections, _factory = goal_env
    service.create(definition(), tenant_id=7, actor_id="19")
    projections.denied = True
    with pytest.raises(PermissionError, match="revoked"):
        service.get("fulfill-order-42", tenant_id=7, actor_id="19")
    with pytest.raises(PermissionError, match="revoked"):
        service.list(tenant_id=7, actor_id="19")


@pytest.mark.parametrize("value", [True, None, "NaN", "Infinity", "10 days", {}, []])
def test_unknown_or_nonfinite_source_metric_cannot_become_a_numeric_goal(goal_env, value):
    service, projections, factory = goal_env
    projections.value = value
    with pytest.raises(GoalBindingError):
        service.create(definition(), tenant_id=7, actor_id="19")
    with factory() as db:
        assert db.query(EnterpriseGoalBinding).count() == 0


@pytest.mark.parametrize("target", [True, "NaN", "Infinity", float("nan")])
def test_nonfinite_or_boolean_goal_target_is_rejected(target):
    with pytest.raises(ValidationError):
        GoalDefinition.model_validate(definition(target=target))


def test_metric_units_and_unknown_projection_fail_closed(goal_env):
    service, projections, _factory = goal_env
    with pytest.raises(GoalBindingError, match="unit"):
        service.create(definition(unit="箱"), tenant_id=7, actor_id="19")
    projections.freshness = "unknown"
    with pytest.raises(GoalBindingError, match="state_unavailable"):
        service.create(definition(), tenant_id=7, actor_id="19")


def test_decimal_source_value_retains_precision_and_explicit_units(goal_env):
    _service, projections, _factory = goal_env
    projections.value = "12345678901234567890.123456789"
    state = projections.get("order", "42", tenant_id=7, actor_id="19")
    assert metric_value(state, "remaining_quantity", "件") == Decimal(projections.value)
    state["state"] = {"paid_amount": "99.999", "currency": "CNY"}
    assert metric_value(state, "paid_amount", "CNY") == Decimal("99.999")
    with pytest.raises(GoalBindingError, match="unit"):
        metric_value(state, "paid_amount", "USD")
    state["state"] = {"score": "2", "metric_units": {"score": "points"}}
    assert metric_value(state, "score", "points") == Decimal(2)


def test_strategic_plan_binding_uses_the_existing_reader_and_exact_content_hash(goal_env):
    service, _projections, _factory = goal_env
    plan = {
        "quarter": "2026-Q4",
        "generated_at": "2026-11-21T00:00:00Z",
        "features": [{"title": "减少订单延期", "success_metric": "待发数量下降"}],
    }
    service.strategic_reader = lambda: copy.deepcopy(plan)
    payload = definition(strategic_plan_sha256=canonical_hash(plan), strategic_feature_index=0)
    goal = service.create(payload, tenant_id=7, actor_id="19")
    assert goal["source"]["authority"] == "strategic_plan_app_service.latest_plan"
    assert goal["source"]["plan_sha256"] == canonical_hash(plan)
    assert goal["source"]["title"] == "减少订单延期"
    with pytest.raises(GoalBindingError, match="changed_or_unavailable"):
        service.create(
            {**payload, "goal_id": "invented-plan", "strategic_plan_sha256": "0" * 64},
            tenant_id=7,
            actor_id="19",
        )
    with pytest.raises(GoalBindingError, match="feature_required"):
        service.create(
            definition(strategic_plan_sha256=canonical_hash(plan)), tenant_id=7, actor_id="19"
        )
