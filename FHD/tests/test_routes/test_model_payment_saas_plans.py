"""model-payment 与 saas_plans 集成。"""

from __future__ import annotations

from app.fastapi_routes.model_payment import _all_plans, _plan_by_id
from app.infrastructure.billing import saas_plans as sp


def setup_function() -> None:
    sp.load_saas_plans_config.cache_clear()


def test_all_plans_includes_saas_tiers() -> None:
    ids = {p["id"] for p in _all_plans()}
    assert "demo-starter" in ids
    assert "saas-trial-30" in ids
    assert "saas-permanent-starter" in ids


def test_plan_by_id_resolves_permanent_plan() -> None:
    plan = _plan_by_id("saas-permanent-ultra")
    assert plan is not None
    assert plan["amount_cents"] == 99_999_900


def test_plan_by_id_resolves_trial_plan() -> None:
    plan = _plan_by_id("saas-trial-30")
    assert plan is not None
    assert plan["amount_cents"] == 9900
