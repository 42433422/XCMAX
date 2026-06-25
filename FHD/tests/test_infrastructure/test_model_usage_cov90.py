"""Behavior tests for app.infrastructure.billing.model_usage — coverage ramp to 90%.

Targets previously-uncovered units:
* ``_coerce_int`` non-numeric fallback.
* ``_load_usage_state`` corrupt/non-dict/non-list/bad-entry sanitisation.
* ``_safe_metadata`` non-dict + non-serialisable fallback.
* ``_money`` invalid input fallback; ``_market_amount_for_cost_units`` minimum bump.
* ``_strip_bearer`` Authorization:/Bearer prefix stripping.
* ``_market_auth_token`` env-token path + session-token fallback + import failure.
* ``_market_timeout`` invalid value fallback.
* ``_market_post_json`` missing base / missing token / HTTP error / 402 / >=400 / non-JSON body.
* ``_apply_market_wallet_debit`` zero cost + missing hold_no.
* ``_apply_market_wallet_refund`` missing hold_no + zero amount + error->pending.
* ``refund_tool_usage`` not-found / already-refunded / not_charged / market_wallet path.
* ``_record_usage_entry`` market_debit_failed billing source.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

import app.infrastructure.billing.model_usage as mu


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the ledger at an isolated temp file for each test."""
    path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(path))
    return path


# --------------------------------------------------------------------------- #
# _coerce_int                                                                  #
# --------------------------------------------------------------------------- #
class TestCoerceInt:
    def test_non_numeric_string_returns_zero(self) -> None:
        assert mu._coerce_int("not-a-number") == 0

    def test_object_typeerror_returns_zero(self) -> None:
        assert mu._coerce_int(object()) == 0

    def test_valid_numeric_string(self) -> None:
        assert mu._coerce_int("42") == 42

    def test_none_returns_zero(self) -> None:
        assert mu._coerce_int(None) == 0


# --------------------------------------------------------------------------- #
# _load_usage_state                                                            #
# --------------------------------------------------------------------------- #
class TestLoadUsageState:
    def test_missing_file_returns_empty(self, ledger) -> None:
        state = mu._load_usage_state()
        assert state == mu._empty_usage_state()

    def test_corrupt_json_returns_empty(self, ledger) -> None:
        ledger.write_text("{not valid json", encoding="utf-8")
        state = mu._load_usage_state()
        assert state["entries"] == []
        assert state["wallets"] == {}

    def test_non_dict_top_level_returns_empty(self, ledger) -> None:
        ledger.write_text("[1, 2, 3]", encoding="utf-8")
        state = mu._load_usage_state()
        assert state == mu._empty_usage_state()

    def test_entries_not_a_list_is_normalised(self, ledger) -> None:
        ledger.write_text('{"entries": "oops", "wallets": {}}', encoding="utf-8")
        state = mu._load_usage_state()
        assert state["entries"] == []

    def test_non_dict_entries_filtered_and_wallets_default(self, ledger) -> None:
        ledger.write_text(
            '{"entries": [{"usage_id": "a", "cost_units": 2}, "junk", 5], "wallets": 7}',
            encoding="utf-8",
        )
        state = mu._load_usage_state()
        assert len(state["entries"]) == 1
        assert state["entries"][0]["usage_id"] == "a"
        # non-dict wallets coerced to {}
        assert state["wallets"] == {}
        # summary recomputed from the surviving entry
        assert state["summary"]["cost_units_total"] == 2


# --------------------------------------------------------------------------- #
# _safe_metadata                                                               #
# --------------------------------------------------------------------------- #
class TestSafeMetadata:
    def test_non_dict_returns_empty(self) -> None:
        assert mu._safe_metadata(["a", "b"]) == {}
        assert mu._safe_metadata(None) == {}

    def test_serialisable_dict_copied(self) -> None:
        out = mu._safe_metadata({"x": 1, "y": "z"})
        assert out == {"x": 1, "y": "z"}

    def test_object_values_pass_via_default_str(self) -> None:
        # json.dumps uses default=str so an arbitrary object value serialises fine;
        # the dict is copied through unchanged (the value object is preserved).
        marker = object()
        out = mu._safe_metadata({"k": marker})
        assert out["k"] is marker

    def test_non_string_keys_trigger_typeerror_fallback(self) -> None:
        # Non-string keys make json.dumps raise TypeError even with default=str,
        # forcing the except branch that stringifies every key and value.
        out = mu._safe_metadata({(1, 2): object()})
        assert list(out.keys()) == ["(1, 2)"]
        assert all(isinstance(v, str) for v in out.values())


# --------------------------------------------------------------------------- #
# _money / _market_amount_for_cost_units                                       #
# --------------------------------------------------------------------------- #
class TestMoney:
    def test_invalid_input_returns_zero(self) -> None:
        assert mu._money("not-a-decimal") == Decimal("0.00")
        assert mu._money(object()) == Decimal("0.00")

    def test_rounds_half_up(self) -> None:
        assert mu._money("1.005") == Decimal("1.01")

    def test_market_amount_applies_minimum(self, monkeypatch) -> None:
        # per-unit price tiny -> raw amount below the minimum charge
        monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.0001")
        monkeypatch.setenv("MODEL_USAGE_MARKET_MIN_CHARGE", "0.05")
        amount = mu._market_amount_for_cost_units(1)
        assert amount == Decimal("0.05")

    def test_market_amount_zero_cost_no_minimum(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_MIN_CHARGE", "0.05")
        assert mu._market_amount_for_cost_units(0) == Decimal("0.00")


# --------------------------------------------------------------------------- #
# _strip_bearer                                                                #
# --------------------------------------------------------------------------- #
class TestStripBearer:
    def test_strips_authorization_prefix(self) -> None:
        assert mu._strip_bearer("Authorization: tok123") == "tok123"

    def test_strips_bearer_prefix(self) -> None:
        assert mu._strip_bearer("Bearer tok456") == "tok456"

    def test_strips_authorization_then_bearer(self) -> None:
        assert mu._strip_bearer("Authorization: Bearer tok789") == "tok789"

    def test_plain_token_unchanged(self) -> None:
        assert mu._strip_bearer("rawtoken") == "rawtoken"


# --------------------------------------------------------------------------- #
# _market_auth_token                                                           #
# --------------------------------------------------------------------------- #
class TestMarketAuthToken:
    def test_env_token_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "Bearer envtok")
        assert mu._market_auth_token() == "envtok"

    def test_session_fallback_with_user_id(self, monkeypatch) -> None:
        for var in (
            "MODEL_USAGE_MARKET_AUTH_TOKEN",
            "XCAGI_MARKET_AUTH_TOKEN",
            "MODSTORE_AUTH_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        with patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            return_value="Bearer sesstok",
        ) as latest:
            out = mu._market_auth_token(user_id="77")
        latest.assert_called_once_with(user_id=77)
        assert out == "sesstok"

    def test_session_fallback_bad_user_id_passes_none(self, monkeypatch) -> None:
        for var in (
            "MODEL_USAGE_MARKET_AUTH_TOKEN",
            "XCAGI_MARKET_AUTH_TOKEN",
            "MODSTORE_AUTH_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        with patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            return_value="",
        ) as latest:
            out = mu._market_auth_token(user_id="not-int")
        latest.assert_called_once_with(user_id=None)
        assert out == ""

    def test_import_failure_returns_empty(self, monkeypatch) -> None:
        for var in (
            "MODEL_USAGE_MARKET_AUTH_TOKEN",
            "XCAGI_MARKET_AUTH_TOKEN",
            "MODSTORE_AUTH_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        with patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            side_effect=RuntimeError("boom"),
        ):
            assert mu._market_auth_token(user_id="5") == ""


# --------------------------------------------------------------------------- #
# _market_timeout                                                              #
# --------------------------------------------------------------------------- #
class TestMarketTimeout:
    def test_invalid_value_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_TIMEOUT", "abc")
        assert mu._market_timeout() == 10.0

    def test_valid_value_clamped_to_minimum(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_TIMEOUT", "0.1")
        assert mu._market_timeout() == 1.0

    def test_valid_value_used(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_TIMEOUT", "25")
        assert mu._market_timeout() == 25.0


# --------------------------------------------------------------------------- #
# _market_post_json                                                            #
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code: int, body, *, raise_json: bool = False, text: str = ""):
        self.status_code = status_code
        self._body = body
        self._raise_json = raise_json
        self.text = text

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._body


class _FakeClient:
    def __init__(self, response=None, *, error: Exception | None = None):
        self._response = response
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, *, headers, json):
        if self._error is not None:
            raise self._error
        return self._response


class TestMarketPostJson:
    def test_missing_base_url(self, monkeypatch) -> None:
        with patch.object(mu, "_market_base_url", return_value=""):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert data is None
        assert err["message"] == "market_base_url_missing"

    def test_missing_token(self, monkeypatch) -> None:
        with patch.object(mu, "_market_base_url", return_value="http://m"):
            data, err = mu._market_post_json("/p", token="", payload={})
        assert data is None
        assert err["status"] == "market_auth_missing"

    def test_http_error_returns_failed(self) -> None:
        client = _FakeClient(error=httpx.ConnectError("refused"))
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"
        assert err["path"] == "/p"

    def test_402_maps_to_insufficient_balance(self) -> None:
        resp = _FakeResponse(402, {"message": "余额不足啦"})
        client = _FakeClient(response=resp)
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert data is None
        assert err["status"] == "insufficient_balance"
        assert err["message"] == "余额不足啦"

    def test_400_with_balance_message_is_insufficient(self) -> None:
        resp = _FakeResponse(400, {"ok": False, "message": "余额不足"})
        client = _FakeClient(response=resp)
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert data is None
        assert err["status"] == "insufficient_balance"

    def test_500_is_market_debit_failed(self) -> None:
        resp = _FakeResponse(500, {"detail": "boom"})
        client = _FakeClient(response=resp)
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"
        assert err["message"] == "boom"

    def test_non_json_body_uses_text(self) -> None:
        resp = _FakeResponse(200, None, raise_json=True, text="plain text body")
        client = _FakeClient(response=resp)
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        # 200 with parseable-as-text body, ok not False -> returns the synthesised dict
        assert err is None
        assert data == {"message": "plain text body"}

    def test_ok_false_flag_fails(self) -> None:
        resp = _FakeResponse(200, {"ok": False, "error": "denied"})
        client = _FakeClient(response=resp)
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert data is None
        assert err["status"] == "market_debit_failed"
        assert err["message"] == "denied"

    def test_success_returns_data(self) -> None:
        resp = _FakeResponse(200, {"ok": True, "hold": {"hold_no": "H1"}})
        client = _FakeClient(response=resp)
        with (
            patch.object(mu, "_market_base_url", return_value="http://m"),
            patch.object(mu.httpx, "Client", return_value=client),
        ):
            data, err = mu._market_post_json("/p", token="t", payload={})
        assert err is None
        assert data["hold"]["hold_no"] == "H1"


# --------------------------------------------------------------------------- #
# _apply_market_wallet_debit                                                   #
# --------------------------------------------------------------------------- #
class TestApplyMarketWalletDebit:
    def test_zero_cost_is_unmetered(self) -> None:
        status, info = mu._apply_market_wallet_debit(
            user_id="u1",
            provider="openai",
            model="gpt",
            cost_units=0,
            usage_key="k",
        )
        assert status == "unmetered"
        assert info["status"] == "not_required"

    def test_preauth_error_propagates_status(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "tok")
        with patch.object(
            mu,
            "_market_post_json",
            return_value=(None, {"status": "insufficient_balance", "message": "no money"}),
        ):
            status, info = mu._apply_market_wallet_debit(
                user_id="u1",
                provider="p",
                model="m",
                cost_units=5,
                usage_key="key1",
            )
        assert status == "insufficient_balance"
        assert info["message"] == "no money"
        assert info["backend"] == "market"

    def test_missing_hold_no_fails(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "tok")
        # preauth succeeds but no hold_no in response
        with patch.object(mu, "_market_post_json", return_value=({"hold": {}}, None)):
            status, info = mu._apply_market_wallet_debit(
                user_id="u1",
                provider="p",
                model="m",
                cost_units=5,
                usage_key="key2",
            )
        assert status == "market_debit_failed"
        assert info["message"] == "market_preauthorize_missing_hold_no"

    def test_settle_error_returns_preauthorized(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "tok")
        responses = [
            ({"hold": {"hold_no": "H9"}}, None),  # preauth ok
            (None, {"status": "market_debit_failed", "message": "settle fail"}),  # settle err
        ]
        with patch.object(mu, "_market_post_json", side_effect=responses):
            status, info = mu._apply_market_wallet_debit(
                user_id="u1",
                provider="p",
                model="m",
                cost_units=5,
                usage_key="key3",
            )
        assert status == "market_debit_failed"
        assert info["hold_no"] == "H9"
        assert info["preauthorized"] is True

    def test_full_success_debited(self, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "tok")
        responses = [
            ({"hold": {"hold_no": "H10"}}, None),  # preauth
            ({"balance": "12.34"}, None),  # settle
        ]
        with patch.object(mu, "_market_post_json", side_effect=responses):
            status, info = mu._apply_market_wallet_debit(
                user_id="u1",
                provider="p",
                model="m",
                cost_units=5,
                usage_key="key4",
            )
        assert status == "debited"
        assert info["hold_no"] == "H10"
        assert info["balance_after_yuan"] == "12.34"


# --------------------------------------------------------------------------- #
# _apply_market_wallet_refund                                                  #
# --------------------------------------------------------------------------- #
class TestApplyMarketWalletRefund:
    def test_missing_hold_no_is_pending(self) -> None:
        status, info = mu._apply_market_wallet_refund(
            user_id="u1",
            hold_no="",
            amount_yuan="1.00",
            refund_key="rk",
            reason="r",
        )
        assert status == "refund_pending"
        assert info["message"] == "market_wallet_hold_no_missing"

    def test_zero_amount_not_required(self) -> None:
        status, info = mu._apply_market_wallet_refund(
            user_id="u1",
            hold_no="H1",
            amount_yuan="0",
            refund_key="rk",
            reason="r",
        )
        assert status == "not_required"
        assert info["amount_yuan"] == "0.00"

    def test_error_returns_pending(self) -> None:
        with patch.object(mu, "_market_post_json", return_value=(None, {"message": "down"})):
            status, info = mu._apply_market_wallet_refund(
                user_id="u1",
                hold_no="H1",
                amount_yuan="2.50",
                refund_key="rk",
                reason="r",
            )
        assert status == "refund_pending"
        assert info["status"] == "refund_pending"

    def test_success_refunded(self) -> None:
        with patch.object(
            mu,
            "_market_post_json",
            return_value=({"balance": "5.00", "refund": {"refund_no": "R1"}}, None),
        ):
            status, info = mu._apply_market_wallet_refund(
                user_id="u1",
                hold_no="H1",
                amount_yuan="2.50",
                refund_key="rk",
                reason="r",
            )
        assert status == "refunded"
        assert info["balance_after_yuan"] == "5.00"
        assert info["refund"] == {"refund_no": "R1"}


# --------------------------------------------------------------------------- #
# refund_tool_usage                                                            #
# --------------------------------------------------------------------------- #
class TestRefundToolUsage:
    def test_usage_not_found(self, ledger) -> None:
        out = mu.refund_tool_usage(usage_key="missing")
        assert out["success"] is False
        assert out["refund_status"] == "usage_not_found"

    def test_find_by_usage_id(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        rec = mu.record_tool_usage(
            user_id="u1", tool_id="t", action="run", cost_units=3, usage_key="k-id"
        )
        out = mu.refund_tool_usage(usage_id=rec["usage_id"])
        # audit_only debit -> refund status audit_only
        assert out["refund"]["status"] == "audit_only"

    def test_already_refunded_returns_existing(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        mu.record_tool_usage(user_id="u1", tool_id="t", action="run", cost_units=3, usage_key="dup")
        first = mu.refund_tool_usage(usage_key="dup")
        second = mu.refund_tool_usage(usage_key="dup")
        # second call returns the already-refunded target unchanged
        assert second["refund"]["refund_key"] == first["refund"]["refund_key"]
        assert second["refund_status"] == first["refund_status"]

    def test_zero_cost_is_not_charged(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        mu.record_tool_usage(
            user_id="u1", tool_id="t", action="run", cost_units=0, usage_key="free"
        )
        out = mu.refund_tool_usage(usage_key="free")
        assert out["refund"]["status"] == "not_charged"

    def test_local_wallet_refund_restores_units(self, ledger, monkeypatch) -> None:
        monkeypatch.delenv("MODEL_USAGE_WALLET_BACKEND", raising=False)
        monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
        mu.set_model_wallet_balance("u1", 10)
        mu.record_tool_usage(
            user_id="u1", tool_id="t", action="run", cost_units=4, usage_key="local1"
        )
        # balance debited to 6
        assert mu.get_model_wallet("u1")["balance_units"] == 6
        out = mu.refund_tool_usage(usage_key="local1")
        assert out["refund"]["status"] == "refunded"
        assert out["refund"]["balance_after_units"] == 10
        assert mu.get_model_wallet("u1")["balance_units"] == 10

    def test_market_wallet_refund_path(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "tok")
        # First record a tool usage whose market debit succeeds.
        debit_responses = [
            ({"hold": {"hold_no": "HM1"}}, None),  # preauth
            ({"balance": "9.00"}, None),  # settle
        ]
        with patch.object(mu, "_market_post_json", side_effect=debit_responses):
            rec = mu.record_tool_usage(
                user_id="u1", tool_id="t", action="run", cost_units=5, usage_key="mkt1"
            )
        assert rec["billing_source"] == "market_wallet"
        assert rec["billing_status"] == "debited"
        # Now refund -> goes through _apply_market_wallet_refund.
        with patch.object(
            mu,
            "_market_post_json",
            return_value=({"balance": "14.00", "refund": {"refund_no": "RM1"}}, None),
        ):
            out = mu.refund_tool_usage(usage_key="mkt1", reason="oops")
        assert out["refund"]["status"] == "refunded"


# --------------------------------------------------------------------------- #
# _record_usage_entry billing source for market failure                       #
# --------------------------------------------------------------------------- #
class TestRecordUsageEntryMarketFailure:
    def test_market_debit_failed_sets_billing_source(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
        monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "tok")
        with patch.object(
            mu,
            "_market_post_json",
            return_value=(None, {"status": "market_debit_failed", "message": "down"}),
        ):
            rec = mu.record_model_usage(
                user_id="u1",
                provider="openai",
                model="gpt",
                total_tokens=2000,
                usage_key="mf1",
            )
        assert rec["billing_status"] == "market_debit_failed"
        assert rec["billing_source"] == "market_wallet"

    def test_market_auth_missing_sets_failed(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
        for var in (
            "MODEL_USAGE_MARKET_AUTH_TOKEN",
            "XCAGI_MARKET_AUTH_TOKEN",
            "MODSTORE_AUTH_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        # No token anywhere -> _market_post_json returns market_auth_missing.
        with patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            return_value="",
        ):
            rec = mu.record_model_usage(
                user_id="u1",
                provider="openai",
                model="gpt",
                total_tokens=2000,
                usage_key="am1",
            )
        assert rec["billing_status"] == "market_debit_failed"
        assert rec["billing_source"] == "market_wallet"

    def test_idempotent_dedup_returns_existing(self, ledger, monkeypatch) -> None:
        monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
        first = mu.record_model_usage(
            user_id="u1", provider="p", model="m", total_tokens=1000, usage_key="same"
        )
        second = mu.record_model_usage(
            user_id="u1", provider="p", model="m", total_tokens=9999, usage_key="same"
        )
        assert second["usage_id"] == first["usage_id"]
        assert second["total_tokens"] == first["total_tokens"]
