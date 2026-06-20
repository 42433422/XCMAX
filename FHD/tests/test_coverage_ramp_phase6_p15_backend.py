"""COVERAGE_RAMP Phase 6 round 15: backend low-coverage modules.

Targets:
- ``app/fastapi_routes/market_account.py`` (667 行，未覆盖 81 行，cov 85.4%)
- ``app/services/skills/label_template_generator/label_template_generator.py`` (359 行，未覆盖 80 行，cov 72.5%)
- ``app/services/tools_workflow_registered.py`` (399 行，未覆盖 79 行，cov 75.9%)
- ``app/fastapi_routes/mod_store_routes.py`` (475 行，未覆盖 76 行，cov 79.2%)
- ``app/infrastructure/mods/catalog_client.py`` (153 行，未覆盖 76 行，cov 40.1%)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

import app.fastapi_routes.market_account as ma
import app.fastapi_routes.mod_store_routes as msr
import app.infrastructure.mods.catalog_client as cc
import app.services.skills.label_template_generator.label_template_generator as ltg
import app.services.tools_workflow_registered as twr
from app.fastapi_routes.market_account import router as market_router
from app.fastapi_routes.mod_store_routes import router as mod_store_router


@pytest.fixture(autouse=True)
def _clear_market_token_caches():
    ma._MARKET_SESSION_TOKENS.clear()
    ma._MARKET_SESSION_REFRESH_TOKENS.clear()
    yield
    ma._MARKET_SESSION_TOKENS.clear()
    ma._MARKET_SESSION_REFRESH_TOKENS.clear()


@pytest.fixture
def market_client() -> TestClient:
    app = FastAPI()
    app.include_router(market_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mod_store_client() -> TestClient:
    app = FastAPI()
    app.include_router(mod_store_router)
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# 1. app/fastapi_routes/market_account.py
# ===========================================================================


class TestMarketAuthHeader:
    """Cover ``_auth_header`` helper branches."""

    def test_auth_header_plain_token_adds_bearer(self) -> None:
        assert ma._auth_header("mytoken") == "Bearer mytoken"

    def test_auth_header_already_bearer_kept(self) -> None:
        assert ma._auth_header("Bearer mytoken") == "Bearer mytoken"

    def test_auth_header_strips_authorization_prefix(self) -> None:
        assert ma._auth_header("Authorization: mytoken") == "Bearer mytoken"

    def test_auth_header_empty_string_returns_empty(self) -> None:
        assert ma._auth_header("") == ""

    def test_auth_header_none_returns_empty(self) -> None:
        assert ma._auth_header(None) == ""

    def test_auth_header_bearer_case_insensitive(self) -> None:
        assert ma._auth_header("bearer mytoken") == "bearer mytoken"

    def test_auth_header_whitespace_only_returns_empty(self) -> None:
        assert ma._auth_header("   ") == ""


class TestMarketNormalizeBearerToken:
    """Cover ``_normalize_bearer_token`` branches."""

    def test_strips_bearer_prefix(self) -> None:
        assert ma._normalize_bearer_token("Bearer mytoken") == "mytoken"

    def test_no_prefix_returns_as_is(self) -> None:
        assert ma._normalize_bearer_token("mytoken") == "mytoken"

    def test_empty_returns_empty(self) -> None:
        assert ma._normalize_bearer_token("") == ""

    def test_none_returns_empty(self) -> None:
        assert ma._normalize_bearer_token(None) == ""

    def test_whitespace_only_returns_empty(self) -> None:
        assert ma._normalize_bearer_token("   ") == ""


class TestMarketBaseUrl:
    """Cover ``_market_base_url`` env handling."""

    def test_default_when_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("XCAGI_MARKET_BASE_URL", None)
            url = ma._market_base_url()
        assert "127.0.0.1:8765" in url

    def test_env_override(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.test/"}):
            assert ma._market_base_url() == "https://market.test"

    def test_strips_trailing_slash(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://m.test////"}):
            assert ma._market_base_url() == "https://m.test"

    def test_empty_env_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": ""}):
            url = ma._market_base_url()
        assert "127.0.0.1:8765" in url


class TestMarketHttpConfig:
    """Cover ``_market_http_timeout`` / ``_market_http_retries``."""

    def test_timeout_default(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("XCAGI_MARKET_HTTP_TIMEOUT", None)
            assert ma._market_http_timeout() == 20.0

    def test_timeout_env_override(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": "30"}):
            assert ma._market_http_timeout() == 30.0

    def test_timeout_invalid_env_falls_back(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": "abc"}):
            assert ma._market_http_timeout() == 20.0

    def test_retries_default(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("XCAGI_MARKET_HTTP_RETRIES", None)
            assert ma._market_http_retries() == 1

    def test_retries_env_override(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "5"}):
            assert ma._market_http_retries() == 5

    def test_retries_invalid_env_falls_back(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "xyz"}):
            assert ma._market_http_retries() == 1

    def test_retries_zero_clamped_to_one(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "0"}):
            assert ma._market_http_retries() == 1


class TestMarketSessionIdFromRequest:
    """Cover ``session_id_from_request``."""

    def test_from_cookie(self) -> None:
        req = MagicMock()
        req.cookies = {"session_id": "abc123"}
        req.headers = {}
        assert ma.session_id_from_request(req) == "abc123"

    def test_from_header_when_no_cookie(self) -> None:
        req = MagicMock()
        req.cookies = {}
        req.headers = {"X-Session-ID": "hdr-session"}
        assert ma.session_id_from_request(req) == "hdr-session"

    def test_cookie_takes_precedence(self) -> None:
        req = MagicMock()
        req.cookies = {"session_id": "cookie-sid"}
        req.headers = {"X-Session-ID": "hdr-sid"}
        assert ma.session_id_from_request(req) == "cookie-sid"

    def test_empty_when_neither(self) -> None:
        req = MagicMock()
        req.cookies = {}
        req.headers = {}
        assert ma.session_id_from_request(req) == ""

    def test_custom_cookie_name(self) -> None:
        with patch.dict("os.environ", {"SESSION_COOKIE_NAME": "custom_sid"}):
            req = MagicMock()
            req.cookies = {"custom_sid": "custom-value"}
            req.headers = {}
            assert ma.session_id_from_request(req) == "custom-value"


class TestMarketSaveSessionToken:
    """Cover ``save_session_market_token``."""

    def test_saves_to_memory(self) -> None:
        ma.save_session_market_token("sid1", "tok1")
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"

    def test_saves_refresh_token(self) -> None:
        ma.save_session_market_token("sid1", "tok1", "refresh1")
        assert ma._MARKET_SESSION_REFRESH_TOKENS["sid1"] == "refresh1"

    def test_empty_session_id_no_op(self) -> None:
        ma.save_session_market_token("", "tok1")
        assert ma._MARKET_SESSION_TOKENS == {}

    def test_empty_token_no_op(self) -> None:
        ma.save_session_market_token("sid1", "")
        assert ma._MARKET_SESSION_TOKENS == {}

    def test_none_inputs_no_op(self) -> None:
        ma.save_session_market_token(None, None)
        assert ma._MARKET_SESSION_TOKENS == {}

    def test_db_persist_swallows_recoverable_error(self) -> None:
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            ma.save_session_market_token("sid1", "tok1")
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"

    def test_db_persist_skips_when_no_row(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        with patch("app.db.session.get_db") as get_db:
            get_db.return_value.__enter__.return_value = mock_db
            ma.save_session_market_token("sid1", "tok1")
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"
        mock_db.commit.assert_not_called()


class TestMarketClearSessionToken:
    """Cover ``clear_session_market_token``."""

    def test_clears_from_memory(self) -> None:
        ma._MARKET_SESSION_TOKENS["sid1"] = "tok1"
        ma._MARKET_SESSION_REFRESH_TOKENS["sid1"] = "rtok1"
        ma.clear_session_market_token("sid1")
        assert "sid1" not in ma._MARKET_SESSION_TOKENS
        assert "sid1" not in ma._MARKET_SESSION_REFRESH_TOKENS

    def test_empty_session_id_no_op(self) -> None:
        ma._MARKET_SESSION_TOKENS["sid1"] = "tok1"
        ma.clear_session_market_token("")
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"

    def test_clear_nonexistent_session_no_error(self) -> None:
        ma.clear_session_market_token("never-existed")

    def test_db_clear_swallows_recoverable_error(self) -> None:
        ma._MARKET_SESSION_TOKENS["sid1"] = "tok1"
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            ma.clear_session_market_token("sid1")
        assert "sid1" not in ma._MARKET_SESSION_TOKENS


class TestMarketSessionToken:
    """Cover ``session_market_token`` and ``session_market_refresh_token``."""

    def test_session_token_from_memory(self) -> None:
        ma._MARKET_SESSION_TOKENS["sid1"] = "tok1"
        assert ma.session_market_token("sid1") == "tok1"

    def test_session_token_empty_sid(self) -> None:
        assert ma.session_market_token("") == ""

    def test_session_token_none_sid(self) -> None:
        assert ma.session_market_token(None) == ""

    def test_session_token_db_fallback(self) -> None:
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.market_access_token = "db-tok"
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_row
        mock_db.query.return_value = mock_query
        with patch("app.db.session.get_db") as get_db:
            get_db.return_value.__enter__.return_value = mock_db
            result = ma.session_market_token("sid1")
        assert result == "db-tok"
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "db-tok"

    def test_session_token_db_no_row(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        with patch("app.db.session.get_db") as get_db:
            get_db.return_value.__enter__.return_value = mock_db
            result = ma.session_market_token("sid1")
        assert result == ""

    def test_session_token_db_recoverable_error(self) -> None:
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            result = ma.session_market_token("sid1")
        assert result == ""

    def test_refresh_token_from_memory(self) -> None:
        ma._MARKET_SESSION_REFRESH_TOKENS["sid1"] = "rtok1"
        assert ma.session_market_refresh_token("sid1") == "rtok1"

    def test_refresh_token_empty_sid(self) -> None:
        assert ma.session_market_refresh_token("") == ""

    def test_refresh_token_db_fallback(self) -> None:
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.market_refresh_token = "db-rtok"
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_row
        mock_db.query.return_value = mock_query
        with patch("app.db.session.get_db") as get_db:
            get_db.return_value.__enter__.return_value = mock_db
            result = ma.session_market_refresh_token("sid1")
        assert result == "db-rtok"


class TestMarketLatestSessionToken:
    """Cover ``latest_session_market_token`` / ``latest_session_market_refresh_token``."""

    def test_latest_token_returns_empty_on_db_error(self) -> None:
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            assert ma.latest_session_market_token() == ""

    def test_latest_refresh_token_returns_empty_on_db_error(self) -> None:
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            assert ma.latest_session_market_refresh_token() == ""

    def test_latest_token_returns_first_non_empty(self) -> None:
        mock_db = MagicMock()
        row1 = MagicMock()
        row1.market_access_token = ""
        row2 = MagicMock()
        row2.market_access_token = "tok2"
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            row1,
            row2,
        ]
        mock_db.query.return_value = mock_query
        with patch("app.db.session.get_db") as get_db:
            get_db.return_value.__enter__.return_value = mock_db
            result = ma.latest_session_market_token()
        assert result == "tok2"

    def test_latest_token_returns_empty_when_no_rows(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        with patch("app.db.session.get_db") as get_db:
            get_db.return_value.__enter__.return_value = mock_db
            result = ma.latest_session_market_token()
        assert result == ""


class TestMarketProxyErrorHttpStatus:
    """Cover ``_proxy_error_http_status``."""

    def test_returns_none_for_non_dict(self) -> None:
        assert ma._proxy_error_http_status("not a dict") is None

    def test_returns_none_for_dict_without_proxy_error(self) -> None:
        assert ma._proxy_error_http_status({"foo": "bar"}) is None

    def test_returns_status_code(self) -> None:
        payload = {"__proxy_error__": True, "status_code": 401}
        assert ma._proxy_error_http_status(payload) == 401

    def test_returns_none_when_status_code_none(self) -> None:
        payload = {"__proxy_error__": True, "status_code": None}
        assert ma._proxy_error_http_status(payload) is None

    def test_returns_none_when_status_code_invalid(self) -> None:
        payload = {"__proxy_error__": True, "status_code": "abc"}
        assert ma._proxy_error_http_status(payload) is None


class TestMarketBodySnippet:
    """Cover ``_body_snippet``."""

    def test_dict_payload(self) -> None:
        result = ma._body_snippet({"key": "value"})
        assert "key" in result and "value" in result

    def test_string_payload(self) -> None:
        assert ma._body_snippet("hello") == "hello"

    def test_none_payload(self) -> None:
        assert ma._body_snippet(None) == ""

    def test_long_payload_truncated(self) -> None:
        long_text = "x" * 500
        result = ma._body_snippet(long_text, limit=10)
        assert result.endswith("…")
        assert len(result) == 11

    def test_short_payload_not_truncated(self) -> None:
        assert ma._body_snippet("short") == "short"

    def test_dict_payload_with_newlines(self) -> None:
        result = ma._body_snippet({"key": "line1\nline2"})
        assert "\n" not in result


class TestMarketErrorMessage:
    """Cover ``_error_message``."""

    def test_dict_with_detail(self) -> None:
        result = ma._error_message({"detail": "bad request"}, 400)
        assert "bad request" in result

    def test_dict_with_message(self) -> None:
        result = ma._error_message({"message": "custom msg"}, 400)
        assert result == "custom msg"

    def test_dict_with_error_field(self) -> None:
        result = ma._error_message({"error": "err msg"}, 400)
        assert result == "err msg"

    def test_dict_with_detail_list(self) -> None:
        payload = {"detail": [{"msg": "err1"}, {"msg": "err2"}]}
        result = ma._error_message(payload, 400)
        assert "err1" in result and "err2" in result

    def test_500_status_with_message(self) -> None:
        result = ma._error_message({"detail": "boom"}, 500)
        assert "500" in result and "boom" in result

    def test_500_status_with_internal_server_error(self) -> None:
        result = ma._error_message({"detail": "Internal Server Error"}, 500)
        assert "500" in result

    def test_500_status_no_message(self) -> None:
        result = ma._error_message({}, 500)
        assert "500" in result

    def test_non_dict_payload_500(self) -> None:
        result = ma._error_message("string error", 500)
        assert "500" in result

    def test_non_dict_payload_400(self) -> None:
        result = ma._error_message("string error", 400)
        assert "400" in result


class TestMarketTransportErrorMessage:
    """Cover ``_transport_error_message``."""

    def test_read_timeout_returns_503(self) -> None:
        exc = httpx.ReadTimeout("timeout")
        msg, status = ma._transport_error_message(exc)
        assert status == 503
        assert "超时" in msg

    def test_other_httpx_error_returns_502(self) -> None:
        exc = httpx.ConnectError("conn refused")
        msg, status = ma._transport_error_message(exc)
        assert status == 502
        assert "无法连接" in msg

    def test_generic_exception_returns_502(self) -> None:
        exc = RuntimeError("boom")
        msg, status = ma._transport_error_message(exc)
        assert status == 502
        assert "boom" in msg

    def test_empty_exception_message_uses_type_name(self) -> None:
        exc = httpx.ConnectError("")
        msg, status = ma._transport_error_message(exc)
        assert status == 502
        assert "ConnectError" in msg


class TestMarketTokenFromAuthResponse:
    """Cover ``_token_from_auth_response``."""

    def test_none_payload(self) -> None:
        assert ma._token_from_auth_response(None) == ""

    def test_non_dict_payload(self) -> None:
        assert ma._token_from_auth_response("string") == ""

    def test_top_level_access_token(self) -> None:
        assert ma._token_from_auth_response({"access_token": "tok"}) == "tok"

    def test_top_level_token(self) -> None:
        assert ma._token_from_auth_response({"token": "tok"}) == "tok"

    def test_data_nested_access_token(self) -> None:
        payload = {"data": {"access_token": "nested-tok"}}
        assert ma._token_from_auth_response(payload) == "nested-tok"

    def test_data_nested_token(self) -> None:
        payload = {"data": {"token": "nested-tok"}}
        assert ma._token_from_auth_response(payload) == "nested-tok"

    def test_data_nested_market_access_token(self) -> None:
        payload = {"data": {"market_access_token": "mtok"}}
        assert ma._token_from_auth_response(payload) == "mtok"

    def test_tokens_nested_in_data(self) -> None:
        payload = {"data": {"tokens": {"access_token": "deep-tok"}}}
        assert ma._token_from_auth_response(payload) == "deep-tok"

    def test_tokens_nested_at_top(self) -> None:
        payload = {"tokens": {"accessToken": "camel-tok"}}
        assert ma._token_from_auth_response(payload) == "camel-tok"

    def test_empty_token_values_skipped(self) -> None:
        payload = {"access_token": "", "token": "  ", "data": {"token": "real"}}
        assert ma._token_from_auth_response(payload) == "real"

    def test_no_token_found(self) -> None:
        assert ma._token_from_auth_response({"foo": "bar"}) == ""


class TestMarketRefreshTokenFromAuthResponse:
    """Cover ``_refresh_token_from_auth_response``."""

    def test_none_payload(self) -> None:
        assert ma._refresh_token_from_auth_response(None) == ""

    def test_non_dict_payload(self) -> None:
        assert ma._refresh_token_from_auth_response("string") == ""

    def test_top_level_refresh_token(self) -> None:
        assert ma._refresh_token_from_auth_response({"refresh_token": "rtok"}) == "rtok"

    def test_top_level_camel_case(self) -> None:
        assert ma._refresh_token_from_auth_response({"refreshToken": "rtok"}) == "rtok"

    def test_data_nested_refresh_token(self) -> None:
        payload = {"data": {"refresh_token": "nested-rtok"}}
        assert ma._refresh_token_from_auth_response(payload) == "nested-rtok"

    def test_tokens_nested_in_data(self) -> None:
        payload = {"data": {"tokens": {"refresh_token": "deep-rtok"}}}
        assert ma._refresh_token_from_auth_response(payload) == "deep-rtok"

    def test_no_refresh_token_found(self) -> None:
        assert ma._refresh_token_from_auth_response({"foo": "bar"}) == ""


class TestMarketUserBlobFromPayload:
    """Cover ``_user_blob_from_market_payload``."""

    def test_none_payload(self) -> None:
        assert ma._user_blob_from_market_payload(None) == {}

    def test_non_dict_payload(self) -> None:
        assert ma._user_blob_from_market_payload("string") == {}

    def test_top_level_user(self) -> None:
        payload = {"user": {"id": 1, "username": "alice"}}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 1
        assert result["username"] == "alice"

    def test_data_nested_user(self) -> None:
        payload = {"data": {"user": {"id": 2, "username": "bob"}}}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 2

    def test_data_dict_with_id_and_username(self) -> None:
        payload = {"data": {"id": 3, "username": "carol"}}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 3

    def test_top_level_id_and_username(self) -> None:
        payload = {"id": 4, "username": "dave"}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 4

    def test_no_user_info(self) -> None:
        assert ma._user_blob_from_market_payload({"foo": "bar"}) == {}


class TestMarketIdentityFromPayloads:
    """Cover ``_market_identity_from_payloads``."""

    def test_empty_payloads(self) -> None:
        is_ent, is_admin, blob = ma._market_identity_from_payloads()
        assert is_ent is False
        assert is_admin is False
        assert blob == {}

    def test_proxy_error_payloads_skipped(self) -> None:
        payload = {"__proxy_error__": True, "status_code": 500}
        is_ent, is_admin, blob = ma._market_identity_from_payloads(payload)
        assert blob == {}

    def test_user_blob_extracted(self) -> None:
        payload = {"user": {"id": 1, "username": "alice", "is_enterprise": True}}
        is_ent, is_admin, blob = ma._market_identity_from_payloads(payload)
        assert is_ent is True
        assert blob["username"] == "alice"

    def test_admin_flag_extracted(self) -> None:
        payload = {"user": {"id": 1, "username": "alice", "is_admin": True}}
        is_ent, is_admin, blob = ma._market_identity_from_payloads(payload)
        assert is_admin is True

    def test_multiple_payloads_merged(self) -> None:
        p1 = {"user": {"id": 1, "username": "alice"}}
        p2 = {"user": {"id": 1, "is_enterprise": True, "is_admin": False}}
        is_ent, is_admin, blob = ma._market_identity_from_payloads(p1, p2)
        assert is_ent is True
        assert is_admin is False


class TestMarketIsLocalMarketBase:
    """Cover ``_is_local_market_base``."""

    def test_127_0_0_1(self) -> None:
        assert ma._is_local_market_base("http://127.0.0.1:8765") is True

    def test_localhost(self) -> None:
        assert ma._is_local_market_base("http://localhost:8765") is True

    def test_remote_url(self) -> None:
        assert ma._is_local_market_base("https://market.example.com") is False

    def test_empty_string(self) -> None:
        assert ma._is_local_market_base("") is False

    def test_none_input(self) -> None:
        assert ma._is_local_market_base(None) is False


class TestMarketLooksLikeVerificationRequired:
    """Cover ``_looks_like_verification_required``."""

    def test_chinese_verification_code(self) -> None:
        payload = {"detail": "需要验证码"}
        assert ma._looks_like_verification_required(payload) is True

    def test_english_verification(self) -> None:
        payload = {"detail": "verification required"}
        assert ma._looks_like_verification_required(payload) is True

    def test_english_code(self) -> None:
        payload = {"detail": "invalid code"}
        assert ma._looks_like_verification_required(payload) is True

    def test_no_match(self) -> None:
        payload = {"detail": "wrong password"}
        assert ma._looks_like_verification_required(payload) is False


class TestMarketAuthorizationFromRequest:
    """Cover ``_authorization_from_request``."""

    def test_from_session_token(self) -> None:
        ma._MARKET_SESSION_TOKENS["sid1"] = "tok1"
        req = MagicMock()
        req.cookies = {"session_id": "sid1"}
        req.headers = {}
        body: dict[str, Any] = {}
        assert ma._authorization_from_request(req, body) == "Bearer tok1"

    def test_from_latest_token_when_no_session(self) -> None:
        with patch.object(ma, "latest_session_market_token", return_value="latest-tok"):
            req = MagicMock()
            req.cookies = {}
            req.headers = {}
            body: dict[str, Any] = {}
            assert ma._authorization_from_request(req, body) == "Bearer latest-tok"

    def test_from_body_authorization(self) -> None:
        req = MagicMock()
        req.cookies = {}
        req.headers = {}
        body = {"authorization": "body-tok"}
        assert ma._authorization_from_request(req, body) == "Bearer body-tok"

    def test_from_body_token(self) -> None:
        req = MagicMock()
        req.cookies = {}
        req.headers = {}
        body = {"token": "body-tok"}
        assert ma._authorization_from_request(req, body) == "Bearer body-tok"

    def test_from_request_header(self) -> None:
        req = MagicMock()
        req.cookies = {}
        req.headers = {"Authorization": "hdr-tok"}
        body: dict[str, Any] = {}
        assert ma._authorization_from_request(req, body) == "Bearer hdr-tok"

    def test_empty_when_no_source(self) -> None:
        req = MagicMock()
        req.cookies = {}
        req.headers = {}
        body: dict[str, Any] = {}
        assert ma._authorization_from_request(req, body) == ""


class TestMarketDegradedAccountOverview:
    """Cover ``_degraded_account_overview``."""

    def test_returns_degraded_structure(self) -> None:
        result = ma._degraded_account_overview("service down")
        assert result["degraded"] is True
        assert result["market_unreachable"] is True
        assert result["sync_warning"] == "service down"
        assert result["user"] == {}
        assert result["wallet"] == {"balance": None}
        assert result["membership"]["tier"] == "unknown"

    def test_empty_message(self) -> None:
        result = ma._degraded_account_overview("")
        assert result["sync_warning"] == ""


class TestMarketMergeLiveOverviewFields:
    """Cover ``_merge_live_overview_fields``."""

    def test_merges_wallet(self) -> None:
        data: dict[str, Any] = {}
        ma._merge_live_overview_fields(data, {"wallet": {"balance": 100}})
        assert data["wallet"] == {"balance": 100}

    def test_skips_none_values(self) -> None:
        data: dict[str, Any] = {"wallet": {"balance": 50}}
        ma._merge_live_overview_fields(data, {"wallet": None})
        assert data["wallet"] == {"balance": 50}

    def test_merges_llm_dict(self) -> None:
        data = {"llm": {"providers": ["a"]}}
        ma._merge_live_overview_fields(data, {"llm": {"providers": ["b"], "extra": 1}})
        assert "b" in data["llm"]["providers"]
        assert data["llm"]["extra"] == 1

    def test_merges_user(self) -> None:
        data: dict[str, Any] = {}
        ma._merge_live_overview_fields(data, {"user": {"id": 1}})
        assert data["user"] == {"id": 1}


class TestMarketSendMarketResetPasswordCode:
    """Cover ``send_market_reset_password_code``."""

    @pytest.mark.asyncio
    async def test_invalid_email_returns_error(self) -> None:
        result = await ma.send_market_reset_password_code("not-an-email")
        assert result["success"] is False
        assert "邮箱" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_email_returns_error(self) -> None:
        result = await ma.send_market_reset_password_code("")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_none_email_returns_error(self) -> None:
        result = await ma.send_market_reset_password_code(None)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_valid_email_success(self) -> None:
        with patch.object(
            ma, "_proxy_json", new_callable=AsyncMock, return_value={"message": "ok"}
        ):
            result = await ma.send_market_reset_password_code("user@test.com")
        assert result["success"] is True
        assert result["message"] == "ok"

    @pytest.mark.asyncio
    async def test_valid_email_default_message(self) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={}):
            result = await ma.send_market_reset_password_code("user@test.com")
        assert result["success"] is True
        assert "已注册" in result["message"]

    @pytest.mark.asyncio
    async def test_proxy_error_returns_failure(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 502, "payload": {}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            result = await ma.send_market_reset_password_code("user@test.com")
        assert result["success"] is False


class TestMarketResetMarketPasswordWithCode:
    """Cover ``reset_market_password_with_code``."""

    @pytest.mark.asyncio
    async def test_invalid_email_returns_error(self) -> None:
        result = await ma.reset_market_password_with_code("bad", "1234", "newpass")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_short_code_returns_error(self) -> None:
        result = await ma.reset_market_password_with_code("u@t.com", "12", "newpass")
        assert result["success"] is False
        assert "验证码" in result["message"]

    @pytest.mark.asyncio
    async def test_short_password_returns_error(self) -> None:
        result = await ma.reset_market_password_with_code("u@t.com", "1234", "short")
        assert result["success"] is False
        assert "密码" in result["message"]

    @pytest.mark.asyncio
    async def test_success_path(self) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={}):
            result = await ma.reset_market_password_with_code("u@t.com", "123456", "newpassword")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_proxy_error_returns_failure(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 400, "payload": {}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            result = await ma.reset_market_password_with_code("u@t.com", "123456", "newpassword")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_server_returns_success_false(self) -> None:
        with patch.object(
            ma,
            "_proxy_json",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "expired"},
        ):
            result = await ma.reset_market_password_with_code("u@t.com", "123456", "newpassword")
        assert result["success"] is False
        assert "expired" in result["message"]


class TestMarketRegisterMarketUser:
    """Cover ``register_market_user``."""

    @pytest.mark.asyncio
    async def test_success_returns_token(self) -> None:
        payload = {"access_token": "newtok", "refresh_token": "newrtok"}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=payload):
            result = await ma.register_market_user("alice", "pass123", "alice@t.com")
        assert result["success"] is True
        assert result["token"] == "newtok"
        assert result["refresh_token"] == "newrtok"

    @pytest.mark.asyncio
    async def test_proxy_error_no_verification_code(self) -> None:
        error_payload = {
            "__proxy_error__": True,
            "status_code": 400,
            "payload": {"detail": "需要验证码"},
        }
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            result = await ma.register_market_user("alice", "pass123", "alice@t.com")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_proxy_error_500(self) -> None:
        error_payload = {
            "__proxy_error__": True,
            "status_code": 500,
            "payload": {"detail": "boom"},
        }
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            result = await ma.register_market_user("alice", "pass123", "alice@t.com")
        assert result["success"] is False


class TestMarketSendMarketPhoneCode:
    """Cover ``send_market_phone_code``."""

    @pytest.mark.asyncio
    async def test_success_with_message(self) -> None:
        with patch.object(
            ma, "_proxy_json", new_callable=AsyncMock, return_value={"message": "sent"}
        ):
            result = await ma.send_market_phone_code("13800000000")
        assert result["success"] is True
        assert result["message"] == "sent"

    @pytest.mark.asyncio
    async def test_success_default_message(self) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={}):
            result = await ma.send_market_phone_code("13800000000")
        assert result["success"] is True
        assert "已发送" in result["message"]

    @pytest.mark.asyncio
    async def test_json_response_returns_failure(self) -> None:
        json_resp = JSONResponse({"message": "failed"}, status_code=502)
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=json_resp):
            result = await ma.send_market_phone_code("13800000000")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_non_dict_payload(self) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value="string"):
            result = await ma.send_market_phone_code("13800000000")
        assert result["success"] is True


class TestMarketLoginMarketWithPhoneCode:
    """Cover ``login_market_with_phone_code``."""

    @pytest.mark.asyncio
    async def test_success_path(self) -> None:
        payload = {"access_token": "tok", "data": {"user": {"id": 1, "username": "u"}}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=payload):
            result = await ma.login_market_with_phone_code("13800000000", "1234")
        assert result["success"] is True
        assert result["token"] == "tok"

    @pytest.mark.asyncio
    async def test_no_token_returns_failure(self) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={}):
            result = await ma.login_market_with_phone_code("13800000000", "1234")
        assert result["success"] is False


class TestMarketLoginMarketWithPassword:
    """Cover ``login_market_with_password``."""

    @pytest.mark.asyncio
    async def test_demo_login_for_local_base(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "http://127.0.0.1:8765"}):
            with patch(
                "app.application.surface_audit_demo_account.try_local_demo_market_login",
                return_value={"token": "demo", "is_enterprise": True, "is_market_admin": False},
            ):
                result = await ma.login_market_with_password("demo", "demo")
        assert result["success"] is True
        assert result["token"] == "demo"

    @pytest.mark.asyncio
    async def test_remote_success(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.test"}):
            with patch(
                "app.application.surface_audit_demo_account.try_local_demo_market_login",
                return_value=None,
            ):
                payload = {"access_token": "remote-tok"}
                with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=payload):
                    result = await ma.login_market_with_password("alice", "pass")
        assert result["success"] is True
        assert result["token"] == "remote-tok"


class TestMarketRegisterRoute:
    """Cover ``/api/market/register`` route."""

    def test_missing_username_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post(
            "/api/market/register", json={"password": "p", "email": "e@t.com"}
        )
        assert resp.status_code == 400
        assert "必填" in resp.json()["message"]

    def test_missing_password_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post(
            "/api/market/register", json={"username": "u", "email": "e@t.com"}
        )
        assert resp.status_code == 400

    def test_missing_email_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/register", json={"username": "u", "password": "p"})
        assert resp.status_code == 400

    def test_success_returns_token(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "register_market_user",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "token": "newtok",
                "market_base_url": "http://test",
                "raw": {},
            },
        ):
            resp = market_client.post(
                "/api/market/register",
                json={"username": "u", "password": "p", "email": "e@t.com"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["token"] == "newtok"

    def test_register_failure_returns_400(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "register_market_user",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "exists"},
        ):
            resp = market_client.post(
                "/api/market/register",
                json={"username": "u", "password": "p", "email": "e@t.com"},
            )
        assert resp.status_code == 400


class TestMarketLoginRoute:
    """Cover ``/api/market/login`` route."""

    def test_missing_credentials_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/login", json={"username": "u"})
        assert resp.status_code == 400

    def test_success_returns_token(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "login_market_with_password",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "token": "tok",
                "market_base_url": "http://test",
                "raw": {},
            },
        ):
            resp = market_client.post("/api/market/login", json={"username": "u", "password": "p"})
        assert resp.status_code == 200
        assert resp.json()["data"]["token"] == "tok"

    def test_login_failure_returns_403(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "login_market_with_password",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "bad creds"},
        ):
            resp = market_client.post("/api/market/login", json={"username": "u", "password": "p"})
        assert resp.status_code == 403


class TestMarketSendPhoneCodeRoute:
    """Cover ``/api/market/send-phone-code`` route."""

    def test_missing_phone_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/send-phone-code", json={})
        assert resp.status_code == 400

    def test_success_returns_200(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "send_market_phone_code",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "sent"},
        ):
            resp = market_client.post("/api/market/send-phone-code", json={"phone": "13800000000"})
        assert resp.status_code == 200

    def test_failure_returns_502(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "send_market_phone_code",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "fail", "status_code": 502},
        ):
            resp = market_client.post("/api/market/send-phone-code", json={"phone": "13800000000"})
        assert resp.status_code == 502


class TestMarketLoginWithPhoneCodeRoute:
    """Cover ``/api/market/login-with-phone-code`` route."""

    def test_missing_phone_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/login-with-phone-code", json={"code": "1234"})
        assert resp.status_code == 400

    def test_missing_code_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/login-with-phone-code", json={"phone": "138"})
        assert resp.status_code == 400

    def test_success_returns_token(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "login_market_with_phone_code",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "token": "tok",
                "refresh_token": "rtok",
                "market_base_url": "http://test",
            },
        ):
            resp = market_client.post(
                "/api/market/login-with-phone-code",
                json={"phone": "13800000000", "code": "1234"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["token"] == "tok"

    def test_failure_returns_401(self, market_client: TestClient) -> None:
        with patch.object(
            ma,
            "login_market_with_phone_code",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "message": "bad code",
                "status_code": 401,
                "error_code": "MARKET_AUTH_FAILED",
            },
        ):
            resp = market_client.post(
                "/api/market/login-with-phone-code",
                json={"phone": "13800000000", "code": "1234"},
            )
        assert resp.status_code == 401


class TestMarketAccountSyncRoute:
    """Cover ``/api/market/account-sync`` route."""

    def test_missing_authorization_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/account-sync", json={})
        assert resp.status_code == 400

    def test_authorization_from_body(self, market_client: TestClient) -> None:
        with patch.object(
            ma, "_proxy_json", new_callable=AsyncMock, return_value={"data": {"user": {"id": 1}}}
        ):
            resp = market_client.post(
                "/api/market/account-sync", json={"authorization": "Bearer tok"}
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_authorization_from_header(self, market_client: TestClient) -> None:
        with patch.object(
            ma, "_proxy_json", new_callable=AsyncMock, return_value={"data": {"user": {"id": 1}}}
        ):
            resp = market_client.post(
                "/api/market/account-sync",
                json={},
                headers={"Authorization": "Bearer hdr-tok"},
            )
        assert resp.status_code == 200


class TestMarketStatusRoute:
    """Cover ``/api/market/status`` route."""

    def test_reachable_returns_200(self, market_client: TestClient) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={"status": "ok"}):
            resp = market_client.get("/api/market/status")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["reachable"] is True

    def test_unreachable_returns_200_with_false(self, market_client: TestClient) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 502, "payload": {}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            resp = market_client.get("/api/market/status")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


class TestMarketPaymentRoutes:
    """Cover ``/api/market/payment/*`` routes."""

    def test_payment_plans_success(self, market_client: TestClient) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={"plans": []}):
            resp = market_client.get("/api/market/payment/plans")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_payment_plans_error(self, market_client: TestClient) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 502, "payload": {}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            resp = market_client.get("/api/market/payment/plans")
        assert resp.status_code == 502

    def test_payment_checkout_success(self, market_client: TestClient) -> None:
        with patch.object(
            ma, "_proxy_json", new_callable=AsyncMock, return_value={"url": "http://pay"}
        ):
            resp = market_client.post("/api/market/payment/checkout", json={"plan": "pro"})
        assert resp.status_code == 200

    def test_payment_orders_success(self, market_client: TestClient) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={"orders": []}):
            resp = market_client.get("/api/market/payment/orders")
        assert resp.status_code == 200

    def test_payment_orders_with_status(self, market_client: TestClient) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={"orders": []}):
            resp = market_client.get(
                "/api/market/payment/orders", params={"status": "paid", "limit": 10}
            )
        assert resp.status_code == 200

    def test_payment_query_success(self, market_client: TestClient) -> None:
        with patch.object(
            ma, "_proxy_json", new_callable=AsyncMock, return_value={"status": "paid"}
        ):
            resp = market_client.get("/api/market/payment/query/ORDER123")
        assert resp.status_code == 200


class TestMarketWalletOverviewRoute:
    """Cover ``/api/market/wallet/overview`` route."""

    def test_success(self, market_client: TestClient) -> None:
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={"balance": 100}):
            resp = market_client.get("/api/market/wallet/overview")
        assert resp.status_code == 200

    def test_error(self, market_client: TestClient) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 502, "payload": {}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            resp = market_client.get("/api/market/wallet/overview")
        assert resp.status_code == 502


class TestMarketDevCreateAccountRoute:
    """Cover ``/api/market/dev-create-account`` route."""

    def test_short_password_returns_400(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/dev-create-account", json={"password": "short"})
        assert resp.status_code == 400

    def test_success_with_default_fields(self, market_client: TestClient) -> None:
        with (
            patch.object(
                ma,
                "_register_without_verification",
                new_callable=AsyncMock,
                return_value={"access_token": "tok"},
            ),
            patch.object(
                ma,
                "_proxy_json",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ),
        ):
            resp = market_client.post("/api/market/dev-create-account", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_register_conflict_falls_back_to_login(self, market_client: TestClient) -> None:
        error_payload = {
            "__proxy_error__": True,
            "status_code": 409,
            "payload": {"detail": "用户已存在"},
        }
        with (
            patch.object(
                ma,
                "_register_without_verification",
                new_callable=AsyncMock,
                return_value=error_payload,
            ),
            patch.object(
                ma,
                "_proxy_json",
                new_callable=AsyncMock,
                return_value={"access_token": "login-tok"},
            ),
        ):
            resp = market_client.post("/api/market/dev-create-account", json={})
        assert resp.status_code == 200

    def test_register_failure_returns_error(self, market_client: TestClient) -> None:
        error_payload = {
            "__proxy_error__": True,
            "status_code": 500,
            "payload": {"detail": "boom"},
        }
        with patch.object(
            ma,
            "_register_without_verification",
            new_callable=AsyncMock,
            return_value=error_payload,
        ):
            resp = market_client.post("/api/market/dev-create-account", json={})
        assert resp.status_code == 500


class TestMarketSessionHandoffRoute:
    """Cover ``/api/market/session-handoff`` route."""

    def test_no_user_no_token_returns_404(self, market_client: TestClient) -> None:
        with (
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
            patch.object(ma, "latest_session_market_token", return_value=""),
        ):
            resp = market_client.get("/api/market/session-handoff")
        assert resp.status_code == 404

    def test_no_user_with_latest_token_returns_200(self, market_client: TestClient) -> None:
        with (
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
            patch.object(ma, "latest_session_market_token", return_value="latest-tok"),
        ):
            resp = market_client.get("/api/market/session-handoff")
        assert resp.status_code == 200
        assert resp.json()["data"]["market_access_token"] == "latest-tok"


class TestMarketAccountOverviewRoute:
    """Cover ``/api/market/account-overview`` route."""

    def test_no_authorization_returns_401(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/account-overview", json={})
        assert resp.status_code == 401

    def test_success_returns_data(self, market_client: TestClient) -> None:
        with (
            patch.object(
                ma,
                "_authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch.object(
                ma,
                "_proxy_json",
                new_callable=AsyncMock,
                return_value={"data": {"user": {"id": 1}}},
            ),
            patch.object(ma, "_legacy_account_overview", new_callable=AsyncMock, return_value={}),
        ):
            resp = market_client.post("/api/market/account-overview", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_degraded_when_proxy_returns_json_response(self, market_client: TestClient) -> None:
        json_resp = JSONResponse({"message": "unavailable"}, status_code=502)
        with (
            patch.object(
                ma,
                "_authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=json_resp),
        ):
            resp = market_client.post("/api/market/account-overview", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["degraded"] is True


class TestMarketLlmCatalogRoute:
    """Cover ``/api/market/llm-catalog`` routes."""

    def test_no_authorization_returns_401(self, market_client: TestClient) -> None:
        resp = market_client.post("/api/market/llm-catalog", json={})
        assert resp.status_code == 401

    def test_get_success(self, market_client: TestClient) -> None:
        with (
            patch.object(
                ma,
                "_authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch.object(
                ma,
                "_proxy_json",
                new_callable=AsyncMock,
                return_value={"providers": ["openai"]},
            ),
        ):
            resp = market_client.get("/api/market/llm-catalog")
        assert resp.status_code == 200
        assert "providers" in resp.json()["data"]

    def test_post_success(self, market_client: TestClient) -> None:
        with (
            patch.object(
                ma,
                "_authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch.object(
                ma,
                "_proxy_json",
                new_callable=AsyncMock,
                return_value={"providers": ["openai"]},
            ),
        ):
            resp = market_client.post("/api/market/llm-catalog", json={"refresh": True})
        assert resp.status_code == 200

    def test_proxy_error_returns_degraded(self, market_client: TestClient) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 502, "payload": {}}
        with (
            patch.object(
                ma,
                "_authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload),
        ):
            resp = market_client.post("/api/market/llm-catalog", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["degraded"] is True


class TestMarketRefreshSessionMarketToken:
    """Cover ``refresh_session_market_token``."""

    @pytest.mark.asyncio
    async def test_no_refresh_token_returns_empty(self) -> None:
        with (
            patch.object(ma, "session_market_refresh_token", return_value=""),
            patch.object(ma, "latest_session_market_refresh_token", return_value=""),
        ):
            result = await ma.refresh_session_market_token("sid1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_success_returns_new_token(self) -> None:
        with (
            patch.object(ma, "session_market_refresh_token", return_value="rtok"),
            patch.object(
                ma,
                "_proxy_json",
                new_callable=AsyncMock,
                return_value={"access_token": "newtok", "refresh_token": "newrtok"},
            ),
        ):
            result = await ma.refresh_session_market_token("sid1")
        assert result == "newtok"
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "newtok"

    @pytest.mark.asyncio
    async def test_proxy_error_returns_empty(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 401, "payload": {}}
        with (
            patch.object(ma, "session_market_refresh_token", return_value="rtok"),
            patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload),
        ):
            result = await ma.refresh_session_market_token("sid1")
        assert result == ""


class TestMarketResolveValidMarketAccessToken:
    """Cover ``resolve_valid_market_access_token``."""

    @pytest.mark.asyncio
    async def test_no_token_returns_empty(self) -> None:
        with (
            patch.object(ma, "session_market_token", return_value=""),
            patch.object(ma, "latest_session_market_token", return_value=""),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_demo_token_returned_as_is(self) -> None:
        with (
            patch.object(ma, "session_market_token", return_value="demo-tok"),
            patch.object(ma, "latest_session_market_token", return_value=""),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=True,
            ),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "demo-tok"

    @pytest.mark.asyncio
    async def test_401_triggers_refresh(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 401, "payload": {}}
        with (
            patch.object(ma, "session_market_token", return_value="tok"),
            patch.object(ma, "latest_session_market_token", return_value=""),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=False,
            ),
            patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload),
            patch.object(
                ma, "refresh_session_market_token", new_callable=AsyncMock, return_value="refreshed"
            ),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "refreshed"

    @pytest.mark.asyncio
    async def test_other_error_returns_local_token(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 500, "payload": {}}
        with (
            patch.object(ma, "session_market_token", return_value="tok"),
            patch.object(ma, "latest_session_market_token", return_value=""),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=False,
            ),
            patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "tok"


class TestMarketRegisterWithoutVerification:
    """Cover ``_register_without_verification``."""

    @pytest.mark.asyncio
    async def test_first_endpoint_success(self) -> None:
        with patch.object(
            ma,
            "_proxy_json",
            new_callable=AsyncMock,
            return_value={"access_token": "tok"},
        ) as mock_proxy:
            result = await ma._register_without_verification("u", "p", "e@t.com")
        assert result == {"access_token": "tok"}
        assert mock_proxy.call_count == 1

    @pytest.mark.asyncio
    async def test_first_fails_falls_back_to_second(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 404, "payload": {}}
        success_payload = {"access_token": "tok2"}
        with patch.object(
            ma,
            "_proxy_json",
            new_callable=AsyncMock,
            side_effect=[error_payload, success_payload],
        ):
            result = await ma._register_without_verification("u", "p", "e@t.com")
        assert result == {"access_token": "tok2"}


class TestMarketNormalizeMarketAuthPayload:
    """Cover ``_normalize_market_auth_payload``."""

    @pytest.mark.asyncio
    async def test_json_response_returns_failure(self) -> None:
        json_resp = JSONResponse({"message": "bad"}, status_code=401)
        result = await ma._normalize_market_auth_payload(json_resp)
        assert result["success"] is False
        assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_json_response_500_sets_unavailable_code(self) -> None:
        json_resp = JSONResponse({"message": "boom"}, status_code=500)
        result = await ma._normalize_market_auth_payload(json_resp)
        assert result["success"] is False
        assert result["error_code"] == "MARKET_AUTH_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_no_token_returns_failure(self) -> None:
        result = await ma._normalize_market_auth_payload({"foo": "bar"})
        assert result["success"] is False
        assert "access_token" in result["message"]

    @pytest.mark.asyncio
    async def test_success_with_user_blob(self) -> None:
        payload = {"access_token": "tok", "user": {"id": 1, "username": "alice"}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value={}):
            result = await ma._normalize_market_auth_payload(payload)
        assert result["success"] is True
        assert result["token"] == "tok"
        assert result["raw"]["user"]["username"] == "alice"


class TestMarketLegacyAccountOverview:
    """Cover ``_legacy_account_overview``."""

    @pytest.mark.asyncio
    async def test_me_error_propagated(self) -> None:
        error_payload = {"__proxy_error__": True, "status_code": 401, "payload": {}}
        with patch.object(ma, "_proxy_json", new_callable=AsyncMock, return_value=error_payload):
            result = await ma._legacy_account_overview("Bearer tok")
        assert result.get("__proxy_error__") is True

    @pytest.mark.asyncio
    async def test_success_composes_overview(self) -> None:
        me = {"user": {"id": 1, "username": "alice"}}
        wallet = {"wallet": {"balance": 100}}
        plan = {"plan": "pro", "membership": {"tier": "pro"}, "quotas": []}
        llm = {"providers": [{"has_user_override": True}]}
        with patch.object(
            ma,
            "_proxy_json",
            new_callable=AsyncMock,
            side_effect=[me, wallet, plan, llm],
        ):
            result = await ma._legacy_account_overview("Bearer tok")
        assert result["success"] is True
        assert result["user"]["username"] == "alice"
        assert result["wallet"]["balance"] == 100
        assert result["plan"] == "pro"
        assert result["llm"]["byok_configured_count"] == 1

    @pytest.mark.asyncio
    async def test_wallet_overview_error_falls_back_to_balance(self) -> None:
        me = {"user": {"id": 1}}
        wallet_err = {"__proxy_error__": True, "status_code": 404, "payload": {}}
        balance = {"balance": 50}
        plan = {}
        llm = {}
        with patch.object(
            ma,
            "_proxy_json",
            new_callable=AsyncMock,
            side_effect=[me, wallet_err, balance, plan, llm],
        ):
            result = await ma._legacy_account_overview("Bearer tok")
        assert result["success"] is True


class TestMarketBindMarketAuthToSession:
    """Cover ``bind_market_auth_to_session``."""

    def test_saves_token_to_session(self) -> None:
        req = MagicMock()
        req.cookies = {"session_id": "sid1"}
        req.headers = {}
        token, refresh = ma.bind_market_auth_to_session(
            req, {"token": "tok1", "refresh_token": "rtok1"}
        )
        assert token == "tok1"
        assert refresh == "rtok1"
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"

    def test_no_token_no_save(self) -> None:
        req = MagicMock()
        req.cookies = {"session_id": "sid1"}
        req.headers = {}
        token, refresh = ma.bind_market_auth_to_session(req, {})
        assert token == ""
        assert refresh == ""
        assert "sid1" not in ma._MARKET_SESSION_TOKENS

    def test_token_only_no_refresh(self) -> None:
        req = MagicMock()
        req.cookies = {"session_id": "sid1"}
        req.headers = {}
        token, refresh = ma.bind_market_auth_to_session(req, {"token": "tok1"})
        assert token == "tok1"
        assert refresh == ""


# ===========================================================================
# 2. app/services/skills/label_template_generator/label_template_generator.py
# ===========================================================================


def _make_test_image(path, width=600, height=400, color=(255, 255, 255)) -> str:
    """Create a small PNG image for testing."""
    img = Image.new("RGB", (width, height), color)
    img.save(path, format="PNG")
    return path


class TestLTGAnalyzeImage:
    """Cover ``analyze_image`` helper branches."""

    def test_analyze_image_valid_returns_success(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "a.png"), 500, 320)
        result = ltg.analyze_image(p)
        assert result["success"] is True
        assert result["format"] == "PNG"
        assert result["size"]["width"] == 500
        assert result["size"]["height"] == 320
        assert "colors" in result
        assert "sections" in result

    def test_analyze_image_verbose_adds_info(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "b.png"), 900, 600)
        result = ltg.analyze_image(p, verbose=True)
        assert result["success"] is True
        assert "additional_info" in result
        assert "dpi" in result["additional_info"]
        assert "has_transparency" in result["additional_info"]
        assert "estimated_font_sizes" in result["additional_info"]

    def test_analyze_image_file_not_found_returns_failure(self) -> None:
        result = ltg.analyze_image("/nonexistent/path/img.png")
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_analyze_image_rgba_has_transparency(self, tmp_path) -> None:
        img = Image.new("RGBA", (300, 200), (255, 0, 0, 128))
        p = str(tmp_path / "rgba.png")
        img.save(p, format="PNG")
        result = ltg.analyze_image(p, verbose=True)
        assert result["success"] is True
        assert result["additional_info"]["has_transparency"] is True

    def test_analyze_image_small_dimensions(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "small.png"), 100, 80)
        result = ltg.analyze_image(p)
        assert result["success"] is True
        assert len(result["sections"]) == 1
        assert result["sections"][0]["name"] == "main"

    def test_analyze_image_filename_extracted(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "my_label.png"), 500, 320)
        result = ltg.analyze_image(p)
        assert result["file"] == "my_label.png"


class TestLTGAnalyzeColors:
    """Cover ``_analyze_colors`` helper."""

    def test_analyze_colors_white_bg(self) -> None:
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        result = ltg._analyze_colors(img)
        assert result["background"] == "#ffffff"
        assert result["is_consistent_background"] is True

    def test_analyze_colors_black_bg(self) -> None:
        img = Image.new("RGB", (200, 200), (0, 0, 0))
        result = ltg._analyze_colors(img)
        assert result["background"] == "#000000"
        assert result["is_consistent_background"] is True

    def test_analyze_colors_inconsistent_bg(self) -> None:
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        # Draw a different color in one corner
        for x in range(20):
            for y in range(20):
                img.putpixel((x, y), (255, 0, 0))
        result = ltg._analyze_colors(img)
        # Corner (10,10) is now red, others are white
        assert result["is_consistent_background"] is False

    def test_analyze_colors_rgba_image(self) -> None:
        img = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
        result = ltg._analyze_colors(img)
        assert result["background"] == "#ff0000"

    def test_analyze_colors_returns_border_and_text(self) -> None:
        img = Image.new("RGB", (100, 100), (128, 128, 128))
        result = ltg._analyze_colors(img)
        assert result["border"] == "#000000"
        assert result["text"] == "#000000"


class TestLTGEstimateSections:
    """Cover ``_estimate_sections`` helper."""

    def test_estimate_sections_large_image(self) -> None:
        sections = ltg._estimate_sections(900, 600)
        assert len(sections) == 5
        names = [s["name"] for s in sections]
        assert "product_number" in names
        assert "footer" in names

    def test_estimate_sections_medium_image(self) -> None:
        sections = ltg._estimate_sections(500, 350)
        assert len(sections) == 3
        names = [s["name"] for s in sections]
        assert "header" in names
        assert "content" in names
        assert "footer" in names

    def test_estimate_sections_small_image(self) -> None:
        sections = ltg._estimate_sections(200, 150)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"
        assert sections[0]["y_end"] == 140

    def test_estimate_sections_boundary_800x500(self) -> None:
        sections = ltg._estimate_sections(800, 500)
        assert len(sections) == 5

    def test_estimate_sections_boundary_400x300(self) -> None:
        sections = ltg._estimate_sections(400, 300)
        assert len(sections) == 3

    def test_estimate_sections_below_boundary(self) -> None:
        sections = ltg._estimate_sections(399, 299)
        assert len(sections) == 1


class TestLTGEstimateFontSizes:
    """Cover ``_estimate_font_sizes`` helper."""

    def test_estimate_font_sizes_large_width(self) -> None:
        sizes = ltg._estimate_font_sizes(900, 600)
        assert sizes["title"] == 70
        assert sizes["label"] == 40
        assert sizes["content"] == 58
        assert sizes["small"] == 38

    def test_estimate_font_sizes_medium_width(self) -> None:
        sizes = ltg._estimate_font_sizes(500, 350)
        assert sizes["title"] == 40
        assert sizes["label"] == 24
        assert sizes["content"] == 32
        assert sizes["small"] == 20

    def test_estimate_font_sizes_small_width(self) -> None:
        sizes = ltg._estimate_font_sizes(300, 200)
        assert sizes["title"] == 24
        assert sizes["label"] == 14
        assert sizes["content"] == 18
        assert sizes["small"] == 12

    def test_estimate_font_sizes_boundary_800(self) -> None:
        sizes = ltg._estimate_font_sizes(800, 600)
        assert sizes["title"] == 70

    def test_estimate_font_sizes_boundary_400(self) -> None:
        sizes = ltg._estimate_font_sizes(400, 300)
        assert sizes["title"] == 40


class TestLTGClassifyField:
    """Cover ``_classify_field`` helper."""

    def test_classify_field_known_label(self) -> None:
        ftype, key = ltg._classify_field("品名")
        assert ftype == "fixed_label"
        assert key == "product_name"

    def test_classify_field_color(self) -> None:
        ftype, key = ltg._classify_field("颜色")
        assert ftype == "fixed_label"
        assert key == "color"

    def test_classify_field_price_suffix(self) -> None:
        ftype, key = ltg._classify_field("统一零售价")
        assert ftype == "fixed_label"
        assert key == "price"

    def test_classify_field_dynamic_label(self) -> None:
        ftype, key = ltg._classify_field("自定义字段")
        assert ftype == "dynamic"
        assert key == "自定义字段"

    def test_classify_field_empty_string(self) -> None:
        ftype, key = ltg._classify_field("")
        assert ftype == "dynamic"
        assert key == ""

    def test_classify_field_unknown_label(self) -> None:
        ftype, key = ltg._classify_field("未知")
        assert ftype == "dynamic"


class TestLTGIdentifyFields:
    """Cover ``_identify_fields`` helper."""

    def test_identify_fields_with_colon(self) -> None:
        blocks = [
            {
                "text": "品名：运动鞋",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = ltg._identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "品名"
        assert fields[0]["value"] == "运动鞋"
        assert fields[0]["type"] == "fixed_label"

    def test_identify_fields_with_chinese_colon(self) -> None:
        blocks = [
            {
                "text": "颜色:红色",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.8,
            }
        ]
        fields = ltg._identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "颜色"

    def test_identify_fields_no_colon_with_known_label(self) -> None:
        blocks = [
            {
                "text": "产品编号 6808AA",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.85,
            }
        ]
        fields = ltg._identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "产品编号"
        assert fields[0]["value"] == "6808AA"

    def test_identify_fields_empty_blocks(self) -> None:
        fields = ltg._identify_fields([])
        assert fields == []

    def test_identify_fields_no_match(self) -> None:
        blocks = [
            {
                "text": "随便一段文字",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.7,
            }
        ]
        fields = ltg._identify_fields(blocks)
        assert fields == []

    def test_identify_fields_multiple_blocks(self) -> None:
        blocks = [
            {
                "text": "品名：鞋",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            },
            {
                "text": "颜色：白",
                "left": 10,
                "top": 60,
                "width": 100,
                "height": 30,
                "conf": 0.85,
            },
        ]
        fields = ltg._identify_fields(blocks)
        assert len(fields) == 2


class TestLTGExtractFieldsByPattern:
    """Cover ``_extract_fields_by_pattern`` fallback helper."""

    def test_extract_fields_by_pattern_returns_list(self) -> None:
        fields = ltg._extract_fields_by_pattern("/some/path.png")
        assert isinstance(fields, list)
        assert len(fields) == 7

    def test_extract_fields_by_pattern_has_required_keys(self) -> None:
        fields = ltg._extract_fields_by_pattern("/some/path.png")
        for f in fields:
            assert "label" in f
            assert "value" in f
            assert "field_key" in f
            assert "type" in f

    def test_extract_fields_by_pattern_all_fixed_label(self) -> None:
        fields = ltg._extract_fields_by_pattern("/some/path.png")
        for f in fields:
            assert f["type"] == "fixed_label"

    def test_extract_fields_by_pattern_contains_product_name(self) -> None:
        fields = ltg._extract_fields_by_pattern("/some/path.png")
        labels = [f["label"] for f in fields]
        assert "品名" in labels

    def test_extract_fields_by_pattern_empty_path(self) -> None:
        fields = ltg._extract_fields_by_pattern("")
        assert len(fields) == 7


class TestLTGPairFieldsByGrid:
    """Cover ``_pair_fields_by_grid`` helper."""

    def test_pair_fields_empty_blocks_returns_empty(self) -> None:
        result = ltg._pair_fields_by_grid([], [0, 100], [0, 100])
        assert result == []

    def test_pair_fields_single_block_no_pair(self) -> None:
        blocks = [
            {
                "text": "品名",
                "center": (50, 50),
                "y_center": 50,
                "left": 10,
                "top": 20,
                "width": 80,
                "height": 30,
                "conf": 0.9,
            }
        ]
        result = ltg._pair_fields_by_grid(blocks, [0, 100], [0, 100])
        assert len(result) == 1
        assert result[0]["label"] == "品名"
        assert result[0]["value"] == ""

    def test_pair_fields_two_blocks_paired(self) -> None:
        blocks = [
            {
                "text": "品名",
                "center": (50, 50),
                "y_center": 50,
                "left": 10,
                "top": 20,
                "width": 80,
                "height": 30,
                "conf": 0.9,
            },
            {
                "text": "运动鞋",
                "center": (150, 50),
                "y_center": 50,
                "left": 110,
                "top": 20,
                "width": 80,
                "height": 30,
                "conf": 0.85,
            },
        ]
        result = ltg._pair_fields_by_grid(blocks, [0, 100], [0, 100, 200])
        assert len(result) == 1
        assert result[0]["label"] == "品名"
        assert result[0]["value"] == "运动鞋"

    def test_pair_fields_with_merged_cells(self) -> None:
        blocks = [
            {
                "text": "品名",
                "center": (50, 50),
                "y_center": 50,
                "left": 10,
                "top": 20,
                "width": 80,
                "height": 30,
                "conf": 0.9,
            }
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = ltg._pair_fields_by_grid(blocks, [0, 100], [0, 100, 200], merged)
        assert len(result) == 1
        assert result[0]["is_merged"] is True

    def test_pair_fields_none_merged_defaults_empty(self) -> None:
        blocks = [
            {
                "text": "test",
                "center": (50, 50),
                "y_center": 50,
                "left": 10,
                "top": 20,
                "width": 80,
                "height": 30,
                "conf": 0.9,
            }
        ]
        result = ltg._pair_fields_by_grid(blocks, [0, 100], [0, 100])
        assert len(result) == 1
        assert result[0]["is_merged"] is False


class TestLTGGenerateTemplateCode:
    """Cover ``generate_template_code`` and code generators."""

    def test_generate_template_code_basic(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "tpl.png"), 500, 350)
        code = ltg.generate_template_code(p)
        assert "class LabelTemplateGenerator" in code
        assert "def generate_label" in code

    def test_generate_template_code_with_ocr_result(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "tpl2.png"), 500, 350)
        ocr_result = {
            "success": True,
            "fields": [
                {
                    "label": "品名",
                    "value": "鞋",
                    "field_key": "product_name",
                    "type": "fixed_label",
                }
            ],
        }
        code = ltg.generate_template_code(p, ocr_result=ocr_result)
        assert "product_name" in code
        assert "品名" in code

    def test_generate_template_code_invalid_path_returns_error(self) -> None:
        code = ltg.generate_template_code("/nonexistent.png")
        assert code.startswith("# Error")

    def test_generate_template_code_custom_class_name(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "tpl3.png"), 500, 350)
        code = ltg.generate_template_code(p, class_name="MyCustomLabel")
        assert "class MyCustomLabel" in code

    def test_generate_basic_code_returns_string(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "basic.png"), 500, 350)
        code = ltg._generate_basic_code(
            p,
            "MyClass",
            500,
            350,
            {"background": "#ffffff", "border": "#000000", "text": "#000000"},
        )
        assert "class MyClass" in code
        assert "def generate_label" in code

    def test_generate_code_with_fields_returns_string(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "fields.png"), 500, 350)
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"}
        ]
        code = ltg._generate_code_with_fields(p, "MyClass", 500, 350, colors, fields)
        assert "product_name" in code
        assert "品名" in code


class TestLTGSkillExecute:
    """Cover ``LabelTemplateGeneratorSkill.execute``."""

    def test_skill_execute_success_no_ocr(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "skill.png"), 500, 350)
        skill = ltg.LabelTemplateGeneratorSkill()
        result = skill.execute(p, enable_ocr=False)
        assert result["success"] is True
        assert "code" in result
        assert "analysis" in result

    def test_skill_execute_invalid_path_returns_failure(self) -> None:
        skill = ltg.LabelTemplateGeneratorSkill()
        result = skill.execute("/nonexistent.png", enable_ocr=False)
        assert result["success"] is False

    def test_skill_execute_with_output_file(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "skill2.png"), 500, 350)
        out_file = str(tmp_path / "out.py")
        skill = ltg.LabelTemplateGeneratorSkill()
        result = skill.execute(p, enable_ocr=False, output_file=out_file)
        assert result["success"] is True
        assert result.get("output_file") == out_file

    def test_skill_execute_with_ocr_import_error(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "skill3.png"), 500, 350)
        skill = ltg.LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr"
        ) as mock_ocr:
            mock_ocr.return_value = {
                "success": False,
                "message": "缺少图像处理依赖",
                "fallback_fields": [],
            }
            result = skill.execute(p, enable_ocr=True)
            assert result["success"] is True
            assert result["ocr_result"]["success"] is False

    def test_skill_execute_verbose(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "skill4.png"), 500, 350)
        skill = ltg.LabelTemplateGeneratorSkill()
        result = skill.execute(p, enable_ocr=False, verbose=True)
        assert result["success"] is True

    def test_skill_info_returns_dict(self) -> None:
        skill = ltg.LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["name"] == "label_template_generator"
        assert "description" in info
        assert "parameters" in info
        assert "image_path" in info["parameters"]


class TestLTGGetSkillSingleton:
    """Cover ``get_label_template_generator_skill`` singleton."""

    def test_get_skill_returns_instance(self) -> None:
        ltg._skill_instance = None
        skill = ltg.get_label_template_generator_skill()
        assert isinstance(skill, ltg.LabelTemplateGeneratorSkill)

    def test_get_skill_returns_same_instance(self) -> None:
        ltg._skill_instance = None
        skill1 = ltg.get_label_template_generator_skill()
        skill2 = ltg.get_label_template_generator_skill()
        assert skill1 is skill2

    def test_get_skill_after_explicit_set(self) -> None:
        custom = ltg.LabelTemplateGeneratorSkill()
        ltg._skill_instance = custom
        assert ltg.get_label_template_generator_skill() is custom
        ltg._skill_instance = None


class TestLTGExtractTextWithOcr:
    """Cover ``extract_text_with_ocr`` error paths."""

    def test_extract_text_with_ocr_file_not_found(self) -> None:
        result = ltg.extract_text_with_ocr("/nonexistent.png")
        # Either FileNotFoundError path or ImportError path
        assert result["success"] is False
        assert "fallback_fields" in result

    def test_extract_text_with_ocr_import_error(self, tmp_path) -> None:
        p = _make_test_image(str(tmp_path / "ocr.png"), 200, 200)
        # Force ImportError by making cv2 import fail
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("no cv2")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = ltg.extract_text_with_ocr(p)
            assert result["success"] is False
            assert "fallback_fields" in result


# ===========================================================================
# 3. app/services/tools_workflow_registered.py
# ===========================================================================


class TestTWRNormalSlotDispatch:
    """Cover ``_registered_router_normal_slot_dispatch``."""

    def test_normal_slot_dispatch_product_query(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message"
        ) as mock:
            mock.return_value = {"success": True, "data": []}
            result = twr._registered_router_normal_slot_dispatch(
                "product_query", {"message": "查询鞋子"}, {}, "normal", "查询鞋子"
            )
            assert result["success"] is True
            mock.assert_called_once_with("查询鞋子")

    def test_normal_slot_dispatch_product_query_uses_user_message(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message"
        ) as mock:
            mock.return_value = {"success": True}
            twr._registered_router_normal_slot_dispatch(
                "product_query", {}, {}, "normal", "user msg"
            )
            mock.assert_called_once_with("user msg")

    def test_normal_slot_dispatch_shipment_preview(self) -> None:
        with patch("app.application.normal_chat_dispatch.run_normal_slot_shipment_preview") as mock:
            mock.return_value = {"success": True}
            result = twr._registered_router_normal_slot_dispatch(
                "shipment_preview", {"order_text": "订单1"}, {}, "normal", ""
            )
            assert result["success"] is True
            mock.assert_called_once_with("订单1")

    def test_normal_slot_dispatch_shipment_preview_fallback_user_message(self) -> None:
        with patch("app.application.normal_chat_dispatch.run_normal_slot_shipment_preview") as mock:
            mock.return_value = {"success": True}
            twr._registered_router_normal_slot_dispatch(
                "shipment_preview", {}, {}, "normal", "fallback order"
            )
            mock.assert_called_once_with("fallback order")

    def test_normal_slot_dispatch_unknown_action(self) -> None:
        result = twr._registered_router_normal_slot_dispatch("unknown", {}, {}, "normal", "")
        assert result["success"] is False
        assert "未注册" in result["message"]

    def test_normal_slot_dispatch_empty_params(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message"
        ) as mock:
            mock.return_value = {"success": True}
            twr._registered_router_normal_slot_dispatch("product_query", {}, {}, "normal", "")
            mock.assert_called_once_with("")


class TestTWRCustomers:
    """Cover ``_registered_router_customers``."""

    def test_customers_query_with_keyword(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            svc.get_all.return_value = {"success": True, "data": [{"id": 1}]}
            mock_get.return_value = svc
            result = twr._registered_router_customers("query", {"keyword": "abc"}, {}, "normal", "")
            assert result["success"] is True
            assert result["data"] == [{"id": 1}]

    def test_customers_query_with_unit_name(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            svc.get_all.return_value = {"success": True, "data": []}
            mock_get.return_value = svc
            twr._registered_router_customers("query", {"unit_name": "unit1"}, {}, "normal", "")
            svc.get_all.assert_called_once_with(keyword="unit1", page=1, per_page=20)

    def test_customers_ensure_exists_no_unit_name(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_customers("ensure_exists", {}, {}, "normal", "")
            assert result["success"] is False
            assert "缺少 unit_name" in result["message"]

    def test_customers_ensure_exists_matched(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            matched = MagicMock()
            matched.unit_name = "matched_unit"
            svc.match_purchase_unit.return_value = matched
            mock_get.return_value = svc
            result = twr._registered_router_customers(
                "ensure_exists", {"unit_name": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_customers_ensure_exists_create_new(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            svc.match_purchase_unit.return_value = None
            svc.create.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_customers(
                "ensure_exists", {"unit_name": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["created"] is True

    def test_customers_ensure_exists_create_already_exists(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            svc.match_purchase_unit.return_value = None
            svc.create.return_value = {"success": False, "message": "已存在"}
            mock_get.return_value = svc
            result = twr._registered_router_customers(
                "ensure_exists", {"unit_name": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_customers_create_success(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            svc.create.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_customers(
                "create", {"unit_name": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["created"] is True

    def test_customers_create_no_unit_name(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_customers("create", {}, {}, "normal", "")
            assert result["success"] is False


class TestTWRProducts:
    """Cover ``_registered_router_products``."""

    def test_products_query_normal_profile(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_workflow_products_query_normal_profile"
        ) as mock:
            mock.return_value = {"success": True}
            result = twr._registered_router_products("query", {}, {}, "normal", "user msg")
            assert result["success"] is True

    def test_products_query_non_normal_profile(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = svc
            result = twr._registered_router_products(
                "query", {"unit_name": "u1"}, {}, "advanced", ""
            )
            assert result["success"] is True

    def test_products_exists_match_by_model(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            svc.get_products.return_value = {
                "success": True,
                "data": [{"name": "n", "model_number": "M01"}],
            }
            mock_get.return_value = svc
            result = twr._registered_router_products(
                "exists", {"model_number": "m01", "unit_name": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_products_exists_match_by_name(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            svc.get_products.return_value = {
                "success": True,
                "data": [{"name": "prod1", "model_number": ""}],
            }
            mock_get.return_value = svc
            result = twr._registered_router_products(
                "exists", {"product_name": "prod1", "unit_name": "u1"}, {}, "normal", ""
            )
            assert result["exists"] is True

    def test_products_exists_no_match(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = svc
            result = twr._registered_router_products(
                "exists", {"model_number": "X"}, {}, "normal", ""
            )
            assert result["exists"] is False

    def test_products_create_missing_params(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_products("create", {}, {}, "normal", "")
            assert result["success"] is False

    def test_products_create_success(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            svc.create_product.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_products(
                "create",
                {"name_or_model": "prod", "unit_name": "u1", "unit_price": "10.5"},
                {},
                "normal",
                "",
            )
            assert result["success"] is True

    def test_products_create_invalid_price_defaults_zero(self) -> None:
        with patch("app.services.get_products_service") as mock_get:
            svc = MagicMock()
            svc.create_product.return_value = {"success": True}
            mock_get.return_value = svc
            twr._registered_router_products(
                "create",
                {"name_or_model": "prod", "unit_name": "u1", "unit_price": "invalid"},
                {},
                "normal",
                "",
            )
            args, kwargs = svc.create_product.call_args
            assert (
                kwargs["unit_price"] == 0.0
                if "unit_price" in kwargs
                else args[0]["unit_price"] == 0.0
            )


class TestTWRMaterials:
    """Cover ``_registered_router_materials``."""

    def test_materials_list(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.get_all_materials.return_value = {"success": True, "data": []}
            mock_get.return_value = svc
            result = twr._registered_router_materials("list", {}, {}, "normal", "")
            assert result["success"] is True

    def test_materials_query_alias(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.get_all_materials.return_value = {"success": True}
            mock_get.return_value = svc
            twr._registered_router_materials("query", {}, {}, "normal", "")
            svc.get_all_materials.assert_called_once()

    def test_materials_create(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.create_material.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_materials("create", {"name": "mat1"}, {}, "normal", "")
            assert result["success"] is True

    def test_materials_create_with_material_name(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.create_material.return_value = {"success": True}
            mock_get.return_value = svc
            twr._registered_router_materials("create", {"material_name": "mat2"}, {}, "normal", "")
            args, _ = svc.create_material.call_args
            assert args[0]["name"] == "mat2"

    def test_materials_update(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.update_material.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_materials(
                "update", {"id": "1", "name": "new"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_materials_delete(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.delete_material.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_materials("delete", {"id": "1"}, {}, "normal", "")
            assert result["success"] is True

    def test_materials_batch_delete(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.batch_delete_materials.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_materials(
                "batch_delete", {"ids": ["1", "2"]}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_materials_export(self) -> None:
        with patch("app.application.get_material_application_service") as mock_get:
            svc = MagicMock()
            svc.export_to_excel.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_materials("export", {"search": "abc"}, {}, "normal", "")
            assert result["success"] is True


class TestTWRShipmentRecords:
    """Cover ``_registered_router_shipment_records``."""

    def test_shipment_records_list(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            svc = MagicMock()
            svc.get_shipment_records.return_value = []
            mock_get.return_value = svc
            result = twr._registered_router_shipment_records(
                "list", {"unit": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_shipment_records_list_no_unit(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            svc = MagicMock()
            svc.get_shipment_records.return_value = []
            mock_get.return_value = svc
            twr._registered_router_shipment_records("list", {}, {}, "normal", "")
            svc.get_shipment_records.assert_called_once_with(None)

    def test_shipment_records_update(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            svc = MagicMock()
            svc.update_shipment_record.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_shipment_records(
                "update", {"id": "1", "status": "done"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_shipment_records_delete(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            svc = MagicMock()
            svc.delete_shipment_record.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_shipment_records(
                "delete", {"id": "1"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_shipment_records_export(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            svc = MagicMock()
            svc.export_shipment_records.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_shipment_records(
                "export", {"unit": "u1"}, {}, "normal", ""
            )
            assert result["success"] is True


class TestTWRBusinessDocking:
    """Cover ``_registered_router_business_docking_family``."""

    def test_business_docking_view_action(self) -> None:
        result = twr._registered_router_business_docking_family("view", {}, {}, "normal", "")
        assert result["success"] is True
        assert "redirect" in result

    def test_business_docking_no_file_path(self) -> None:
        result = twr._registered_router_business_docking_family("analyze", {}, {}, "normal", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_business_docking_file_not_exists(self) -> None:
        result = twr._registered_router_business_docking_family(
            "analyze", {"file_path": "/nonexistent.xlsx"}, {}, "normal", ""
        )
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_business_docking_with_existing_file(self, tmp_path) -> None:
        f = tmp_path / "test.xlsx"
        f.write_bytes(b"fake")
        with (
            patch(
                "app.services.document_templates_service._extract_structured_excel_preview"
            ) as mock_struct,
            patch(
                "app.services.document_templates_service._extract_excel_grid_preview"
            ) as mock_grid,
            patch(
                "app.services.document_templates_service._extract_excel_grid_style_cache"
            ) as mock_style,
            patch(
                "app.services.document_templates_service._extract_excel_all_sheets_preview"
            ) as mock_all,
            patch("app.services.document_templates_service._list_excel_sheet_names") as mock_names,
        ):
            mock_struct.return_value = {"fields": [], "sample_rows": []}
            mock_grid.return_value = {}
            mock_style.return_value = {}
            mock_all.return_value = []
            mock_names.return_value = ["Sheet1"]
            result = twr._registered_router_business_docking_family(
                "analyze", {"file_path": str(f)}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["sheet_names"] == ["Sheet1"]


class TestTWRWechat:
    """Cover ``_registered_router_wechat``."""

    def test_wechat_view(self) -> None:
        with patch("app.application.get_wechat_contact_app_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_wechat("view", {}, {}, "normal", "")
            assert result["success"] is True
            assert "redirect" in result

    def test_wechat_list(self) -> None:
        with patch("app.application.get_wechat_contact_app_service") as mock_get:
            svc = MagicMock()
            svc.get_contacts.return_value = []
            mock_get.return_value = svc
            result = twr._registered_router_wechat("list", {}, {}, "normal", "")
            assert result["success"] is True

    def test_wechat_query_alias(self) -> None:
        with patch("app.application.get_wechat_contact_app_service") as mock_get:
            svc = MagicMock()
            svc.get_contacts.return_value = []
            mock_get.return_value = svc
            twr._registered_router_wechat("query", {}, {}, "normal", "")
            svc.get_contacts.assert_called_once()

    def test_wechat_refresh_contact_cache(self) -> None:
        with patch(
            "app.services.wechat_contact_cache_import.ensure_decrypted_wechat_dbs"
        ) as mock_ensure:
            mock_ensure.return_value = {"success": True}
            result = twr._registered_router_wechat("refresh_contact_cache", {}, {}, "normal", "")
            assert result["success"] is True

    def test_wechat_refresh_messages_cache(self) -> None:
        with patch(
            "app.services.wechat_contact_cache_import.ensure_decrypted_wechat_dbs"
        ) as mock_ensure:
            mock_ensure.return_value = {"success": True}
            result = twr._registered_router_wechat("refresh_messages_cache", {}, {}, "normal", "")
            assert result["success"] is True


class TestTWRPrint:
    """Cover ``_registered_router_print``."""

    def test_print_view(self) -> None:
        with patch("app.services.get_printer_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_print("view", {}, {}, "normal", "")
            assert result["success"] is True

    def test_print_list(self) -> None:
        with patch("app.services.get_printer_service") as mock_get:
            svc = MagicMock()
            svc.get_printers.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_print("list", {}, {}, "normal", "")
            assert result["success"] is True

    def test_print_label(self) -> None:
        with patch("app.services.get_printer_service") as mock_get:
            svc = MagicMock()
            svc.print_label.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_print(
                "print_label", {"file_path": "/tmp/l.pdf", "copies": 2}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_print_document(self) -> None:
        with patch("app.services.get_printer_service") as mock_get:
            svc = MagicMock()
            svc.print_document.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_print(
                "print_document",
                {"file_path": "/tmp/d.pdf", "use_automation": True},
                {},
                "normal",
                "",
            )
            assert result["success"] is True

    def test_print_test(self) -> None:
        with patch("app.services.get_printer_service") as mock_get:
            svc = MagicMock()
            svc.test_printer.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_print("test", {"printer_name": "P1"}, {}, "normal", "")
            assert result["success"] is True


class TestTWRPrinterList:
    """Cover ``_registered_router_printer_list``."""

    def test_printer_list_view(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_printer_list("view", {}, {}, "normal", "")
            assert result["success"] is True

    def test_printer_list_list(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.get_printer_config.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_printer_list("list", {}, {}, "normal", "")
            assert result["success"] is True

    def test_printer_list_set_default(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.set_default_printer.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_printer_list(
                "set_default", {"printer_name": "P1"}, {}, "normal", ""
            )
            assert result["success"] is True


class TestTWRSettings:
    """Cover ``_registered_router_settings``."""

    def test_settings_view(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            mock_get.return_value = svc
            result = twr._registered_router_settings("view", {}, {}, "normal", "")
            assert result["success"] is True

    def test_settings_query(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.get_system_info.return_value = {"os": "test"}
            mock_get.return_value = svc
            result = twr._registered_router_settings("query", {}, {}, "normal", "")
            assert result["success"] is True

    def test_settings_get_system_info_alias(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.get_system_info.return_value = {"os": "test"}
            mock_get.return_value = svc
            result = twr._registered_router_settings("get_system_info", {}, {}, "normal", "")
            assert result["success"] is True

    def test_settings_get_startup_config(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.get_startup_config.return_value = {"enabled": False}
            mock_get.return_value = svc
            result = twr._registered_router_settings("get_startup_config", {}, {}, "normal", "")
            assert result["success"] is True

    def test_settings_enable_startup(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.enable_startup.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_settings("enable_startup", {}, {}, "normal", "")
            assert result["success"] is True

    def test_settings_disable_startup(self) -> None:
        with patch("app.services.get_system_service") as mock_get:
            svc = MagicMock()
            svc.disable_startup.return_value = {"success": True}
            mock_get.return_value = svc
            result = twr._registered_router_settings("disable_startup", {}, {}, "normal", "")
            assert result["success"] is True


class TestTWRExcelAnalysis:
    """Cover ``_registered_router_excel_analysis``."""

    def test_excel_analysis_no_file_path(self) -> None:
        result = twr._registered_router_excel_analysis("read", {}, {}, "normal", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_excel_analysis_file_path_from_runtime_context(self) -> None:
        with (
            patch(
                "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill"
            ) as mock_toolkit,
            patch(
                "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill"
            ) as mock_analyzer,
        ):
            tk = MagicMock()
            tk.execute.return_value = {"success": True, "content": []}
            mock_toolkit.return_value = tk
            mock_analyzer.return_value = MagicMock()
            result = twr._registered_router_excel_analysis(
                "read",
                {},
                {"excel_analysis": {"file_path": "/tmp/x.xlsx"}},
                "normal",
                "",
            )
            assert result["success"] is True

    def test_excel_analysis_file_path_from_last_context(self) -> None:
        with (
            patch(
                "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill"
            ) as mock_toolkit,
            patch(
                "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill"
            ) as mock_analyzer,
        ):
            tk = MagicMock()
            tk.execute.return_value = {"success": True, "content": []}
            mock_toolkit.return_value = tk
            mock_analyzer.return_value = MagicMock()
            result = twr._registered_router_excel_analysis(
                "read",
                {},
                {"last_excel_analysis_context": {"result": {"file_path": "/tmp/x.xlsx"}}},
                "normal",
                "",
            )
            assert result["success"] is True

    def test_excel_analysis_unknown_action(self) -> None:
        result = twr._registered_router_excel_analysis(
            "unknown",
            {"file_path": "/tmp/x.xlsx"},
            {},
            "normal",
            "",
        )
        assert result["success"] is False
        assert "未知" in result["message"]

    def test_excel_analysis_import_error(self) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "excel_template_analyzer" in name:
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = twr._registered_router_excel_analysis(
                "read", {"file_path": "/tmp/x.xlsx"}, {}, "normal", ""
            )
            assert result["success"] is False
            assert "Excel Skill" in result["message"]


class TestTWRExcelImport:
    """Cover ``_registered_router_excel_import``."""

    def test_excel_import_unknown_action(self) -> None:
        result = twr._registered_router_excel_import("unknown", {}, {}, "normal", "")
        assert result["success"] is False

    def test_excel_import_no_pending_id(self) -> None:
        result = twr._registered_router_excel_import("execute_import", {}, {}, "normal", "")
        assert result["success"] is False
        assert "pending_import_id" in result["message"]

    def test_excel_import_not_found(self) -> None:
        with patch("app.application.get_ai_chat_app_service") as mock_get:
            svc = MagicMock()
            svc._pending_excel_imports = {}
            mock_get.return_value = svc
            result = twr._registered_router_excel_import(
                "execute_import", {"pending_import_id": "x"}, {}, "normal", ""
            )
            assert result["success"] is False
            assert "未找到" in result["message"]

    def test_excel_import_no_records(self) -> None:
        with patch("app.application.get_ai_chat_app_service") as mock_get:
            svc = MagicMock()
            svc._pending_excel_imports = {"x": {"records": []}}
            mock_get.return_value = svc
            result = twr._registered_router_excel_import(
                "execute_import", {"pending_import_id": "x"}, {}, "normal", ""
            )
            assert result["success"] is False
            assert "没有可导入" in result["message"]


class TestTWRExecuteRegisteredWorkflowTool:
    """Cover ``execute_registered_workflow_tool`` dispatcher."""

    def test_execute_unknown_tool(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile"
        ) as mock_profile:
            mock_profile.return_value = "normal"
            result = twr.execute_registered_workflow_tool(
                "unknown_tool", "action", {"_runtime_context": {}}
            )
            assert result["success"] is False
            assert "未注册" in result["message"]

    def test_execute_with_runtime_context(self) -> None:
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile"
            ) as mock_profile,
            patch(
                "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message"
            ) as mock_query,
        ):
            mock_profile.return_value = "normal"
            mock_query.return_value = {"success": True}
            result = twr.execute_registered_workflow_tool(
                "normal_slot_dispatch",
                "product_query",
                {"_runtime_context": {"message": "hi"}},
            )
            assert result["success"] is True

    def test_execute_none_params_defaults_empty(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile"
        ) as mock_profile:
            mock_profile.return_value = "normal"
            result = twr.execute_registered_workflow_tool("normal_slot_dispatch", "unknown", None)
            assert result["success"] is False

    def test_execute_registered_router_dict_contains_keys(self) -> None:
        expected_keys = {
            "normal_slot_dispatch",
            "customers",
            "products",
            "materials",
            "shipment_records",
            "shipment_orders",
            "business_docking",
            "business_event",
            "template_extract",
            "template_preview",
            "document_template",
            "label_template_generator",
            "wechat",
            "print",
            "printer_list",
            "settings",
            "excel_analysis",
            "excel_analyzer",
            "excel_toolkit",
            "excel_import",
            "excel_vector_index",
            "generate_office_document",
            "unit_products_import",
            "inventory",
            "purchase",
            "finance",
            "ocr",
            "dataset_rag",
            "memory_v2",
            "system_maintenance",
        }
        assert set(twr._REGISTERED_WORKFLOW_ROUTERS.keys()) == expected_keys


# ===========================================================================
# 4. app/fastapi_routes/mod_store_routes.py
# ===========================================================================


class TestMSIsExtensionRow:
    """Cover ``_is_extension_row`` helper."""

    def test_is_extension_row_valid_id(self) -> None:
        assert msr._is_extension_row({"id": "mod1", "type": "mod"}) is True

    def test_is_extension_row_empty_id(self) -> None:
        assert msr._is_extension_row({"id": "", "type": "mod"}) is False

    def test_is_extension_row_all_id(self) -> None:
        assert msr._is_extension_row({"id": "all", "type": "mod"}) is False

    def test_is_extension_row_category_type(self) -> None:
        assert msr._is_extension_row({"id": "x", "type": "category"}) is False

    def test_is_extension_row_template_type(self) -> None:
        assert msr._is_extension_row({"id": "x", "type": "template"}) is False

    def test_is_extension_row_shell_seed_type(self) -> None:
        assert msr._is_extension_row({"id": "x", "type": "shell_seed"}) is False

    def test_is_extension_row_default_type(self) -> None:
        assert msr._is_extension_row({"id": "x"}) is True

    def test_is_extension_row_none_id(self) -> None:
        assert msr._is_extension_row({"id": None, "type": "mod"}) is False


class TestMSItemToModInfo:
    """Cover ``_item_to_mod_info`` helper."""

    def test_item_to_mod_info_full_data(self) -> None:
        d = {"id": "m1", "name": "Mod1", "version": "2.0.0", "author": "A", "description": "desc"}
        info = msr._item_to_mod_info(d)
        assert info["id"] == "m1"
        assert info["name"] == "Mod1"
        assert info["version"] == "2.0.0"
        assert info["author"] == "A"
        assert info["description"] == "desc"
        assert info["is_installed"] is True
        assert info["source"] == "local"

    def test_item_to_mod_info_empty_data(self) -> None:
        info = msr._item_to_mod_info({})
        assert info["id"] == ""
        assert info["name"] == "未命名"
        assert info["version"] == "1.0.0"
        assert info["author"] == "—"

    def test_item_to_mod_info_only_id(self) -> None:
        info = msr._item_to_mod_info({"id": "x"})
        assert info["id"] == "x"
        assert info["name"] == "x"

    def test_item_to_mod_info_category_not_installed(self) -> None:
        info = msr._item_to_mod_info({"id": "x", "type": "category"})
        assert info["is_installed"] is False

    def test_item_to_mod_info_default_values(self) -> None:
        info = msr._item_to_mod_info({"id": "x", "type": "mod"})
        assert info["download_count"] == 0
        assert info["avg_rating"] == 0.0
        assert info["rating_count"] == 0
        assert info["dependencies"] == {}


class TestMSSafeText:
    """Cover ``_safe_text`` helper."""

    def test_safe_text_string(self) -> None:
        assert msr._safe_text("hello") == "hello"

    def test_safe_text_strips_whitespace(self) -> None:
        assert msr._safe_text("  hi  ") == "hi"

    def test_safe_text_none(self) -> None:
        assert msr._safe_text(None) == ""

    def test_safe_text_int(self) -> None:
        assert msr._safe_text(42) == "42"

    def test_safe_text_empty_string(self) -> None:
        assert msr._safe_text("") == ""


class TestMSSplitPackageFile:
    """Cover ``_split_package_file`` helper."""

    def test_split_package_file_with_colon(self) -> None:
        mid, ver = msr._split_package_file("mod1:1.0.0")
        assert mid == "mod1"
        assert ver == "1.0.0"

    def test_split_package_file_no_colon(self) -> None:
        mid, ver = msr._split_package_file("mod1")
        assert mid == "mod1"
        assert ver == ""

    def test_split_package_file_empty(self) -> None:
        mid, ver = msr._split_package_file("")
        assert mid == ""
        assert ver == ""

    def test_split_package_file_strips_whitespace(self) -> None:
        mid, ver = msr._split_package_file("  mod1 : 1.0  ")
        assert mid == "mod1"
        assert ver == "1.0"

    def test_split_package_file_none(self) -> None:
        mid, ver = msr._split_package_file(None)
        assert mid == ""
        assert ver == ""


class TestMSFilterRows:
    """Cover ``_filter_rows`` helper."""

    def test_filter_rows_no_filter(self) -> None:
        rows = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
        result = msr._filter_rows(rows)
        assert len(result) == 2

    def test_filter_rows_by_query_name(self) -> None:
        rows = [{"id": "1", "name": "Alpha"}, {"id": "2", "name": "Beta"}]
        result = msr._filter_rows(rows, q="alpha")
        assert len(result) == 1
        assert result[0]["name"] == "Alpha"

    def test_filter_rows_by_query_id(self) -> None:
        rows = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
        result = msr._filter_rows(rows, q="2")
        assert len(result) == 1

    def test_filter_rows_by_query_description(self) -> None:
        rows = [{"id": "1", "name": "A", "description": "special"}]
        result = msr._filter_rows(rows, q="special")
        assert len(result) == 1

    def test_filter_rows_by_author(self) -> None:
        rows = [{"id": "1", "author": "John"}, {"id": "2", "author": "Jane"}]
        result = msr._filter_rows(rows, author="john")
        assert len(result) == 1

    def test_filter_rows_installed_true(self) -> None:
        rows = [{"id": "1", "is_installed": True}, {"id": "2", "is_installed": False}]
        result = msr._filter_rows(rows, installed=True)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_filter_rows_installed_false(self) -> None:
        rows = [{"id": "1", "is_installed": True}, {"id": "2", "is_installed": False}]
        result = msr._filter_rows(rows, installed=False)
        assert len(result) == 1
        assert result[0]["id"] == "2"

    def test_filter_rows_empty_rows(self) -> None:
        result = msr._filter_rows([], q="test")
        assert result == []

    def test_filter_rows_empty_query(self) -> None:
        rows = [{"id": "1", "name": "A"}]
        result = msr._filter_rows(rows, q="")
        assert len(result) == 1


class TestMSAllRows:
    """Cover ``_all_rows`` helper."""

    def test_all_rows_returns_list(self) -> None:
        with patch("app.fastapi_routes.mod_store_routes.list_mod_items") as mock_list:
            mock_list.return_value = []
            result = msr._all_rows()
            assert result == []

    def test_all_rows_handles_exception(self) -> None:
        with patch("app.fastapi_routes.mod_store_routes.list_mod_items") as mock_list:
            mock_list.side_effect = RuntimeError("fail")
            result = msr._all_rows()
            assert result == []

    def test_all_rows_maps_items(self) -> None:
        with patch("app.fastapi_routes.mod_store_routes.list_mod_items") as mock_list:
            item = MagicMock()
            item.model_dump.return_value = {"id": "m1", "name": "Mod1", "type": "mod"}
            mock_list.return_value = [item]
            result = msr._all_rows()
            assert len(result) == 1
            assert result[0]["id"] == "m1"


class TestMSInstalledById:
    """Cover ``_installed_by_id`` helper."""

    def test_installed_by_id_filters_installed(self) -> None:
        with patch("app.fastapi_routes.mod_store_routes.list_mod_items") as mock_list:
            item1 = MagicMock()
            item1.model_dump.return_value = {"id": "m1", "name": "A", "type": "mod"}
            item2 = MagicMock()
            item2.model_dump.return_value = {"id": "cat1", "name": "B", "type": "category"}
            mock_list.return_value = [item1, item2]
            result = msr._installed_by_id()
            assert "m1" in result
            assert "cat1" not in result

    def test_installed_by_id_empty(self) -> None:
        with patch("app.fastapi_routes.mod_store_routes.list_mod_items") as mock_list:
            mock_list.return_value = []
            result = msr._installed_by_id()
            assert result == {}


class TestMSRemoteToModInfo:
    """Cover ``_remote_to_mod_info`` helper."""

    def test_remote_to_mod_info_full(self) -> None:
        d = {
            "id": "r1",
            "name": "Remote1",
            "version": "1.0.0",
            "author": "Author",
            "description": "desc",
            "download_url": "/dl",
            "download_count": 5,
            "avg_rating": 4.5,
            "rating_count": 10,
        }
        with patch("app.mod_sdk.host_foundation.catalog_store_collection") as mock_cat:
            mock_cat.return_value = "default_collection"
            info = msr._remote_to_mod_info(d, set())
            assert info["id"] == "r1"
            assert info["name"] == "Remote1"
            assert info["is_installed"] is False
            assert info["source"] == "remote"

    def test_remote_to_mod_info_installed(self) -> None:
        with patch("app.mod_sdk.host_foundation.catalog_store_collection") as mock_cat:
            mock_cat.return_value = "col"
            info = msr._remote_to_mod_info({"id": "r1"}, {"r1"})
            assert info["is_installed"] is True

    def test_remote_to_mod_info_empty(self) -> None:
        with patch("app.mod_sdk.host_foundation.catalog_store_collection") as mock_cat:
            mock_cat.return_value = "col"
            info = msr._remote_to_mod_info({}, set())
            assert info["id"] == ""
            assert info["name"] == "未命名"

    def test_remote_to_mod_info_with_commerce(self) -> None:
        d = {"id": "r1", "commerce": {"seller": "Seller1", "collection": "col1"}}
        with patch("app.mod_sdk.host_foundation.catalog_store_collection") as mock_cat:
            mock_cat.return_value = "col"
            info = msr._remote_to_mod_info(d, set())
            assert info["author"] == "Seller1"
            assert info["commerce"]["collection"] == "col1"


class TestMSRoutesBasic:
    """Cover simple route endpoints."""

    def test_upload_route_returns_not_implemented(self, mod_store_client) -> None:
        resp = mod_store_client.post("/upload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "上传" in data["detail"]

    def test_validate_route_returns_not_implemented(self, mod_store_client) -> None:
        resp = mod_store_client.get("/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_updates_route_returns_empty(self, mod_store_client) -> None:
        resp = mod_store_client.get("/updates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["count"] == 0

    def test_dependencies_route_returns_empty(self, mod_store_client) -> None:
        resp = mod_store_client.get("/dependencies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["can_install"] is True

    def test_rate_route_returns_not_implemented(self, mod_store_client) -> None:
        resp = mod_store_client.post("/mod/m1/rate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_download_route_returns_404(self, mod_store_client) -> None:
        resp = mod_store_client.get("/package/m1:1.0.0/download")
        assert resp.status_code == 404

    def test_delete_package_route_returns_not_implemented(self, mod_store_client) -> None:
        resp = mod_store_client.delete("/package/m1:1.0.0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_rebuild_index_route_returns_success(self, mod_store_client) -> None:
        resp = mod_store_client.post("/index/rebuild")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "无需重建" in data["message"]


class TestMSRoutesWithData:
    """Cover routes that need data mocking."""

    def test_catalog_route_returns_data(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows", new_callable=AsyncMock
        ) as mock_combined:
            mock_combined.return_value = (
                [{"id": "r1", "name": "R1"}],
                [{"id": "i1", "name": "I1"}],
            )
            resp = mod_store_client.get("/catalog")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["data"]["indexed_count"] == 1

    def test_search_route_with_query(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows", new_callable=AsyncMock
        ) as mock_combined:
            mock_combined.return_value = (
                [{"id": "1", "name": "Alpha"}, {"id": "2", "name": "Beta"}],
                [],
            )
            resp = mod_store_client.get("/search?q=alpha")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) == 1
            assert data["data"][0]["name"] == "Alpha"

    def test_popular_route_sorts_by_downloads(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows", new_callable=AsyncMock
        ) as mock_combined:
            mock_combined.return_value = (
                [
                    {"id": "1", "name": "A", "total_downloads": 5},
                    {"id": "2", "name": "B", "total_downloads": 10},
                ],
                [],
            )
            resp = mod_store_client.get("/popular?limit=1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["data"][0]["name"] == "B"

    def test_recent_route_sorts_by_created_at(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows", new_callable=AsyncMock
        ) as mock_combined:
            mock_combined.return_value = (
                [
                    {"id": "1", "name": "A", "created_at": "2024-01-01"},
                    {"id": "2", "name": "B", "created_at": "2024-02-01"},
                ],
                [],
            )
            resp = mod_store_client.get("/recent?limit=1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["data"][0]["name"] == "B"

    def test_details_route_remote_success(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.catalog_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [
                {"versions": [{"version": "1.0.0"}]},
                {"id": "m1", "name": "Mod1", "author": "A", "description": "d"},
            ]
            resp = mod_store_client.get("/mod/m1/details")
            assert resp.status_code == 200
            data = resp.json()
            assert data["data"]["id"] == "m1"

    def test_details_route_fallback_local(self, mod_store_client) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch(
                "app.fastapi_routes.mod_store_routes._combined_rows", new_callable=AsyncMock
            ) as mock_combined,
        ):
            mock_get.side_effect = HTTPException(status_code=404, detail="not found")
            mock_combined.return_value = (
                [
                    {
                        "id": "m1",
                        "name": "Local",
                        "version": "1.0",
                        "author": "A",
                        "description": "d",
                        "source": "local",
                    }
                ],
                [],
            )
            resp = mod_store_client.get("/mod/m1/details")
            assert resp.status_code == 200
            data = resp.json()
            assert data["data"]["name"] == "Local"

    def test_details_route_not_found(self, mod_store_client) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch(
                "app.fastapi_routes.mod_store_routes._combined_rows", new_callable=AsyncMock
            ) as mock_combined,
        ):
            mock_get.side_effect = HTTPException(status_code=404, detail="not found")
            mock_combined.return_value = ([], [])
            resp = mod_store_client.get("/mod/unknown/details")
            assert resp.status_code == 404

    def test_uninstall_route_no_mod_id(self, mod_store_client) -> None:
        resp = mod_store_client.post("/uninstall", json={})
        assert resp.status_code == 400

    def test_uninstall_route_success(self, mod_store_client) -> None:
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_get:
            svc = MagicMock()
            svc.uninstall_mod.return_value = (True, "ok")
            mock_get.return_value = svc
            resp = mod_store_client.post("/uninstall", json={"mod_id": "m1"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True


class TestMSMarketCatalogRoute:
    """Cover ``/market-catalog`` route."""

    def test_market_catalog_success(self, mod_store_client) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.fetch_market_catalog_page",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "app.fastapi_routes.mod_store_routes._map_market_catalog_page",
                new_callable=AsyncMock,
            ) as mock_map,
            patch("app.fastapi_routes.mod_store_routes._installed_by_id") as mock_installed,
        ):
            mock_fetch.return_value = {"items": [], "total": 0}
            mock_map.return_value = ([], 0)
            mock_installed.return_value = {}
            resp = mod_store_client.get("/market-catalog")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["data"]["total"] == 0

    def test_market_catalog_with_query(self, mod_store_client) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.fetch_market_catalog_page",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "app.fastapi_routes.mod_store_routes._map_market_catalog_page",
                new_callable=AsyncMock,
            ) as mock_map,
            patch("app.fastapi_routes.mod_store_routes._installed_by_id") as mock_installed,
        ):
            mock_fetch.return_value = {"items": [], "total": 0}
            mock_map.return_value = ([], 0)
            mock_installed.return_value = {}
            resp = mod_store_client.get("/market-catalog?q=test&limit=50")
            assert resp.status_code == 200
            mock_fetch.assert_called_once()


class TestMSSyncModstoreLibrary:
    """Cover ``/sync-modstore-library`` route."""

    def test_sync_no_json_body(self, mod_store_client) -> None:
        resp = mod_store_client.post(
            "/sync-modstore-library", content=b"not json", headers={"content-type": "text/plain"}
        )
        assert resp.status_code == 400

    def test_sync_no_token(self, mod_store_client) -> None:
        resp = mod_store_client.post("/sync-modstore-library", json={"mod_ids": ["m1"]})
        assert resp.status_code == 400
        assert "token" in resp.json()["detail"].lower()

    def test_sync_no_mod_ids_and_not_all(self, mod_store_client) -> None:
        resp = mod_store_client.post("/sync-modstore-library", json={"token": "t1"})
        assert resp.status_code == 400

    def test_sync_with_all_flag(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.return_value = {"success": True, "message": "ok", "data": {}}
            resp = mod_store_client.post(
                "/sync-modstore-library", json={"token": "t1", "all": True}
            )
            assert resp.status_code == 200

    def test_sync_value_error_returns_400(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.side_effect = ValueError("bad")
            resp = mod_store_client.post(
                "/sync-modstore-library", json={"token": "t1", "all": True}
            )
            assert resp.status_code == 400

    def test_sync_runtime_error_returns_502(self, mod_store_client) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.side_effect = RuntimeError("network")
            resp = mod_store_client.post(
                "/sync-modstore-library", json={"token": "t1", "all": True}
            )
            assert resp.status_code == 502


# ===========================================================================
# 5. app/infrastructure/mods/catalog_client.py
# ===========================================================================


class TestCCCatalogBaseUrl:
    """Cover ``catalog_base_url`` helper."""

    def test_catalog_base_url_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_CATALOG_BASE_URL", None)
            assert cc.catalog_base_url() == cc.DEFAULT_CATALOG_BASE_URL

    def test_catalog_base_url_custom(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "https://custom.example.com/v2"}):
            assert cc.catalog_base_url() == "https://custom.example.com/v2"

    def test_catalog_base_url_strips_trailing_slash(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "https://x.com/v1/"}):
            assert cc.catalog_base_url() == "https://x.com/v1"

    def test_catalog_base_url_empty_falls_back(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": ""}):
            assert cc.catalog_base_url() == cc.DEFAULT_CATALOG_BASE_URL

    def test_catalog_base_url_whitespace_stripped(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "  https://x.com/v1  "}):
            assert cc.catalog_base_url() == "https://x.com/v1"


class TestCCMarketCatalogListUrl:
    """Cover ``market_catalog_list_url`` helper."""

    def test_market_catalog_list_url_explicit(self) -> None:
        with patch.dict(
            os.environ, {"XCAGI_MARKET_CATALOG_URL": "https://market.example.com/api/catalog"}
        ):
            assert cc.market_catalog_list_url() == "https://market.example.com/api/catalog"

    def test_market_catalog_list_url_explicit_strips_slash(self) -> None:
        with patch.dict(os.environ, {"XCAGI_MARKET_CATALOG_URL": "https://m.com/api/cat/"}):
            assert cc.market_catalog_list_url() == "https://m.com/api/cat"

    def test_market_catalog_list_url_derived_from_base(self) -> None:
        with patch.dict(
            os.environ,
            {"XCAGI_CATALOG_BASE_URL": "https://x.com/v1", "XCAGI_MARKET_CATALOG_URL": ""},
        ):
            assert cc.market_catalog_list_url() == "https://x.com/api/market/catalog"

    def test_market_catalog_list_url_default(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "", "XCAGI_MARKET_CATALOG_URL": ""}):
            # catalog_base_url returns default, which has netloc
            assert cc.market_catalog_list_url() == "https://xiu-ci.com/api/market/catalog"

    def test_market_catalog_list_url_empty_explicit_falls_back(self) -> None:
        with patch.dict(os.environ, {"XCAGI_MARKET_CATALOG_URL": "  "}):
            # Whitespace stripped to empty, falls through to derivation
            url = cc.market_catalog_list_url()
            assert "api/market/catalog" in url


class TestCCUseMarketCatalog:
    """Cover ``_use_market_catalog`` helper."""

    def test_use_market_catalog_default_true(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_CATALOG_USE_MARKET", None)
            assert cc._use_market_catalog() is True

    def test_use_market_catalog_explicit_1(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_USE_MARKET": "1"}):
            assert cc._use_market_catalog() is True

    def test_use_market_catalog_explicit_0(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_USE_MARKET": "0"}):
            assert cc._use_market_catalog() is False

    def test_use_market_catalog_false(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_USE_MARKET": "false"}):
            assert cc._use_market_catalog() is False

    def test_use_market_catalog_no(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_USE_MARKET": "no"}):
            assert cc._use_market_catalog() is False

    def test_use_market_catalog_off(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_USE_MARKET": "off"}):
            assert cc._use_market_catalog() is False

    def test_use_market_catalog_other_value_true(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_USE_MARKET": "yes"}):
            assert cc._use_market_catalog() is True


class TestCCCatalogHeaders:
    """Cover ``_catalog_headers`` helper."""

    def test_catalog_headers_no_token(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_CATALOG_TOKEN", None)
            assert cc._catalog_headers() == {}

    def test_catalog_headers_with_token(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_TOKEN": "mytoken"}):
            assert cc._catalog_headers() == {"Authorization": "Bearer mytoken"}

    def test_catalog_headers_empty_token(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_TOKEN": ""}):
            assert cc._catalog_headers() == {}

    def test_catalog_headers_whitespace_token(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_TOKEN": "  tok  "}):
            assert cc._catalog_headers() == {"Authorization": "Bearer tok"}


class TestCCCatalogUrl:
    """Cover ``_catalog_url`` helper."""

    def test_catalog_url_absolute_http(self) -> None:
        assert cc._catalog_url("http://example.com/x") == "http://example.com/x"

    def test_catalog_url_absolute_https(self) -> None:
        assert cc._catalog_url("https://example.com/x") == "https://example.com/x"

    def test_catalog_url_relative_path(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "https://x.com/v1"}):
            assert cc._catalog_url("packages") == "https://x.com/v1/packages"

    def test_catalog_url_relative_with_slash(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "https://x.com/v1"}):
            assert cc._catalog_url("/packages") == "https://x.com/v1/packages"

    def test_catalog_url_v1_prefix_stripped(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "https://x.com/v1"}):
            assert cc._catalog_url("/v1/packages") == "https://x.com/v1/packages"

    def test_catalog_url_no_v1_prefix_kept(self) -> None:
        with patch.dict(os.environ, {"XCAGI_CATALOG_BASE_URL": "https://x.com/v1"}):
            assert cc._catalog_url("/api/x") == "https://x.com/v1/api/x"


class TestCCMarketItemToPackageRow:
    """Cover ``_market_item_to_package_row`` helper."""

    def test_market_item_to_package_row_full(self) -> None:
        item = {
            "pkg_id": "p1",
            "name": "Package1",
            "version": "2.0.0",
            "description": "desc",
            "artifact": "employee_pack",
            "author": "A",
            "download_count": 5,
            "total_downloads": 10,
            "avg_rating": 4.5,
            "rating_count": 3,
            "price": 9.99,
            "created_at": "2024-01-01",
            "license": "MIT",
            "material_category": "cat1",
            "industry": "ind1",
        }
        row = cc._market_item_to_package_row(item)
        assert row is not None
        assert row["id"] == "p1"
        assert row["name"] == "Package1"
        assert row["version"] == "2.0.0"
        assert row["commerce"]["mode"] == "paid"
        assert row["commerce"]["price"] == 9.99

    def test_market_item_to_package_row_no_pkg_id(self) -> None:
        assert cc._market_item_to_package_row({}) is None

    def test_market_item_to_package_row_empty_pkg_id(self) -> None:
        assert cc._market_item_to_package_row({"pkg_id": ""}) is None

    def test_market_item_to_package_row_free_price(self) -> None:
        row = cc._market_item_to_package_row({"pkg_id": "p1", "price": 0})
        assert row["commerce"]["mode"] == "free"

    def test_market_item_to_package_row_default_version(self) -> None:
        row = cc._market_item_to_package_row({"pkg_id": "p1"})
        assert row["version"] == "1.0.0"

    def test_market_item_to_package_row_empty_version(self) -> None:
        row = cc._market_item_to_package_row({"pkg_id": "p1", "version": ""})
        assert row["version"] == "1.0.0"

    def test_market_item_to_package_row_default_artifact(self) -> None:
        row = cc._market_item_to_package_row({"pkg_id": "p1"})
        assert row["artifact"] == "employee_pack"

    def test_market_item_to_package_row_download_url(self) -> None:
        row = cc._market_item_to_package_row({"pkg_id": "p1", "version": "1.0.0"})
        assert row["download_url"] == "/v1/packages/p1/1.0.0/download"

    def test_market_item_to_package_row_public_listing_true(self) -> None:
        row = cc._market_item_to_package_row({"pkg_id": "p1"})
        assert row["public_listing"] is True

    def test_market_item_to_package_row_alias_market_item(self) -> None:
        assert cc.market_item_to_package_row is cc._market_item_to_package_row


class TestCCHttpGetJson:
    """Cover ``_http_get_json`` helper."""

    @pytest.mark.asyncio
    async def test_http_get_json_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "value"}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await cc._http_get_json("https://x.com/api")
            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_http_get_json_request_error_raises_502(self) -> None:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.RequestError("network")
            mock_client_cls.return_value = mock_client
            with patch("app.infrastructure.mods.catalog_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(HTTPException) as exc_info:
                    await cc._http_get_json("https://x.com/api")
                assert exc_info.value.status_code == 502
            # 远端网络错误应触发重试（3 次尝试）
            assert mock_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_http_get_json_4xx_raises_502(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "not found"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await cc._http_get_json("https://x.com/api")
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_http_get_json_5xx_raises_502(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "server error"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("app.infrastructure.mods.catalog_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(HTTPException) as exc_info:
                    await cc._http_get_json("https://x.com/api")
                assert exc_info.value.status_code == 502
            # 远端 5xx 应触发重试（3 次尝试）
            assert mock_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_http_get_json_5xx_retries_then_succeeds(self) -> None:
        """远端间歇性 500 后重试成功：第一次 500，第二次 200。"""
        err_resp = MagicMock()
        err_resp.status_code = 500
        err_resp.text = "Internal Server Error"
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"items": [], "total": 0}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.side_effect = [err_resp, ok_resp]

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("app.infrastructure.mods.catalog_client.asyncio.sleep", new_callable=AsyncMock):
                result = await cc._http_get_json("https://x.com/api")
                assert result == {"items": [], "total": 0}
            assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_http_get_json_request_error_retries_then_succeeds(self) -> None:
        """远端间歇性网络错误后重试成功：第一次 RequestError，第二次 200。"""
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.side_effect = [httpx.RequestError("transient"), ok_resp]

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch("app.infrastructure.mods.catalog_client.asyncio.sleep", new_callable=AsyncMock):
                result = await cc._http_get_json("https://x.com/api")
                assert result == {"ok": True}
            assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_http_get_json_invalid_json_raises_502(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await cc._http_get_json("https://x.com/api")
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_http_get_json_non_dict_raises_502(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ["not", "a", "dict"]

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await cc._http_get_json("https://x.com/api")
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_http_get_json_with_token_header(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with (
            patch.dict(os.environ, {"XCAGI_CATALOG_TOKEN": "tok"}),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            await cc._http_get_json("https://x.com/api")
            args, kwargs = mock_client.get.call_args
            assert kwargs["headers"] == {"Authorization": "Bearer tok"}


class TestCCCatalogGetJson:
    """Cover ``catalog_get_json`` helper."""

    @pytest.mark.asyncio
    async def test_catalog_get_json_calls_http_get_json(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"ok": True}
            result = await cc.catalog_get_json("/packages")
            assert result == {"ok": True}
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_catalog_get_json_with_absolute_url(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"ok": True}
            await cc.catalog_get_json("https://example.com/api")
            args, _ = mock_get.call_args
            assert args[0] == "https://example.com/api"


class TestCCFetchMarketCatalogPage:
    """Cover ``fetch_market_catalog_page`` helper."""

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_basic(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            result = await cc.fetch_market_catalog_page()
            assert result["total"] == 0
            args, _ = mock_get.call_args
            assert "limit=80" in args[0]
            assert "offset=0" in args[0]

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_with_query(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            await cc.fetch_market_catalog_page(q="test")
            args, _ = mock_get.call_args
            assert "q=test" in args[0]

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_with_collection(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            await cc.fetch_market_catalog_page(collection="col1")
            args, _ = mock_get.call_args
            assert "collection=col1" in args[0]

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_limit_clamped(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            await cc.fetch_market_catalog_page(limit=500)
            args, _ = mock_get.call_args
            assert "limit=200" in args[0]

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_limit_min_one(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            await cc.fetch_market_catalog_page(limit=0)
            args, _ = mock_get.call_args
            assert "limit=1" in args[0]

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_negative_offset(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            await cc.fetch_market_catalog_page(offset=-5)
            args, _ = mock_get.call_args
            assert "offset=0" in args[0]

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_page_all_filters(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            await cc.fetch_market_catalog_page(
                q="q",
                collection="c",
                artifact="a",
                material_category="mc",
                license_scope="ls",
                industry="ind",
                security_level="sl",
            )
            args, _ = mock_get.call_args
            url = args[0]
            assert "q=q" in url
            assert "collection=c" in url
            assert "artifact=a" in url
            assert "material_category=mc" in url
            assert "license_scope=ls" in url
            assert "industry=ind" in url
            assert "security_level=sl" in url


class TestCCFetchMarketCatalogRows:
    """Cover ``_fetch_market_catalog_rows`` helper."""

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_rows_single_page(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "items": [{"pkg_id": "p1"}, {"pkg_id": "p2"}],
                "total": 2,
            }
            rows = await cc._fetch_market_catalog_rows()
            assert len(rows) == 2
            assert rows[0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_rows_empty(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": [], "total": 0}
            rows = await cc._fetch_market_catalog_rows()
            assert rows == []

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_rows_skips_non_dict(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "items": [{"pkg_id": "p1"}, "not_dict", 42],
                "total": 1,
            }
            rows = await cc._fetch_market_catalog_rows()
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_rows_skips_no_pkg_id(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "items": [{"pkg_id": "p1"}, {"name": "no id"}],
                "total": 1,
            }
            rows = await cc._fetch_market_catalog_rows()
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_rows_items_not_list_raises(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": "not a list", "total": 0}
            with pytest.raises(HTTPException) as exc_info:
                await cc._fetch_market_catalog_rows()
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_fetch_market_catalog_rows_invalid_total_uses_len(self) -> None:
        with patch(
            "app.infrastructure.mods.catalog_client._http_get_json", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "items": [{"pkg_id": "p1"}],
                "total": "invalid",
            }
            rows = await cc._fetch_market_catalog_rows()
            assert len(rows) == 1


class TestCCCatalogDownloadTo:
    """Cover ``catalog_download_to`` helper."""

    @pytest.mark.asyncio
    async def test_catalog_download_to_success(self, tmp_path) -> None:
        dest = tmp_path / "pkg.zip"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aread = AsyncMock(return_value=b"")

        async def _aiter_bytes():
            yield b"data1"
            yield b"data2"

        mock_resp.aiter_bytes = _aiter_bytes

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await cc.catalog_download_to("/packages/p1/1.0.0/download", dest)
            assert dest.exists()
            assert dest.read_bytes() == b"data1data2"

    @pytest.mark.asyncio
    async def test_catalog_download_to_4xx_raises_502(self, tmp_path) -> None:
        dest = tmp_path / "pkg.zip"
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.aread = AsyncMock(return_value=b"not found")

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await cc.catalog_download_to("/packages/p1/1.0.0/download", dest)
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_catalog_download_to_request_error_raises_502(self, tmp_path) -> None:
        dest = tmp_path / "pkg.zip"
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(side_effect=httpx.RequestError("network"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await cc.catalog_download_to("/packages/p1/1.0.0/download", dest)
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_catalog_download_to_creates_parent_dir(self, tmp_path) -> None:
        dest = tmp_path / "subdir" / "pkg.zip"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aread = AsyncMock(return_value=b"")

        async def _aiter_bytes():
            yield b"x"

        mock_resp.aiter_bytes = _aiter_bytes

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await cc.catalog_download_to("/packages/p1/1.0.0/download", dest)
            assert dest.parent.exists()


class TestCCIterCatalogPackages:
    """Cover ``iter_catalog_packages`` helper."""

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_market_success(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=True),
            patch(
                "app.infrastructure.mods.catalog_client._fetch_market_catalog_rows",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_fetch.return_value = [{"id": "p1"}, {"id": "p2"}]
            rows = []
            async for row in cc.iter_catalog_packages():
                rows.append(row)
            assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_market_empty_falls_back(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=True),
            patch(
                "app.infrastructure.mods.catalog_client._fetch_market_catalog_rows",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "app.infrastructure.mods.catalog_client.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_fetch.return_value = []
            mock_get.return_value = {"packages": [{"id": "p1"}]}
            rows = []
            async for row in cc.iter_catalog_packages():
                rows.append(row)
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_market_http_error_falls_back(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=True),
            patch(
                "app.infrastructure.mods.catalog_client._fetch_market_catalog_rows",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "app.infrastructure.mods.catalog_client.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_fetch.side_effect = HTTPException(status_code=502, detail="err")
            mock_get.return_value = {"packages": [{"id": "p1"}]}
            rows = []
            async for row in cc.iter_catalog_packages():
                rows.append(row)
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_market_recoverable_error_falls_back(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=True),
            patch(
                "app.infrastructure.mods.catalog_client._fetch_market_catalog_rows",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "app.infrastructure.mods.catalog_client.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_fetch.side_effect = RuntimeError("err")
            mock_get.return_value = {"packages": [{"id": "p1"}]}
            rows = []
            async for row in cc.iter_catalog_packages():
                rows.append(row)
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_disabled_market_uses_index(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=False),
            patch(
                "app.infrastructure.mods.catalog_client.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_get.return_value = {"packages": [{"id": "p1"}, {"id": "p2"}]}
            rows = []
            async for row in cc.iter_catalog_packages():
                rows.append(row)
            assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_packages_not_list_raises(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=False),
            patch(
                "app.infrastructure.mods.catalog_client.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_get.return_value = {"packages": "not a list"}
            with pytest.raises(HTTPException) as exc_info:
                async for _ in cc.iter_catalog_packages():
                    pass
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_iter_catalog_packages_filters_non_dict(self) -> None:
        with (
            patch("app.infrastructure.mods.catalog_client._use_market_catalog", return_value=False),
            patch(
                "app.infrastructure.mods.catalog_client.catalog_get_json", new_callable=AsyncMock
            ) as mock_get,
            patch("app.services.catalog_visibility.is_public_catalog_row", return_value=True),
        ):
            mock_get.return_value = {"packages": [{"id": "p1"}, "not_dict", 42]}
            rows = []
            async for row in cc.iter_catalog_packages():
                rows.append(row)
            assert len(rows) == 1
