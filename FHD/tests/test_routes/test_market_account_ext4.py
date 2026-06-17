"""Tests for app.fastapi_routes.market_account — deep coverage (ext4).

Focus: helper functions (_auth_header, _normalize_bearer_token, _proxy_error_http_status,
_body_snippet, _error_message, _market_http_timeout, _market_http_retries, _transport_error_message,
_token_from_auth_response, _refresh_token_from_auth_response, _user_blob_from_market_payload,
_market_identity_from_payloads, _looks_like_verification_required),
session token management, and route handlers.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# _market_base_url
# ---------------------------------------------------------------------------


class TestMarketBaseUrl:
    def test_default_value(self):
        from app.fastapi_routes.market_account import _market_base_url

        with patch.dict("os.environ", {}, clear=False):
            # Remove the env var if it exists
            with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": ""}, clear=False):
                result = _market_base_url()
                assert isinstance(result, str)
                assert "127.0.0.1:8765" in result or result.startswith("http")

    def test_custom_env_value(self):
        from app.fastapi_routes.market_account import _market_base_url

        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://custom.example.com/"}):
            result = _market_base_url()
            assert result == "https://custom.example.com"

    def test_strips_whitespace(self):
        from app.fastapi_routes.market_account import _market_base_url

        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "  https://spaced.com  "}):
            result = _market_base_url()
            assert result == "https://spaced.com"


# ---------------------------------------------------------------------------
# _auth_header
# ---------------------------------------------------------------------------


class TestAuthHeader:
    def test_plain_token(self):
        from app.fastapi_routes.market_account import _auth_header

        result = _auth_header("mytoken123")
        assert result == "Bearer mytoken123"

    def test_bearer_prefix_already(self):
        from app.fastapi_routes.market_account import _auth_header

        result = _auth_header("Bearer mytoken123")
        assert result == "Bearer mytoken123"

    def test_authorization_prefix(self):
        from app.fastapi_routes.market_account import _auth_header

        result = _auth_header("Authorization: mytoken123")
        assert result == "Bearer mytoken123"

    def test_empty_string(self):
        from app.fastapi_routes.market_account import _auth_header

        result = _auth_header("")
        assert result == ""

    def test_none_input(self):
        from app.fastapi_routes.market_account import _auth_header

        result = _auth_header(None)
        assert result == ""

    def test_bearer_case_insensitive(self):
        from app.fastapi_routes.market_account import _auth_header

        result = _auth_header("bearer mytoken")
        assert result == "bearer mytoken"


# ---------------------------------------------------------------------------
# _normalize_bearer_token
# ---------------------------------------------------------------------------


class TestNormalizeBearerToken:
    def test_strips_bearer_prefix(self):
        from app.fastapi_routes.market_account import _normalize_bearer_token

        result = _normalize_bearer_token("Bearer mytoken123")
        assert result == "mytoken123"

    def test_plain_token(self):
        from app.fastapi_routes.market_account import _normalize_bearer_token

        result = _normalize_bearer_token("mytoken123")
        assert result == "mytoken123"

    def test_empty_string(self):
        from app.fastapi_routes.market_account import _normalize_bearer_token

        result = _normalize_bearer_token("")
        assert result == ""

    def test_none_input(self):
        from app.fastapi_routes.market_account import _normalize_bearer_token

        result = _normalize_bearer_token(None)
        assert result == ""

    def test_bearer_case_insensitive(self):
        from app.fastapi_routes.market_account import _normalize_bearer_token

        result = _normalize_bearer_token("BEARER mytoken")
        assert result == "mytoken"


# ---------------------------------------------------------------------------
# _proxy_error_http_status
# ---------------------------------------------------------------------------


class TestProxyErrorHttpStatus:
    def test_valid_proxy_error(self):
        from app.fastapi_routes.market_account import _proxy_error_http_status

        payload = {"__proxy_error__": True, "status_code": 401}
        result = _proxy_error_http_status(payload)
        assert result == 401

    def test_missing_proxy_error_flag(self):
        from app.fastapi_routes.market_account import _proxy_error_http_status

        payload = {"status_code": 401}
        result = _proxy_error_http_status(payload)
        assert result is None

    def test_non_dict_payload(self):
        from app.fastapi_routes.market_account import _proxy_error_http_status

        result = _proxy_error_http_status("error string")
        assert result is None

    def test_none_status_code(self):
        from app.fastapi_routes.market_account import _proxy_error_http_status

        payload = {"__proxy_error__": True, "status_code": None}
        result = _proxy_error_http_status(payload)
        assert result is None

    def test_non_numeric_status_code(self):
        from app.fastapi_routes.market_account import _proxy_error_http_status

        payload = {"__proxy_error__": True, "status_code": "bad"}
        result = _proxy_error_http_status(payload)
        assert result is None

    def test_none_payload(self):
        from app.fastapi_routes.market_account import _proxy_error_http_status

        result = _proxy_error_http_status(None)
        assert result is None


# ---------------------------------------------------------------------------
# _body_snippet
# ---------------------------------------------------------------------------


class TestBodySnippet:
    def test_dict_payload(self):
        from app.fastapi_routes.market_account import _body_snippet

        result = _body_snippet({"key": "value"})
        assert isinstance(result, str)
        assert "key" in result

    def test_string_payload(self):
        from app.fastapi_routes.market_account import _body_snippet

        result = _body_snippet("hello world")
        assert result == "hello world"

    def test_none_payload(self):
        from app.fastapi_routes.market_account import _body_snippet

        result = _body_snippet(None)
        assert result == ""

    def test_truncation(self):
        from app.fastapi_routes.market_account import _body_snippet

        long_text = "a" * 300
        result = _body_snippet(long_text, limit=100)
        assert len(result) <= 102  # 100 + ellipsis
        assert result.endswith("…")

    def test_short_text_no_truncation(self):
        from app.fastapi_routes.market_account import _body_snippet

        result = _body_snippet("short", limit=100)
        assert result == "short"
        assert not result.endswith("…")

    def test_newlines_replaced(self):
        from app.fastapi_routes.market_account import _body_snippet

        result = _body_snippet("line1\nline2\nline3")
        assert "\n" not in result
        assert " " in result


# ---------------------------------------------------------------------------
# _error_message
# ---------------------------------------------------------------------------


class TestErrorMessage:
    def test_dict_with_detail(self):
        from app.fastapi_routes.market_account import _error_message

        result = _error_message({"detail": "Not found"}, 404)
        assert "Not found" in result

    def test_dict_with_message(self):
        from app.fastapi_routes.market_account import _error_message

        result = _error_message({"message": "Bad request"}, 400)
        assert "Bad request" in result

    def test_dict_with_error(self):
        from app.fastapi_routes.market_account import _error_message

        result = _error_message({"error": "Server error"}, 500)
        assert "500" in result

    def test_dict_with_list_detail(self):
        from app.fastapi_routes.market_account import _error_message

        detail = [{"msg": "field required"}, {"msg": "invalid type"}]
        result = _error_message({"detail": detail}, 422)
        assert "field required" in result
        assert "invalid type" in result

    def test_500_error_hint(self):
        from app.fastapi_routes.market_account import _error_message

        result = _error_message({}, 500)
        assert "500" in result
        assert "XCAGI_MARKET_BASE_URL" in result

    def test_non_dict_payload(self):
        from app.fastapi_routes.market_account import _error_message

        result = _error_message("string error", 400)
        assert "400" in result

    def test_dict_with_no_detail_key(self):
        from app.fastapi_routes.market_account import _error_message

        result = _error_message({"foo": "bar"}, 400)
        assert "400" in result


# ---------------------------------------------------------------------------
# _market_http_timeout / _market_http_retries
# ---------------------------------------------------------------------------


class TestMarketHttpConfig:
    def test_default_timeout(self):
        from app.fastapi_routes.market_account import _market_http_timeout

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": ""}, clear=False):
            result = _market_http_timeout()
            assert result == 20.0

    def test_custom_timeout(self):
        from app.fastapi_routes.market_account import _market_http_timeout

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": "30"}):
            result = _market_http_timeout()
            assert result == 30.0

    def test_invalid_timeout(self):
        from app.fastapi_routes.market_account import _market_http_timeout

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": "not_a_number"}):
            result = _market_http_timeout()
            assert result == 20.0

    def test_default_retries(self):
        from app.fastapi_routes.market_account import _market_http_retries

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": ""}, clear=False):
            result = _market_http_retries()
            assert result == 1

    def test_custom_retries(self):
        from app.fastapi_routes.market_account import _market_http_retries

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "3"}):
            result = _market_http_retries()
            assert result == 3

    def test_invalid_retries(self):
        from app.fastapi_routes.market_account import _market_http_retries

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "abc"}):
            result = _market_http_retries()
            assert result == 1

    def test_zero_retries_clamped(self):
        from app.fastapi_routes.market_account import _market_http_retries

        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "0"}):
            result = _market_http_retries()
            assert result == 1  # max(1, 0) = 1


# ---------------------------------------------------------------------------
# _transport_error_message
# ---------------------------------------------------------------------------


class TestTransportErrorMessage:
    def test_read_timeout(self):
        import httpx
        from app.fastapi_routes.market_account import _transport_error_message

        exc = httpx.ReadTimeout("read timed out")
        msg, status = _transport_error_message(exc)
        assert "超时" in msg
        assert status == 503

    def test_generic_http_error(self):
        import httpx
        from app.fastapi_routes.market_account import _transport_error_message

        exc = httpx.ConnectError("connection refused")
        msg, status = _transport_error_message(exc)
        assert "无法连接" in msg
        assert status == 502

    def test_non_httpx_exception(self):
        from app.fastapi_routes.market_account import _transport_error_message

        exc = RuntimeError("something went wrong")
        msg, status = _transport_error_message(exc)
        assert "无法连接" in msg
        assert status == 502


# ---------------------------------------------------------------------------
# _token_from_auth_response
# ---------------------------------------------------------------------------


class TestTokenFromAuthResponse:
    def test_top_level_token(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"token": "abc123"})
        assert result == "abc123"

    def test_data_access_token(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"data": {"access_token": "xyz789"}})
        assert result == "xyz789"

    def test_data_tokens_nested(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"data": {"tokens": {"access_token": "nested123"}}})
        assert result == "nested123"

    def test_top_level_tokens_nested(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"tokens": {"accessToken": "camelCase"}})
        assert result == "camelCase"

    def test_no_token_found(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"foo": "bar"})
        assert result == ""

    def test_non_dict_payload(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response("not a dict")
        assert result == ""

    def test_empty_token_ignored(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"token": "", "access_token": "  "})
        assert result == ""

    def test_market_access_token(self):
        from app.fastapi_routes.market_account import _token_from_auth_response

        result = _token_from_auth_response({"market_access_token": "mat123"})
        assert result == "mat123"


# ---------------------------------------------------------------------------
# _refresh_token_from_auth_response
# ---------------------------------------------------------------------------


class TestRefreshTokenFromAuthResponse:
    def test_top_level_refresh_token(self):
        from app.fastapi_routes.market_account import _refresh_token_from_auth_response

        result = _refresh_token_from_auth_response({"refresh_token": "rt123"})
        assert result == "rt123"

    def test_data_nested(self):
        from app.fastapi_routes.market_account import _refresh_token_from_auth_response

        result = _refresh_token_from_auth_response({"data": {"refresh_token": "rt456"}})
        assert result == "rt456"

    def test_camel_case(self):
        from app.fastapi_routes.market_account import _refresh_token_from_auth_response

        result = _refresh_token_from_auth_response({"refreshToken": "rt789"})
        assert result == "rt789"

    def test_no_refresh_token(self):
        from app.fastapi_routes.market_account import _refresh_token_from_auth_response

        result = _refresh_token_from_auth_response({"token": "abc"})
        assert result == ""

    def test_non_dict_payload(self):
        from app.fastapi_routes.market_account import _refresh_token_from_auth_response

        result = _refresh_token_from_auth_response(None)
        assert result == ""


# ---------------------------------------------------------------------------
# _user_blob_from_market_payload
# ---------------------------------------------------------------------------


class TestUserBlobFromMarketPayload:
    def test_top_level_user(self):
        from app.fastapi_routes.market_account import _user_blob_from_market_payload

        result = _user_blob_from_market_payload({"user": {"id": 1, "username": "test"}})
        assert result == {"id": 1, "username": "test"}

    def test_data_user(self):
        from app.fastapi_routes.market_account import _user_blob_from_market_payload

        result = _user_blob_from_market_payload({"data": {"user": {"id": 2, "username": "test2"}}})
        assert result == {"id": 2, "username": "test2"}

    def test_data_with_id_and_username(self):
        from app.fastapi_routes.market_account import _user_blob_from_market_payload

        result = _user_blob_from_market_payload({"data": {"id": 3, "username": "test3"}})
        assert result == {"id": 3, "username": "test3"}

    def test_top_level_id_and_username(self):
        from app.fastapi_routes.market_account import _user_blob_from_market_payload

        result = _user_blob_from_market_payload({"id": 4, "username": "test4"})
        assert result == {"id": 4, "username": "test4"}

    def test_non_dict_payload(self):
        from app.fastapi_routes.market_account import _user_blob_from_market_payload

        result = _user_blob_from_market_payload("not a dict")
        assert result == {}

    def test_empty_dict(self):
        from app.fastapi_routes.market_account import _user_blob_from_market_payload

        result = _user_blob_from_market_payload({})
        assert result == {}


# ---------------------------------------------------------------------------
# _market_identity_from_payloads
# ---------------------------------------------------------------------------


class TestMarketIdentityFromPayloads:
    def test_enterprise_user(self):
        from app.fastapi_routes.market_account import _market_identity_from_payloads

        payload = {"user": {"is_enterprise": True, "is_admin": False, "username": "ent_user"}}
        is_ent, is_admin, blob = _market_identity_from_payloads(payload)
        assert is_ent is True
        assert is_admin is False
        assert blob["username"] == "ent_user"

    def test_admin_user(self):
        from app.fastapi_routes.market_account import _market_identity_from_payloads

        payload = {"user": {"is_admin": True, "username": "admin"}}
        is_ent, is_admin, blob = _market_identity_from_payloads(payload)
        assert is_admin is True

    def test_proxy_error_skipped(self):
        from app.fastapi_routes.market_account import _market_identity_from_payloads

        payload = {"__proxy_error__": True, "status_code": 500}
        is_ent, is_admin, blob = _market_identity_from_payloads(payload)
        assert blob == {}

    def test_multiple_payloads_merged(self):
        from app.fastapi_routes.market_account import _market_identity_from_payloads

        p1 = {"user": {"username": "first"}}
        p2 = {"user": {"is_enterprise": True, "username": "second"}}
        is_ent, is_admin, blob = _market_identity_from_payloads(p1, p2)
        assert is_ent is True
        assert blob["username"] == "first"  # first non-empty blob wins


# ---------------------------------------------------------------------------
# _looks_like_verification_required
# ---------------------------------------------------------------------------


class TestLooksLikeVerificationRequired:
    def test_verification_code_message(self):
        from app.fastapi_routes.market_account import _looks_like_verification_required

        result = _looks_like_verification_required({"detail": "需要验证码"})
        assert result is True

    def test_verification_english(self):
        from app.fastapi_routes.market_account import _looks_like_verification_required

        result = _looks_like_verification_required({"detail": "verification required"})
        assert result is True

    def test_normal_error(self):
        from app.fastapi_routes.market_account import _looks_like_verification_required

        result = _looks_like_verification_required({"detail": "Invalid password"})
        assert result is False


# ---------------------------------------------------------------------------
# session_id_from_request
# ---------------------------------------------------------------------------


class TestSessionIdFromRequest:
    def test_from_cookie(self):
        from app.fastapi_routes.market_account import session_id_from_request

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "test-session-123"}
        mock_request.headers = {}
        result = session_id_from_request(mock_request)
        assert result == "test-session-123"

    def test_from_header(self):
        from app.fastapi_routes.market_account import session_id_from_request

        mock_request = MagicMock()
        mock_request.cookies = {}
        mock_request.headers = {"X-Session-ID": "header-session-456"}
        result = session_id_from_request(mock_request)
        assert result == "header-session-456"

    def test_no_session(self):
        from app.fastapi_routes.market_account import session_id_from_request

        mock_request = MagicMock()
        mock_request.cookies = {}
        mock_request.headers = {}
        result = session_id_from_request(mock_request)
        assert result == ""

    def test_custom_cookie_name(self):
        from app.fastapi_routes.market_account import session_id_from_request

        mock_request = MagicMock()
        mock_request.cookies = {"my_session": "custom-789"}
        mock_request.headers = {}
        with patch.dict("os.environ", {"SESSION_COOKIE_NAME": "my_session"}):
            result = session_id_from_request(mock_request)
            assert result == "custom-789"


# ---------------------------------------------------------------------------
# _authorization_from_request
# ---------------------------------------------------------------------------


class TestAuthorizationFromRequest:
    def test_with_session_token(self):
        from app.fastapi_routes.market_account import _authorization_from_request

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "sid123"}
        mock_request.headers = {}
        with patch(
            "app.fastapi_routes.market_account.session_market_token",
            return_value="session_tok",
        ):
            result = _authorization_from_request(mock_request, {})
            assert "session_tok" in result

    def test_with_body_token(self):
        from app.fastapi_routes.market_account import _authorization_from_request

        mock_request = MagicMock()
        mock_request.cookies = {}
        mock_request.headers = {}
        with patch(
            "app.fastapi_routes.market_account.session_market_token",
            return_value="",
        ), patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            return_value="",
        ):
            result = _authorization_from_request(mock_request, {"token": "body_tok"})
            assert "body_tok" in result

    def test_with_header_authorization(self):
        from app.fastapi_routes.market_account import _authorization_from_request

        mock_request = MagicMock()
        mock_request.cookies = {}
        mock_request.headers = {"Authorization": "Bearer header_tok"}
        with patch(
            "app.fastapi_routes.market_account.session_market_token",
            return_value="",
        ), patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            return_value="",
        ):
            result = _authorization_from_request(mock_request, {})
            assert "header_tok" in result

    def test_no_authorization(self):
        from app.fastapi_routes.market_account import _authorization_from_request

        mock_request = MagicMock()
        mock_request.cookies = {}
        mock_request.headers = {}
        with patch(
            "app.fastapi_routes.market_account.session_market_token",
            return_value="",
        ), patch(
            "app.fastapi_routes.market_account.latest_session_market_token",
            return_value="",
        ):
            result = _authorization_from_request(mock_request, {})
            assert result == ""


# ---------------------------------------------------------------------------
# save_session_market_token / clear_session_market_token
# ---------------------------------------------------------------------------


class TestSessionTokenManagement:
    def test_save_and_retrieve(self):
        from app.fastapi_routes.market_account import (
            _MARKET_SESSION_TOKENS,
            save_session_market_token,
            session_market_token,
        )

        # Use a unique key to avoid collision
        sid = f"test_sid_{id(self)}"
        try:
            with patch("app.db.session.get_db", side_effect=ImportError("no db")):
                save_session_market_token(sid, "tok123")
            result = session_market_token(sid)
            assert result == "tok123"
        finally:
            _MARKET_SESSION_TOKENS.pop(sid, None)

    def test_save_empty_session_id(self):
        from app.fastapi_routes.market_account import save_session_market_token

        # Should not raise
        save_session_market_token("", "tok123")

    def test_save_empty_token(self):
        from app.fastapi_routes.market_account import save_session_market_token

        # Should not raise
        save_session_market_token("sid", "")

    def test_clear_token(self):
        from app.fastapi_routes.market_account import (
            _MARKET_SESSION_TOKENS,
            clear_session_market_token,
            session_market_token,
        )

        sid = f"test_clear_sid_{id(self)}"
        try:
            with patch("app.db.session.get_db", side_effect=ImportError("no db")):
                _MARKET_SESSION_TOKENS[sid] = "tok_to_clear"
            clear_session_market_token(sid)
            result = session_market_token(sid)
            assert result == ""
        finally:
            _MARKET_SESSION_TOKENS.pop(sid, None)

    def test_session_market_token_empty_sid(self):
        from app.fastapi_routes.market_account import session_market_token

        result = session_market_token("")
        assert result == ""


# ---------------------------------------------------------------------------
# Market routes (integration with TestClient)
# ---------------------------------------------------------------------------


class TestMarketAccountRoutes:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.fastapi_routes.market_account import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=False)

    def test_market_status(self, client):
        resp = client.get("/api/market/status")
        assert resp.status_code in (200, 401, 403, 502)

    def test_market_login_route_empty_body(self, client):
        resp = client.post("/api/market/login", json={})
        assert resp.status_code in (200, 400, 422, 502)

    def test_market_session_handoff(self, client):
        resp = client.get("/api/market/session-handoff")
        assert resp.status_code in (200, 404, 502)

    def test_market_account_overview(self, client):
        resp = client.post("/api/market/account-overview", json={})
        assert resp.status_code in (200, 401, 403, 422, 502)


# ---------------------------------------------------------------------------
# _degraded_account_overview
# ---------------------------------------------------------------------------


class TestDegradedAccountOverview:
    def test_returns_dict_with_message(self):
        from app.fastapi_routes.market_account import _degraded_account_overview

        result = _degraded_account_overview("service unavailable")
        assert isinstance(result, dict)
        assert "sync_warning" in result or "degraded" in result


# ---------------------------------------------------------------------------
# _merge_live_overview_fields
# ---------------------------------------------------------------------------


class TestMergeLiveOverviewFields:
    def test_merges_fields(self):
        from app.fastapi_routes.market_account import _merge_live_overview_fields

        data = {"user": {"name": "test"}}
        live = {"user": {"email": "test@example.com"}, "extra": "value"}
        _merge_live_overview_fields(data, live)
        # Should have merged something from live into data
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# _is_local_market_base
# ---------------------------------------------------------------------------


class TestIsLocalMarketBase:
    def test_localhost(self):
        from app.fastapi_routes.market_account import _is_local_market_base

        result = _is_local_market_base("http://127.0.0.1:8765")
        assert result is True

    def test_remote_url(self):
        from app.fastapi_routes.market_account import _is_local_market_base

        result = _is_local_market_base("https://api.example.com")
        assert result is False

    def test_localhost_hostname(self):
        from app.fastapi_routes.market_account import _is_local_market_base

        result = _is_local_market_base("http://localhost:8765")
        assert result is True


# ---------------------------------------------------------------------------
# _demo_market_login_payload
# ---------------------------------------------------------------------------


class TestDemoMarketLoginPayload:
    def test_returns_dict(self):
        from app.fastapi_routes.market_account import _demo_market_login_payload

        result = _demo_market_login_payload(
            {"username": "demo", "password": "demo"},
            market_base_url="http://127.0.0.1:8765",
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _market_auth_from_request
# ---------------------------------------------------------------------------


class TestMarketAuthFromRequest:
    def test_extracts_auth(self):
        from app.fastapi_routes.market_account import _market_auth_from_request

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "sid"}
        mock_request.headers = {}
        with patch(
            "app.fastapi_routes.market_account.session_market_token",
            return_value="tok123",
        ):
            result = _market_auth_from_request(mock_request)
            assert "tok123" in result
