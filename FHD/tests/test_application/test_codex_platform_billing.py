"""Authenticated platform receipts are audit-only, even with a live wallet backend."""

from dataclasses import replace

import pytest

from app.infrastructure.billing import model_usage as ledger
from app.infrastructure.billing.model_reservation import (
    ModelReservationError,
    record_platform_model_usage,
)
from app.infrastructure.codex.policy import ModelRoute


@pytest.fixture
def account_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    for name in ("_apply_wallet_debit", "_apply_market_wallet_debit"):
        monkeypatch.setattr(ledger, name, lambda *a, **k: pytest.fail("second wallet charge"))
    route = ModelRoute(
        "https://platform.example/v1",
        "litellm/qwen",
        "litellm",
        "qwen",
        32000,
        4000,
        response_model="qwen-snapshot",
        gateway_kind="market",
        credential="account-secret",
        route_token="route-secret",
        config_revision="revision-1",
        key_source="platform",
    )
    usage = {"prompt_tokens": 1500, "completion_tokens": 500, "total_tokens": 2000}
    receipt = {
        "schema": "xcmax.responses-billing.v1",
        "provider": "litellm",
        "model": "qwen",
        "key_source": "platform",
        "config_revision": "revision-1",
        "client_request_id": "req-1",
        "request_id": "platform-req-1",
        "hold_no": "hold-1",
        "billed": True,
        "charge_amount": "0.02",
        "billing_status": "settled",
        "usage": {"input_tokens": 1500, "output_tokens": 500, "total_tokens": 2000},
    }
    return {
        "usage_key": "usage-1",
        "run_id": "run-1",
        "user_id": "71",
        "request_id": "req-1",
        "route": route,
        "usage": usage,
        "receipt": receipt,
    }


def test_settlement_is_idempotent_and_never_debits_either_wallet(account_usage):
    first = record_platform_model_usage(**account_usage)
    second = record_platform_model_usage(**account_usage)
    assert first == second
    assert first["wallet_backend"] == "audit" and first["cost_units"] == 2
    assert first["billing_source"] == "platform_xcagi"
    assert len(ledger.list_model_usage_entries(run_id="run-1")) == 1
    assert "account-secret" not in str(first) and "route-secret" not in str(first)


def test_byok_remains_free_and_keeps_platform_receipt(account_usage):
    account_usage["route"] = replace(account_usage["route"], key_source="user_override")
    account_usage["receipt"].update(
        key_source="user_override",
        billing_status="byok",
        billed=False,
        charge_amount="0.00",
        hold_no="",
    )
    row = record_platform_model_usage(**account_usage)
    assert row["metadata"]["platform_receipt"]["billing_status"] == "byok"


@pytest.mark.parametrize(
    "override",
    [
        {"provider": "other"},
        {"model": "litellm/qwen"},
        {"key_source": "user_override"},
        {"config_revision": "revision-2"},
        {"client_request_id": "other"},
        {"billing_status": "pending"},
        {"billed": False},
        {"hold_no": ""},
        {"charge_amount": "NaN"},
        {"charge_amount": "-1"},
        {"usage": {"input_tokens": 1500, "output_tokens": 500}},
        {"usage": {"input_tokens": 1500, "output_tokens": 500, "total_tokens": 3000}},
    ],
)
def test_unbound_or_unsettled_receipt_cannot_release_a_task(account_usage, override):
    account_usage["receipt"].update(override)
    with pytest.raises(ModelReservationError):
        record_platform_model_usage(**account_usage)
    assert ledger.list_model_usage_entries(run_id="run-1") == []


def test_missing_receipt_is_allowed_only_for_known_unstarted_attempt(account_usage):
    account_usage["receipt"] = None
    with pytest.raises(ModelReservationError):
        record_platform_model_usage(**account_usage)
    account_usage["usage"] = dict.fromkeys(account_usage["usage"], 0)
    row = record_platform_model_usage(**account_usage)
    assert row["cost_units"] == 0


def test_existing_request_cannot_be_rebound_to_different_account(account_usage):
    record_platform_model_usage(**account_usage)
    account_usage["user_id"] = "72"
    with pytest.raises(ModelReservationError, match="cannot be rebound"):
        record_platform_model_usage(**account_usage)
    assert ledger.list_model_usage_entries(run_id="run-1")[0]["user_id"] == "71"
