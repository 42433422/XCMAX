"""saas_plans 预算档位与永久购买定价。"""

from __future__ import annotations

from app.infrastructure.billing import saas_plans as sp


def test_permanent_plan_prices_by_budget() -> None:
    sp.load_saas_plans_config.cache_clear()
    cases = [
        ("1–5 万", "saas-permanent-starter", 4_999_900),
        ("5–10 万", "saas-permanent-growth", 9_999_900),
        ("10–50 万", "saas-permanent-max", 49_999_900),
        ("50–100 万", "saas-permanent-ultra", 99_999_900),
    ]
    for budget, plan_id, cents in cases:
        plan = sp.permanent_plan_for_budget(budget)
        assert plan is not None
        assert plan["id"] == plan_id
        assert plan["amount_cents"] == cents


def test_pricing_plans_for_budget_returns_trial_and_permanent() -> None:
    sp.load_saas_plans_config.cache_clear()
    plans = sp.pricing_plans_for_budget("10–50 万")
    ids = [p["id"] for p in plans]
    assert ids == ["saas-trial-30", "saas-permanent-max"]
    assert plans[0]["quota_cents"] == 10_000
    assert plans[0]["expires_behavior"] == "freeze"
    assert plans[1]["account_tier"] == "max"


def test_normalize_budget_range_aliases() -> None:
    assert sp.normalize_budget_range("5-10万") == "5–10 万"
    assert sp.normalize_budget_range("200k-500k") == "10–50 万"
    assert sp.permanent_plan_id_for_budget("200k-500k") == "saas-permanent-max"
    assert sp.normalize_budget_range("5–20 万") == "5–10 万"
    assert sp.permanent_plan_id_for_budget("5–20 万") == "saas-permanent-growth"
