"""Branch coverage tests for app.infrastructure.billing.model_usage.

Covers branches in: _coerce_int, llm_tokens_per_cost_unit, estimate_llm_cost_units,
model_usage_ledger_path, _load_usage_state, _safe_metadata, _usage_summary,
_wallet_required, model_usage_wallet_backend, _wallet_user_id, _wallet_snapshot,
_apply_wallet_debit, _money, _market_amount_for_cost_units, _market_base_url,
_strip_bearer, _market_auth_token, _market_timeout, _market_post_json,
_apply_market_wallet_debit, _apply_market_wallet_refund, set_model_wallet_balance,
get_model_wallet, record_model_usage, record_tool_usage, refund_tool_usage,
_record_usage_entry, list_model_usage_entries.

Uses an isolated ledger file (via MODEL_USAGE_LEDGER_PATH env) to avoid global state pollution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.billing import model_usage as mu

# ---------------------------------------------------------------------------
# Autouse fixture — isolate ledger path and env vars
# ---------------------------------------------------------------------------


_ENV_KEYS = [
    "MODEL_USAGE_LEDGER_PATH",
    "MODEL_USAGE_WALLET_REQUIRED",
    "MODEL_USAGE_WALLET_BACKEND",
    "FHD_LLM_TOKENS_PER_COST_UNIT",
    "MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT",
    "MODEL_USAGE_MARKET_MIN_CHARGE",
    "MODEL_USAGE_MARKET_BASE_URL",
    "XCAGI_MARKET_BASE_URL",
    "MODSTORE_PLATFORM_URL",
    "MODEL_USAGE_MARKET_AUTH_TOKEN",
    "XCAGI_MARKET_AUTH_TOKEN",
    "MODSTORE_AUTH_TOKEN",
    "MODEL_USAGE_MARKET_TIMEOUT",
]


@pytest.fixture(autouse=True)
def _isolate_ledger_and_env(tmp_path, monkeypatch):
    """Redirect ledger to a tmp file and clear all wallet env vars before each test."""
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger))
    for key in _ENV_KEYS:
        if key != "MODEL_USAGE_LEDGER_PATH":
            monkeypatch.delenv(key, raising=False)
    yield
    # Cleanup is automatic via tmp_path + monkeypatch


# ---------------------------------------------------------------------------
# _coerce_int
# ---------------------------------------------------------------------------


class TestCoerceInt:
    def test_int_value(self):
        assert mu._coerce_int(42) == 42

    def test_string_int(self):
        assert mu._coerce_int("100") == 100

    def test_none(self):
        assert mu._coerce_int(None) == 0

    def test_empty_string(self):
        assert mu._coerce_int("") == 0

    def test_float(self):
        assert mu._coerce_int(3.7) == 3

    def test_invalid_string(self):
        assert mu._coerce_int("abc") == 0

    def test_list_raises_type_error(self):
        assert mu._coerce_int([1, 2]) == 0

    def test_dict_raises_type_error(self):
        assert mu._coerce_int({"a": 1}) == 0


# ---------------------------------------------------------------------------
# llm_tokens_per_cost_unit
# ---------------------------------------------------------------------------


class TestLlmTokensPerCostUnit:
    def test_default(self):
        assert mu.llm_tokens_per_cost_unit() == mu.DEFAULT_LLM_TOKENS_PER_COST_UNIT

    def test_env_set_valid(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_TOKENS_PER_COST_UNIT", "500")
        assert mu.llm_tokens_per_cost_unit() == 500

    def test_env_set_zero_returns_default(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_TOKENS_PER_COST_UNIT", "0")
        assert mu.llm_tokens_per_cost_unit() == mu.DEFAULT_LLM_TOKENS_PER_COST_UNIT

    def test_env_set_negative_returns_default(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_TOKENS_PER_COST_UNIT", "-5")
        assert mu.llm_tokens_per_cost_unit() == mu.DEFAULT_LLM_TOKENS_PER_COST_UNIT

    def test_env_set_invalid_returns_default(self, monkeypatch):
        monkeypatch.setenv("FHD_LLM_TOKENS_PER_COST_UNIT", "abc")
        assert mu.llm_tokens_per_cost_unit() == mu.DEFAULT_LLM_TOKENS_PER_COST_UNIT


# ---------------------------------------------------------------------------
# estimate_llm_cost_units
# ---------------------------------------------------------------------------


class TestEstimateLlmCostUnits:
    def test_total_tokens_provided(self):
        result = mu.estimate_llm_cost_units(total_tokens=2500)
        # 2500 / 1000 = 2.5 → ceil = 3
        assert result == 3

    def test_prompt_plus_completion(self):
        result = mu.estimate_llm_cost_units(prompt_tokens=500, completion_tokens=600)
        # 1100 / 1000 = 1.1 → ceil = 2
        assert result == 2

    def test_zero_tokens(self):
        assert mu.estimate_llm_cost_units() == 0

    def test_negative_total_uses_prompt_completion(self):
        result = mu.estimate_llm_cost_units(total_tokens=-1, prompt_tokens=100, completion_tokens=200)
        # 300 / 1000 = 0.3 → ceil = 1, max(1, 1) = 1
        assert result == 1

    def test_minimum_one(self):
        result = mu.estimate_llm_cost_units(prompt_tokens=1, completion_tokens=0)
        # 1 / 1000 = 0.001 → ceil = 1, max(1, 1) = 1
        assert result == 1


# ---------------------------------------------------------------------------
# model_usage_ledger_path
# ---------------------------------------------------------------------------


class TestModelUsageLedgerPath:
    def test_custom_path(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", "/custom/ledger.json")
        assert mu.model_usage_ledger_path() == Path("/custom/ledger.json")

    def test_custom_path_stripped(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", "  /custom/ledger.json  ")
        assert mu.model_usage_ledger_path() == Path("/custom/ledger.json")

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("MODEL_USAGE_LEDGER_PATH", raising=False)
        path = mu.model_usage_ledger_path()
        assert path.name == "model_usage_ledger.json"
        assert "data" in path.parts


# ---------------------------------------------------------------------------
# _load_usage_state
# ---------------------------------------------------------------------------


class TestLoadUsageState:
    def test_file_not_exists(self):
        assert mu._load_usage_state() == mu._empty_usage_state()

    def test_file_corrupt_json(self, tmp_path):
        ledger = mu.model_usage_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("not json{", encoding="utf-8")
        state = mu._load_usage_state()
        assert state == mu._empty_usage_state()

    def test_file_not_dict(self, tmp_path):
        ledger = mu.model_usage_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("[1, 2, 3]", encoding="utf-8")
        state = mu._load_usage_state()
        assert state == mu._empty_usage_state()

    def test_entries_not_list(self, tmp_path):
        ledger = mu.model_usage_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"entries": "not-a-list", "wallets": {}}), encoding="utf-8"
        )
        state = mu._load_usage_state()
        assert state["entries"] == []

    def test_entries_with_non_dict_items_filtered(self, tmp_path):
        ledger = mu.model_usage_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"entries": [{"a": 1}, "bad", 42, {"b": 2}]}), encoding="utf-8"
        )
        state = mu._load_usage_state()
        assert len(state["entries"]) == 2
        assert state["entries"][0] == {"a": 1}

    def test_wallets_not_dict(self, tmp_path):
        ledger = mu.model_usage_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"entries": [], "wallets": "bad"}), encoding="utf-8"
        )
        state = mu._load_usage_state()
        assert state["wallets"] == {}

    def test_valid_state_with_summary(self, tmp_path):
        ledger = mu.model_usage_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [
                {"entry_type": "model_call", "cost_units": 10, "total_tokens": 100},
                {"entry_type": "tool_call", "cost_units": 5, "total_tokens": 0},
            ],
            "wallets": {"user1": {"balance_units": 100}},
        }
        ledger.write_text(json.dumps(data), encoding="utf-8")
        state = mu._load_usage_state()
        assert state["summary"]["entry_count"] == 2
        assert state["summary"]["cost_units_total"] == 15
        assert state["summary"]["model_entry_count"] == 1
        assert state["summary"]["tool_entry_count"] == 1


# ---------------------------------------------------------------------------
# _safe_metadata
# ---------------------------------------------------------------------------


class TestSafeMetadata:
    def test_not_dict(self):
        assert mu._safe_metadata("not-dict") == {}

    def test_not_dict_int(self):
        assert mu._safe_metadata(42) == {}

    def test_none(self):
        assert mu._safe_metadata(None) == {}

    def test_valid_dict(self):
        result = mu._safe_metadata({"key": "value", "num": 42})
        assert result == {"key": "value", "num": 42}

    def test_non_serializable_value(self):
        """Non-string keys cause TypeError in json.dumps → values stringified."""

        class Custom:
            def __str__(self):
                return "custom-str"

        # Non-string key triggers TypeError in json.dumps (default=str only
        # applies to values, not keys) → except branch stringifies everything
        result = mu._safe_metadata({Custom(): "val"})
        assert "custom-str" in result
        assert result["custom-str"] == "val"


# ---------------------------------------------------------------------------
# _usage_summary
# ---------------------------------------------------------------------------


class TestUsageSummary:
    def test_empty_entries(self):
        summary = mu._usage_summary([])
        assert summary["entry_count"] == 0
        assert summary["cost_units_total"] == 0

    def test_model_call_default(self):
        entries = [{"cost_units": 10, "total_tokens": 100}]
        summary = mu._usage_summary(entries)
        assert summary["model_entry_count"] == 1
        assert summary["model_cost_units_total"] == 10

    def test_explicit_model_call(self):
        entries = [{"entry_type": "model_call", "cost_units": 5}]
        summary = mu._usage_summary(entries)
        assert summary["model_entry_count"] == 1

    def test_tool_call(self):
        entries = [{"entry_type": "tool_call", "cost_units": 3}]
        summary = mu._usage_summary(entries)
        assert summary["tool_entry_count"] == 1
        assert summary["tool_cost_units_total"] == 3

    def test_refunded_entry(self):
        entries = [
            {"cost_units": 10, "refund": {"status": "refunded", "cost_units": 10}},
        ]
        summary = mu._usage_summary(entries)
        assert summary["refund_entry_count"] == 1
        assert summary["refund_cost_units_total"] == 10

    def test_refund_not_refunded_status(self):
        entries = [
            {"cost_units": 10, "refund": {"status": "pending", "cost_units": 10}},
        ]
        summary = mu._usage_summary(entries)
        assert summary["refund_entry_count"] == 0

    def test_refund_not_dict(self):
        entries = [
            {"cost_units": 10, "refund": "not-dict"},
        ]
        summary = mu._usage_summary(entries)
        assert summary["refund_entry_count"] == 0


# ---------------------------------------------------------------------------
# _wallet_required
# ---------------------------------------------------------------------------


class TestWalletRequired:
    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", val)
        assert mu._wallet_required() is True

    @pytest.mark.parametrize("val", ["", "no", "off", "0", "false"])
    def test_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", val)
        assert mu._wallet_required() is False

    def test_uppercase_true(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "TRUE")
        assert mu._wallet_required() is True


# ---------------------------------------------------------------------------
# model_usage_wallet_backend
# ---------------------------------------------------------------------------


class TestModelUsageWalletBackend:
    @pytest.mark.parametrize("val", ["market", "modstore", "xcagi_market", "xiuci"])
    def test_market_backend(self, monkeypatch, val):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", val)
        assert mu.model_usage_wallet_backend() == "market"

    @pytest.mark.parametrize("val", ["audit", "none", "off", "disabled"])
    def test_audit_backend(self, monkeypatch, val):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", val)
        assert mu.model_usage_wallet_backend() == "audit"

    def test_local_backend_default(self):
        assert mu.model_usage_wallet_backend() == "local"

    def test_local_backend_unknown(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "unknown")
        assert mu.model_usage_wallet_backend() == "local"

    def test_local_backend_empty(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "")
        assert mu.model_usage_wallet_backend() == "local"


# ---------------------------------------------------------------------------
# _wallet_user_id
# ---------------------------------------------------------------------------


class TestWalletUserId:
    def test_normal(self):
        assert mu._wallet_user_id("user123") == "user123"

    def test_empty(self):
        assert mu._wallet_user_id("") == "anonymous"

    def test_none(self):
        assert mu._wallet_user_id(None) == "anonymous"

    def test_whitespace_only(self):
        assert mu._wallet_user_id("   ") == "anonymous"


# ---------------------------------------------------------------------------
# _wallet_snapshot
# ---------------------------------------------------------------------------


class TestWalletSnapshot:
    def test_wallet_exists_dict(self):
        wallets = {"u1": {"balance_units": 100}}
        snap = mu._wallet_snapshot(wallets, "u1")
        assert snap == {"balance_units": 100}

    def test_wallet_not_exists(self):
        wallets = {"u1": {"balance_units": 100}}
        snap = mu._wallet_snapshot(wallets, "u2")
        assert snap is None

    def test_wallet_not_dict(self):
        wallets = {"u1": "not-dict"}
        snap = mu._wallet_snapshot(wallets, "u1")
        assert snap is None


# ---------------------------------------------------------------------------
# _apply_wallet_debit
# ---------------------------------------------------------------------------


class TestApplyWalletDebit:
    def test_cost_zero_unmetered(self):
        state = {"wallets": {}}
        status, info = mu._apply_wallet_debit(state, user_id="u1", cost_units=0)
        assert status == "unmetered"
        assert info["cost_units"] == 0

    def test_no_wallet_not_required_audit_only(self):
        state = {"wallets": {}}
        status, info = mu._apply_wallet_debit(state, user_id="u1", cost_units=10)
        assert status == "metered"
        assert info["status"] == "audit_only"
        assert info["reason"] == "wallet_not_configured"

    def test_no_wallet_required_insufficient(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
        state = {"wallets": {}}
        status, info = mu._apply_wallet_debit(state, user_id="u1", cost_units=10)
        assert status == "insufficient_balance"
        assert info["shortfall_units"] == 10

    def test_wallet_insufficient_balance(self):
        state = {"wallets": {"u1": {"balance_units": 5}}}
        status, info = mu._apply_wallet_debit(state, user_id="u1", cost_units=10)
        assert status == "insufficient_balance"
        assert info["balance_before_units"] == 5
        assert info["shortfall_units"] == 5

    def test_wallet_sufficient_debited(self):
        state = {"wallets": {"u1": {"balance_units": 100}}}
        status, info = mu._apply_wallet_debit(state, user_id="u1", cost_units=30)
        assert status == "debited"
        assert info["balance_before_units"] == 100
        assert info["balance_after_units"] == 70
        assert state["wallets"]["u1"]["balance_units"] == 70

    def test_wallet_exact_balance(self):
        state = {"wallets": {"u1": {"balance_units": 50}}}
        status, info = mu._apply_wallet_debit(state, user_id="u1", cost_units=50)
        assert status == "debited"
        assert info["balance_after_units"] == 0


# ---------------------------------------------------------------------------
# _money / _money_str
# ---------------------------------------------------------------------------


class TestMoney:
    def test_valid_string(self):
        assert mu._money("10.005") == mu.Decimal("10.01")

    def test_valid_int(self):
        assert mu._money(42) == mu.Decimal("42.00")

    def test_none(self):
        assert mu._money(None) == mu.Decimal("0.00")

    def test_empty_string(self):
        assert mu._money("") == mu.Decimal("0.00")

    def test_invalid_string(self):
        assert mu._money("abc") == mu.Decimal("0.00")

    def test_money_str(self):
        assert mu._money_str("10.005") == "10.01"


# ---------------------------------------------------------------------------
# _market_amount_for_cost_units
# ---------------------------------------------------------------------------


class TestMarketAmountForCostUnits:
    def test_zero_cost(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.01")
        result = mu._market_amount_for_cost_units(0)
        assert result == mu.Decimal("0.00")

    def test_above_minimum(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.10")
        monkeypatch.setenv("MODEL_USAGE_MARKET_MIN_CHARGE", "0.01")
        result = mu._market_amount_for_cost_units(100)
        # 100 * 0.10 = 10.00
        assert result == mu.Decimal("10.00")

    def test_below_minimum_uses_minimum(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.001")
        monkeypatch.setenv("MODEL_USAGE_MARKET_MIN_CHARGE", "0.50")
        result = mu._market_amount_for_cost_units(1)
        # 1 * 0.001 = 0.001 → below 0.50 minimum → 0.50
        assert result == mu.Decimal("0.50")

    def test_default_unit_and_minimum(self):
        result = mu._market_amount_for_cost_units(10)
        # Default: 0.01 per unit, 0.01 minimum → 10 * 0.01 = 0.10
        assert result == mu.Decimal("0.10")


# ---------------------------------------------------------------------------
# _market_base_url
# ---------------------------------------------------------------------------


class TestMarketBaseUrl:
    def test_primary_env(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "http://market.example.com/")
        assert mu._market_base_url() == "http://market.example.com"

    def test_fallback_xcagi(self, monkeypatch):
        monkeypatch.delenv("MODEL_USAGE_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://xcagi.example.com/")
        assert mu._market_base_url() == "http://xcagi.example.com"

    def test_fallback_modstore(self, monkeypatch):
        monkeypatch.delenv("MODEL_USAGE_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://modstore.example.com/")
        assert mu._market_base_url() == "http://modstore.example.com"

    def test_default(self):
        assert mu._market_base_url() == "http://127.0.0.1:8765"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "http://example.com///")
        assert mu._market_base_url() == "http://example.com"


# ---------------------------------------------------------------------------
# _strip_bearer
# ---------------------------------------------------------------------------


class TestStripBearer:
    def test_bearer_prefix(self):
        assert mu._strip_bearer("Bearer mytoken") == "mytoken"

    def test_authorization_prefix(self):
        assert mu._strip_bearer("Authorization: mytoken") == "mytoken"

    def test_plain_token(self):
        assert mu._strip_bearer("plain-token") == "plain-token"

    def test_empty(self):
        assert mu._strip_bearer("") == ""

    def test_none(self):
        assert mu._strip_bearer(None) == ""

    def test_bearer_lowercase(self):
        assert mu._strip_bearer("bearer tok") == "tok"

    def test_authorization_lowercase(self):
        assert mu._strip_bearer("authorization: tok") == "tok"

    def test_strips_whitespace(self):
        assert mu._strip_bearer("  Bearer   spaced  ") == "spaced"


# ---------------------------------------------------------------------------
# _market_auth_token
# ---------------------------------------------------------------------------


class TestMarketAuthToken:
    def test_env_token_primary(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "Bearer envtok")
        assert mu._market_auth_token() == "envtok"

    def test_env_token_xcagi_fallback(self, monkeypatch):
        monkeypatch.delenv("MODEL_USAGE_MARKET_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("XCAGI_MARKET_AUTH_TOKEN", "xcagi-tok")
        assert mu._market_auth_token() == "xcagi-tok"

    def test_env_token_modstore_fallback(self, monkeypatch):
        monkeypatch.delenv("MODEL_USAGE_MARKET_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "modstore-tok")
        assert mu._market_auth_token() == "modstore-tok"

    def test_no_env_token_import_fails(self):
        """When no env token and import fails, returns empty string."""
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            assert mu._market_auth_token() == ""

    def test_no_env_token_with_user_id(self):
        """When user_id provided and import fails, returns empty string."""
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            assert mu._market_auth_token(user_id="123") == ""


# ---------------------------------------------------------------------------
# _market_timeout
# ---------------------------------------------------------------------------


class TestMarketTimeout:
    def test_valid_float(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_TIMEOUT", "30")
        assert mu._market_timeout() == 30.0

    def test_invalid_float(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_TIMEOUT", "abc")
        assert mu._market_timeout() == 10.0

    def test_default(self):
        assert mu._market_timeout() == 10.0

    def test_below_minimum_clamped(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_MARKET_TIMEOUT", "0.5")
        assert mu._market_timeout() == 1.0


# ---------------------------------------------------------------------------
# _market_post_json
# ---------------------------------------------------------------------------


class TestMarketPostJson:
    def test_empty_base_url(self, monkeypatch):
        # _market_base_url always falls back to default; patch to return ""
        # to trigger the "if not base" branch
        with patch("app.infrastructure.billing.model_usage._market_base_url", return_value=""):
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"
        assert err["message"] == "market_base_url_missing"

    def test_empty_token(self):
        data, err = mu._market_post_json("/path", token="", payload={})
        assert data is None
        assert err["status"] == "market_auth_missing"

    def test_http_error(self):
        with patch("httpx.Client") as MockClient:
            import httpx
            client = MockClient.return_value.__enter__.return_value
            client.post.side_effect = httpx.HTTPError("conn fail")
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"
        assert "conn fail" in err["message"]

    def test_response_402_insufficient_balance(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 402
            resp.json.return_value = {"message": "余额不足"}
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "insufficient_balance"

    def test_response_400_error(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 400
            resp.json.return_value = {"message": "bad request"}
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"

    def test_response_ok_false(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"ok": False, "message": "failed"}
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"

    def test_response_success_false(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"success": False, "message": "denied"}
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"

    def test_response_success(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"ok": True, "success": True, "data": "result"}
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data == {"ok": True, "success": True, "data": "result"}
        assert err is None

    def test_response_json_decode_error(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 400
            resp.json.side_effect = ValueError("bad json")
            resp.text = "error body text"
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"

    def test_response_402_with_detail(self):
        with patch("httpx.Client") as MockClient:
            resp = MagicMock()
            resp.status_code = 402
            resp.json.return_value = {"detail": "insufficient funds"}
            client = MockClient.return_value.__enter__.return_value
            client.post.return_value = resp
            data, err = mu._market_post_json("/path", token="tok", payload={})
        assert data is None
        assert err["status"] == "insufficient_balance"
        assert "insufficient funds" in err["message"]


# ---------------------------------------------------------------------------
# _apply_market_wallet_debit
# ---------------------------------------------------------------------------


class TestApplyMarketWalletDebit:
    def test_cost_zero_unmetered(self):
        status, info = mu._apply_market_wallet_debit(
            user_id="u1", provider="p", model="m", cost_units=0, usage_key="k1"
        )
        assert status == "unmetered"

    def test_preauth_error(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.return_value = (None, {"status": "market_debit_failed", "message": "err"})
            status, info = mu._apply_market_wallet_debit(
                user_id="u1", provider="p", model="m", cost_units=10, usage_key="k1"
            )
        assert status == "market_debit_failed"

    def test_preauth_no_hold_no(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.return_value = ({"hold": {}}, None)
            status, info = mu._apply_market_wallet_debit(
                user_id="u1", provider="p", model="m", cost_units=10, usage_key="k1"
            )
        assert status == "market_debit_failed"
        assert "market_preauthorize_missing_hold_no" in info["message"]

    def test_settle_error(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.side_effect = [
                ({"hold": {"hold_no": "H123"}}, None),
                (None, {"status": "market_debit_failed", "message": "settle fail"}),
            ]
            status, info = mu._apply_market_wallet_debit(
                user_id="u1", provider="p", model="m", cost_units=10, usage_key="k1"
            )
        assert status == "market_debit_failed"
        assert info["hold_no"] == "H123"

    def test_settle_success(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.side_effect = [
                ({"hold": {"hold_no": "H123"}}, None),
                ({"balance": "90.00"}, None),
            ]
            status, info = mu._apply_market_wallet_debit(
                user_id="u1", provider="p", model="m", cost_units=10, usage_key="k1"
            )
        assert status == "debited"
        assert info["hold_no"] == "H123"
        assert info["balance_after_yuan"] == "90.00"

    def test_settle_success_balance_none(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.side_effect = [
                ({"hold": {"hold_no": "H123"}}, None),
                ({}, None),
            ]
            status, info = mu._apply_market_wallet_debit(
                user_id="u1", provider="p", model="m", cost_units=10, usage_key="k1"
            )
        assert status == "debited"
        assert info["balance_after_yuan"] is None


# ---------------------------------------------------------------------------
# _apply_market_wallet_refund
# ---------------------------------------------------------------------------


class TestApplyMarketWalletRefund:
    def test_no_hold_no(self):
        status, info = mu._apply_market_wallet_refund(
            user_id="u1", hold_no="", amount_yuan="10.00", refund_key="rk", reason="r"
        )
        assert status == "refund_pending"

    def test_amount_zero_not_required(self):
        status, info = mu._apply_market_wallet_refund(
            user_id="u1", hold_no="H1", amount_yuan="0.00", refund_key="rk", reason="r"
        )
        assert status == "not_required"

    def test_refund_error(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.return_value = (None, {"status": "market_debit_failed", "message": "err"})
            status, info = mu._apply_market_wallet_refund(
                user_id="u1", hold_no="H1", amount_yuan="10.00", refund_key="rk", reason="r"
            )
        assert status == "refund_pending"

    def test_refund_success(self):
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.return_value = ({"balance": "100.00", "refund": {"id": "R1"}}, None)
            status, info = mu._apply_market_wallet_refund(
                user_id="u1", hold_no="H1", amount_yuan="10.00", refund_key="rk", reason="r"
            )
        assert status == "refunded"
        assert info["balance_after_yuan"] == "100.00"
        assert info["refund"] == {"id": "R1"}


# ---------------------------------------------------------------------------
# set_model_wallet_balance / get_model_wallet
# ---------------------------------------------------------------------------


class TestWalletOperations:
    def test_set_balance(self):
        result = mu.set_model_wallet_balance("u1", 100, reason="test")
        assert result["balance_units"] == 100
        assert result["reason"] == "test"

    def test_set_negative_balance_clamped(self):
        result = mu.set_model_wallet_balance("u1", -50)
        assert result["balance_units"] == 0

    def test_get_wallet_exists(self):
        mu.set_model_wallet_balance("u1", 100)
        wallet = mu.get_model_wallet("u1")
        assert wallet["configured"] is True
        assert wallet["balance_units"] == 100

    def test_get_wallet_not_exists(self):
        wallet = mu.get_model_wallet("nonexistent")
        assert wallet["configured"] is False
        assert wallet["balance_units"] == 0


# ---------------------------------------------------------------------------
# record_model_usage
# ---------------------------------------------------------------------------


class TestRecordModelUsage:
    def test_basic_with_total_tokens(self):
        result = mu.record_model_usage(
            run_id="r1",
            user_id="u1",
            provider="openai",
            model="gpt-4",
            total_tokens=500,
            cost_units=5,
        )
        assert result["entry_type"] == "model_call"
        assert result["total_tokens"] == 500
        assert result["cost_units"] == 5
        assert result["billing_status"] == "metered"

    def test_total_zero_uses_prompt_completion(self):
        result = mu.record_model_usage(
            prompt_tokens=200,
            completion_tokens=300,
        )
        assert result["total_tokens"] == 500

    def test_cost_zero_estimated(self):
        result = mu.record_model_usage(prompt_tokens=500, completion_tokens=600)
        # 1100 tokens → ceil(1100/1000) = 2
        assert result["cost_units"] == 2

    def test_with_metadata(self):
        result = mu.record_model_usage(
            user_id="u1",
            metadata={"session": "abc", "turn": 1},
        )
        assert result["metadata"] == {"session": "abc", "turn": 1}

    def test_with_invalid_metadata(self):
        result = mu.record_model_usage(
            user_id="u1",
            metadata="not-dict",
        )
        assert result["metadata"] == {}

    def test_backend_audit(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        result = mu.record_model_usage(user_id="u1", cost_units=10)
        assert result["wallet_debit"]["status"] == "audit_only"
        assert result["billing_status"] == "metered"

    def test_backend_local_with_wallet(self):
        mu.set_model_wallet_balance("u1", 100)
        result = mu.record_model_usage(user_id="u1", cost_units=10)
        assert result["billing_status"] == "debited"
        assert result["billing_source"] == "local_model_wallet"

    def test_backend_local_insufficient(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
        result = mu.record_model_usage(user_id="u1", cost_units=100)
        assert result["billing_status"] == "insufficient_balance"

    def test_dedup_same_usage_key(self):
        r1 = mu.record_model_usage(usage_key="dup-key", cost_units=5)
        r2 = mu.record_model_usage(usage_key="dup-key", cost_units=10)
        assert r1["usage_id"] == r2["usage_id"]
        assert r2["cost_units"] == 5  # Returns existing


# ---------------------------------------------------------------------------
# record_tool_usage
# ---------------------------------------------------------------------------


class TestRecordToolUsage:
    def test_basic(self):
        result = mu.record_tool_usage(
            run_id="r1",
            user_id="u1",
            tool_id="products",
            action="create",
            cost_units=3,
        )
        assert result["entry_type"] == "tool_call"
        assert result["model"] == "products.create"
        assert result["cost_units"] == 3
        assert result["billing_status"] == "metered"

    def test_zero_cost(self):
        result = mu.record_tool_usage(tool_id="query", action="list")
        assert result["cost_units"] == 0
        assert result["billing_status"] == "unmetered"

    def test_with_metadata(self):
        result = mu.record_tool_usage(
            tool_id="t",
            action="a",
            metadata={"k": "v"},
        )
        assert result["metadata"] == {"k": "v"}

    def test_dedup_same_usage_key(self):
        r1 = mu.record_tool_usage(tool_id="t", action="a", usage_key="tool-dup", cost_units=5)
        r2 = mu.record_tool_usage(tool_id="t", action="a", usage_key="tool-dup", cost_units=10)
        assert r1["usage_id"] == r2["usage_id"]


# ---------------------------------------------------------------------------
# refund_tool_usage
# ---------------------------------------------------------------------------


class TestRefundToolUsage:
    def test_usage_not_found(self):
        result = mu.refund_tool_usage(usage_key="nonexistent")
        assert result["success"] is False
        assert result["refund_status"] == "usage_not_found"

    def test_existing_refund_returns_target(self):
        # Record a usage first
        mu.record_model_usage(usage_key="refund-test", cost_units=10, user_id="u1")
        # First refund
        r1 = mu.refund_tool_usage(usage_key="refund-test", reason="test1")
        assert r1["refund"]["reason"] == "test1"
        # Second refund returns existing
        r2 = mu.refund_tool_usage(usage_key="refund-test", reason="test2")
        assert r2["refund"]["reason"] == "test1"

    def test_cost_zero_not_charged(self):
        mu.record_model_usage(usage_key="zero-cost", cost_units=0, user_id="u1")
        result = mu.refund_tool_usage(usage_key="zero-cost")
        assert result["refund"]["status"] == "not_charged"

    def test_insufficient_balance_not_charged(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
        mu.record_model_usage(usage_key="insuf", cost_units=100, user_id="u1")
        result = mu.refund_tool_usage(usage_key="insuf")
        assert result["refund"]["status"] == "not_charged"

    def test_local_wallet_debited_refunded(self):
        mu.set_model_wallet_balance("u1", 100)
        mu.record_model_usage(usage_key="local-debit", cost_units=30, user_id="u1")
        result = mu.refund_tool_usage(usage_key="local-debit")
        assert result["refund"]["status"] == "refunded"
        assert result["refund"]["balance_after_units"] == 100  # Restored

    def test_audit_only_status(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        mu.record_model_usage(usage_key="audit-test", cost_units=10, user_id="u1")
        result = mu.refund_tool_usage(usage_key="audit-test")
        assert result["refund"]["status"] == "audit_only"

    def test_market_wallet_refund(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.side_effect = [
                ({"hold": {"hold_no": "H1"}}, None),
                ({"balance": "100.00"}, None),
                ({"balance": "110.00", "refund": {"id": "R1"}}, None),
            ]
            mu.record_model_usage(usage_key="market-test", cost_units=10, user_id="u1")
            result = mu.refund_tool_usage(usage_key="market-test")
        assert result["refund"]["status"] == "refunded"

    def test_refund_by_usage_id(self):
        mu.record_model_usage(usage_key="by-id-test", cost_units=5, user_id="u1")
        # Get the entry to find usage_id
        entries = mu.list_model_usage_entries()
        entry = next(e for e in entries if e["usage_key"] == "by-id-test")
        result = mu.refund_tool_usage(usage_id=entry["usage_id"])
        assert "refund" in result


# ---------------------------------------------------------------------------
# list_model_usage_entries
# ---------------------------------------------------------------------------


class TestListModelUsageEntries:
    def test_no_entries(self):
        assert mu.list_model_usage_entries() == []

    def test_no_filter(self):
        mu.record_model_usage(usage_key="e1", user_id="u1", run_id="r1")
        mu.record_model_usage(usage_key="e2", user_id="u2", run_id="r2")
        entries = mu.list_model_usage_entries()
        assert len(entries) == 2

    def test_filter_by_run_id(self):
        mu.record_model_usage(usage_key="e1", user_id="u1", run_id="r1")
        mu.record_model_usage(usage_key="e2", user_id="u2", run_id="r2")
        entries = mu.list_model_usage_entries(run_id="r1")
        assert len(entries) == 1
        assert entries[0]["run_id"] == "r1"

    def test_filter_by_user_id(self):
        mu.record_model_usage(usage_key="e1", user_id="u1", run_id="r1")
        mu.record_model_usage(usage_key="e2", user_id="u2", run_id="r2")
        entries = mu.list_model_usage_entries(user_id="u2")
        assert len(entries) == 1
        assert entries[0]["user_id"] == "u2"

    def test_limit(self):
        for i in range(5):
            mu.record_model_usage(usage_key=f"lim-{i}", user_id="u1")
        entries = mu.list_model_usage_entries(limit=3)
        assert len(entries) == 3

    def test_sorted_by_created_at_desc(self):
        mu.record_model_usage(usage_key="first", user_id="u1")
        mu.record_model_usage(usage_key="second", user_id="u1")
        entries = mu.list_model_usage_entries()
        # Most recent first
        assert entries[0]["usage_key"] == "second"
        assert entries[1]["usage_key"] == "first"


# ---------------------------------------------------------------------------
# _record_usage_entry — backend branches
# ---------------------------------------------------------------------------


class TestRecordUsageEntryBackends:
    def test_audit_backend_with_cost(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        entry = {
            "usage_id": "test-audit",
            "usage_key": "test-audit",
            "entry_type": "model_call",
            "user_id": "u1",
            "provider": "p",
            "model": "m",
            "cost_units": 10,
            "billing_status": "",
            "billing_source": "",
        }
        result = mu._record_usage_entry(entry)
        assert result["wallet_debit"]["status"] == "audit_only"
        assert result["wallet_debit"]["cost_units"] == 10
        # "metered" is not in {"debited","insufficient_balance"} nor
        # {"market_debit_failed","market_auth_missing"} → billing_status stays ""
        assert result["billing_status"] == ""

    def test_audit_backend_zero_cost(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        entry = {
            "usage_id": "test-audit-0",
            "usage_key": "test-audit-0",
            "entry_type": "model_call",
            "user_id": "u1",
            "provider": "p",
            "model": "m",
            "cost_units": 0,
            "billing_status": "",
            "billing_source": "",
        }
        result = mu._record_usage_entry(entry)
        assert result["wallet_debit"]["status"] == "audit_only"
        assert result["wallet_debit"]["cost_units"] == 0
        # "unmetered" not in the billing_status update sets → stays ""
        assert result["billing_status"] == ""

    def test_market_backend_debited(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
        with patch("app.infrastructure.billing.model_usage._market_post_json") as mock_post:
            mock_post.side_effect = [
                ({"hold": {"hold_no": "H1"}}, None),
                ({"balance": "90.00"}, None),
            ]
            entry = {
                "usage_id": "test-market",
                "usage_key": "test-market",
                "entry_type": "model_call",
                "user_id": "u1",
                "provider": "p",
                "model": "m",
                "cost_units": 10,
                "billing_status": "",
                "billing_source": "",
            }
            result = mu._record_usage_entry(entry)
        assert result["billing_status"] == "debited"
        assert result["billing_source"] == "market_wallet"

    def test_market_backend_auth_missing(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
        monkeypatch.delenv("MODEL_USAGE_MARKET_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
        with patch("builtins.__import__", side_effect=ImportError("no")):
            entry = {
                "usage_id": "test-auth-miss",
                "usage_key": "test-auth-miss",
                "entry_type": "model_call",
                "user_id": "u1",
                "provider": "p",
                "model": "m",
                "cost_units": 10,
                "billing_status": "",
                "billing_source": "",
            }
            result = mu._record_usage_entry(entry)
        assert result["billing_status"] == "market_debit_failed"

    def test_local_backend_debited(self):
        mu.set_model_wallet_balance("u1", 100)
        entry = {
            "usage_id": "test-local",
            "usage_key": "test-local",
            "entry_type": "model_call",
            "user_id": "u1",
            "provider": "p",
            "model": "m",
            "cost_units": 30,
            "billing_status": "",
            "billing_source": "",
        }
        result = mu._record_usage_entry(entry)
        assert result["billing_status"] == "debited"
        assert result["billing_source"] == "local_model_wallet"

    def test_local_backend_insufficient(self, monkeypatch):
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
        entry = {
            "usage_id": "test-local-insuf",
            "usage_key": "test-local-insuf",
            "entry_type": "model_call",
            "user_id": "u1",
            "provider": "p",
            "model": "m",
            "cost_units": 100,
            "billing_status": "",
            "billing_source": "",
        }
        result = mu._record_usage_entry(entry)
        assert result["billing_status"] == "insufficient_balance"

    def test_duplicate_usage_key_returns_existing(self):
        entry1 = {
            "usage_id": "dup-1",
            "usage_key": "same-key",
            "entry_type": "model_call",
            "user_id": "u1",
            "provider": "p",
            "model": "m",
            "cost_units": 5,
            "billing_status": "",
            "billing_source": "",
        }
        r1 = mu._record_usage_entry(entry1)
        entry2 = dict(entry1, usage_id="dup-2", cost_units=10)
        r2 = mu._record_usage_entry(entry2)
        assert r1["usage_id"] == r2["usage_id"]
        assert r2["cost_units"] == 5
