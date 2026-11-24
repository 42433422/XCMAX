import json
from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import strategy_business_context as business
from modstore_server import strategy_planner


def evidence():
    return {
        "source_owner": "java_postgresql_internal_api",
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": 90,
        "source_available": True,
        "source_authoritative": True,
        "append_only_store_available": True,
        "value_ledger_ready": True,
        "verified_paid_count": 4,
        "verified_paid_amount_cents": 19999600,
        "provider_payment_breakdown_cents": {
            "wallet_topup": 9900,
            "product_service": 19989700,
            "other": 0,
        },
        "customer_goal_count": 5,
        "paid_delivery_count": 3,
        "paid_acceptance_count": 2,
        "complete_customer_count": 1,
        "six_stage_counts": dict(
            payment=4, installation=3, first_use=3, outcome=2, acceptance=2, reuse=1
        ),
        "lifecycle_gaps": {"reuse": 3},
        "desktop_release_source_available": True,
        "customers": [{"customer_alias": "private-customer", "order_no": "private-order"}],
        "private_note": "private-customer-text",
    }


def test_actual_ledger_aggregate_reaches_strategy_without_customer_data(monkeypatch):
    original = evidence()
    original["lifecycle_gaps"]["private-gap-key"] = 42
    monkeypatch.setattr(business, "build_customer_value_evidence", lambda **kwargs: original)
    monkeypatch.setattr(strategy_planner.strategy_bets, "apply_evidence_defaults", lambda: None)
    monkeypatch.setattr(strategy_planner.strategy_bets, "active_bets", lambda: [])
    for name in ("_model_assets", "_repo_signals", "_domain_status"):
        monkeypatch.setattr(strategy_planner, name, lambda: {"status": "unknown"})
    observed = strategy_planner.collect_context()["customer_value"]
    assert observed["status"] == "ok"
    assert observed["source_owner"] == "java_postgresql_internal_api"
    assert observed["verified_paid_count"] == 4
    assert observed["verified_paid_amount_cents"] == 19999600
    assert observed["provider_payment_breakdown_cents"]["wallet_topup"] == 9900
    assert observed["financial_basis"] == "eligible_CNY_provider_payments_not_bank_or_accounting"
    assert observed["six_stage_counts"]["reuse"] == 1
    assert observed["lifecycle_gaps"]["reuse"] == 3
    assert "private-" not in json.dumps(observed)
    assert "customers" not in observed


@pytest.mark.parametrize(
    "missing",
    [
        "source_available",
        "source_authoritative",
        "append_only_store_available",
        "value_ledger_ready",
    ],
)
def test_unavailable_source_does_not_look_like_zero_business(monkeypatch, missing):
    original = evidence()
    original[missing] = False
    monkeypatch.setattr(business, "build_customer_value_evidence", lambda **kwargs: original)
    observed = business.customer_value_context()
    assert observed["status"] == "unknown"
    assert observed["value_ledger_ready"] is False
    assert "verified_paid_count" not in observed and "six_stage_counts" not in observed


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(source_owner="injected"),
        lambda row: row.update(window_days=30),
        lambda row: row.update(window_days="90"),
        lambda row: row.pop("window_days"),
        lambda row: row.update(six_stage_counts=None),
        lambda row: row.update(lifecycle_gaps=[]),
        lambda row: row.pop("lifecycle_gaps"),
        lambda row: row.update(verified_paid_count=True),
        lambda row: row.update(verified_paid_amount_cents=-1),
        lambda row: row.update(provider_payment_breakdown_cents=None),
        lambda row: row["provider_payment_breakdown_cents"].update(other=1),
        lambda row: row["provider_payment_breakdown_cents"].update(private_note=0),
        lambda row: row.update(generated_at="not-a-timestamp"),
        lambda row: row.update(generated_at=(datetime.now(UTC) + timedelta(days=1)).isoformat()),
        lambda row: row["six_stage_counts"].update(reuse="customer-text"),
    ],
)
def test_malformed_or_injected_evidence_remains_unknown(monkeypatch, mutation):
    original = evidence()
    mutation(original)
    monkeypatch.setattr(business, "build_customer_value_evidence", lambda **kwargs: original)
    observed = business.customer_value_context()
    assert observed["status"] == "unknown"
    assert "verified_paid_count" not in observed


def test_payment_source_exception_does_not_abort_other_strategy_observation(monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("private upstream detail")

    monkeypatch.setattr(business, "build_customer_value_evidence", unavailable)
    observed = business.customer_value_context()
    assert observed["status"] == "unknown"
    assert "private" not in json.dumps(observed)
