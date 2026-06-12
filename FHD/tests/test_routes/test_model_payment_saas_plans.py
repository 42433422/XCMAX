"""model-payment 与 saas_plans 集成。"""

from __future__ import annotations

from app.fastapi_routes.model_payment import _all_plans, _plan_by_id


def test_all_plans_includes_saas_tiers() -> None:
    ids = {p["id"] for p in _all_plans()}
    assert "demo-starter" in ids
    assert "saas-starter" in ids
    assert "saas-growth" in ids


def test_plan_by_id_resolves_saas_plan() -> None:
    plan = _plan_by_id("saas-enterprise")
    assert plan is not None
    assert plan["amount_cents"] == 999900
