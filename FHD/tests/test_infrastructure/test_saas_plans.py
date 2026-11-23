"""公开统一价格、预算边界与历史订单目录。"""

from __future__ import annotations

from app.infrastructure.billing import saas_plans as sp


def test_permanent_price_does_not_depend_on_customer_budget() -> None:
    sp.load_saas_plans_config.cache_clear()
    for budget in (None, "", "1–5 万", "5–10 万", "10–50 万", "50–100 万", "500k-plus"):
        plan = sp.permanent_plan_for_budget(budget)
        assert plan is not None
        assert plan["id"] == "saas-permanent-standard"
        assert plan["amount_cents"] == 680_000
        assert plan["account_tier"] == "normal"
        assert plan["quota_cents"] == 0


def test_public_catalog_keeps_free_and_original_trial() -> None:
    sp.load_saas_plans_config.cache_clear()
    plans = sp.pricing_plans_for_budget("10–50 万")
    ids = [p["id"] for p in plans]
    assert ids == [
        "saas-personal-free",
        "saas-trial-30",
        "saas-permanent-standard",
    ]
    assert plans[0]["amount_cents"] == 0
    assert plans[1]["amount_cents"] == 9_900
    assert plans[1]["quota_cents"] == 10_000
    assert plans[1]["duration_days"] == 30
    assert plans[1]["expires_behavior"] == "freeze"


def test_historical_plans_resolve_without_reopening_sales() -> None:
    public_ids = {plan["id"] for plan in sp.list_saas_plans()}
    for suffix, amount, tier in (
        ("starter", 4_999_900, "normal"),
        ("growth", 9_999_900, "pro"),
        ("max", 49_999_900, "max"),
        ("ultra", 99_999_900, "ultra"),
    ):
        plan_id = "saas-permanent-" + suffix
        assert plan_id not in public_ids
        assert sp.plan_by_id(plan_id)["amount_cents"] == amount
        assert sp.plan_by_id(plan_id)["account_tier"] == tier
        assert sp.is_saas_plan_id(plan_id) and sp.is_permanent_saas_plan_id(plan_id)
    assert not sp.is_permanent_saas_plan_id("saas-permanent-forged")
    assert sp.budget_permanent_map() == {}
