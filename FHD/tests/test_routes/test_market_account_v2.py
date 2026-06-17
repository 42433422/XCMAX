"""Tests for app.fastapi_routes.market_account — pure helper functions and token management."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes import market_account as ma

# ========================= _market_base_url ===================================


class TestMarketBaseUrl:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        assert ma._market_base_url() == "http://127.0.0.1:8765"

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "  https://market.example.com/  ")
        assert ma._market_base_url() == "https://market.example.com"

    def test_empty_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "")
        assert ma._market_base_url() == "http://127.0.0.1:8765"


# ========================= _auth_header =======================================


class TestAuthHeader:
    def test_plain_token(self):
        assert ma._auth_header("mytoken") == "Bearer mytoken"

    def test_bearer_prefix(self):
        assert ma._auth_header("Bearer mytoken") == "Bearer mytoken"

    def test_authorization_prefix(self):
        assert ma._auth_header("Authorization: mytoken") == "Bearer mytoken"

    def test_empty(self):
        assert ma._auth_header("") == ""

    def test_none(self):
        assert ma._auth_header(None) == ""

    def test_whitespace_only(self):
        assert ma._auth_header("   ") == ""


# ========================= _normalize_bearer_token ============================


class TestNormalizeBearerToken:
    def test_strips_bearer(self):
        assert ma._normalize_bearer_token("Bearer abc123") == "abc123"

    def test_already_plain(self):
        assert ma._normalize_bearer_token("abc123") == "abc123"

    def test_empty(self):
        assert ma._normalize_bearer_token("") == ""

    def test_none(self):
        assert ma._normalize_bearer_token(None) == ""


# ========================= _proxy_error_http_status ===========================


class TestProxyErrorHttpStatus:
    def test_valid_status(self):
        payload = {"__proxy_error__": True, "status_code": 401}
        assert ma._proxy_error_http_status(payload) == 401

    def test_no_proxy_error_key(self):
        assert ma._proxy_error_http_status({"status_code": 500}) is None

    def test_not_dict(self):
        assert ma._proxy_error_http_status("error") is None

    def test_missing_status_code(self):
        payload = {"__proxy_error__": True}
        assert ma._proxy_error_http_status(payload) is None

    def test_invalid_status_code(self):
        payload = {"__proxy_error__": True, "status_code": "bad"}
        assert ma._proxy_error_http_status(payload) is None


# ========================= _body_snippet ======================================


class TestBodySnippet:
    def test_dict_payload(self):
        result = ma._body_snippet({"key": "value"})
        assert "key" in result

    def test_long_payload_truncated(self):
        result = ma._body_snippet({"k": "v" * 500}, limit=50)
        assert result.endswith("…")

    def test_string_payload(self):
        result = ma._body_snippet("hello")
        assert "hello" in result

    def test_none_payload(self):
        result = ma._body_snippet(None)
        assert result == ""

    def test_newlines_replaced(self):
        result = ma._body_snippet({"k": "line1\nline2"})
        assert "\n" not in result


# ========================= _error_message =====================================


class TestErrorMessage:
    def test_500_with_detail(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        result = ma._error_message({"detail": "db error"}, 500)
        assert "500" in result
        assert "db error" in result

    def test_500_without_detail(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        result = ma._error_message({}, 500)
        assert "500" in result

    def test_400_with_message(self):
        result = ma._error_message({"message": "bad request"}, 400)
        assert result == "bad request"

    def test_400_with_detail_list(self):
        result = ma._error_message({"detail": [{"msg": "field required"}]}, 400)
        assert "field required" in result

    def test_non_dict_payload(self):
        result = ma._error_message("string error", 400)
        assert result == "HTTP 400"

    def test_500_internal_server_error_message(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        result = ma._error_message({"detail": "Internal Server Error"}, 500)
        assert "500" in result


# ========================= _market_http_timeout ===============================


class TestMarketHttpTimeout:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MARKET_HTTP_TIMEOUT", raising=False)
        assert ma._market_http_timeout() == 20.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_HTTP_TIMEOUT", "30")
        assert ma._market_http_timeout() == 30.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_HTTP_TIMEOUT", "bad")
        assert ma._market_http_timeout() == 20.0


# ========================= _market_http_retries ===============================


class TestMarketHttpRetries:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MARKET_HTTP_RETRIES", raising=False)
        assert ma._market_http_retries() == 1

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_HTTP_RETRIES", "3")
        assert ma._market_http_retries() == 3

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_HTTP_RETRIES", "bad")
        assert ma._market_http_retries() == 1

    def test_zero_clamped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_HTTP_RETRIES", "0")
        assert ma._market_http_retries() == 1


# ========================= _transport_error_message ===========================


class TestTransportErrorMessage:
    def test_read_timeout(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        exc = httpx.ReadTimeout("timeout")
        msg, code = ma._transport_error_message(exc)
        assert "超时" in msg
        assert code == 503

    def test_other_http_error(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        exc = httpx.ConnectError("refused")
        msg, code = ma._transport_error_message(exc)
        assert "无法连接" in msg
        assert code == 502

    def test_generic_exception(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        exc = Exception("something")
        msg, code = ma._transport_error_message(exc)
        assert "无法连接" in msg
        assert code == 502


# ========================= _token_from_auth_response ==========================


class TestTokenFromAuthResponse:
    def test_data_access_token(self):
        payload = {"data": {"access_token": "tok123"}}
        assert ma._token_from_auth_response(payload) == "tok123"

    def test_data_token(self):
        payload = {"data": {"token": "tok456"}}
        assert ma._token_from_auth_response(payload) == "tok456"

    def test_top_level_access_token(self):
        payload = {"access_token": "tok789"}
        assert ma._token_from_auth_response(payload) == "tok789"

    def test_nested_tokens(self):
        payload = {"data": {"tokens": {"access_token": "nested_tok"}}}
        assert ma._token_from_auth_response(payload) == "nested_tok"

    def test_top_level_tokens(self):
        payload = {"tokens": {"accessToken": "top_tok"}}
        assert ma._token_from_auth_response(payload) == "top_tok"

    def test_empty_string_skipped(self):
        payload = {"data": {"access_token": ""}, "token": "real_tok"}
        assert ma._token_from_auth_response(payload) == "real_tok"

    def test_none_skipped(self):
        payload = {"data": {"access_token": None}, "token": "real_tok"}
        assert ma._token_from_auth_response(payload) == "real_tok"

    def test_not_dict(self):
        assert ma._token_from_auth_response("not a dict") == ""

    def test_no_token_fields(self):
        assert ma._token_from_auth_response({"data": {}}) == ""

    def test_data_not_dict(self):
        payload = {"data": "not a dict", "token": "fallback"}
        assert ma._token_from_auth_response(payload) == "fallback"


# ========================= _refresh_token_from_auth_response ==================


class TestRefreshTokenFromAuthResponse:
    def test_data_refresh_token(self):
        payload = {"data": {"refresh_token": "rt123"}}
        assert ma._refresh_token_from_auth_response(payload) == "rt123"

    def test_data_refreshToken(self):
        payload = {"data": {"refreshToken": "rt456"}}
        assert ma._refresh_token_from_auth_response(payload) == "rt456"

    def test_nested_tokens(self):
        payload = {"data": {"tokens": {"refresh_token": "nested_rt"}}}
        assert ma._refresh_token_from_auth_response(payload) == "nested_rt"

    def test_top_level(self):
        payload = {"refresh_token": "top_rt"}
        assert ma._refresh_token_from_auth_response(payload) == "top_rt"

    def test_not_dict(self):
        assert ma._refresh_token_from_auth_response("bad") == ""


# ========================= _user_blob_from_market_payload =====================


class TestUserBlobFromMarketPayload:
    def test_top_level_user(self):
        payload = {"user": {"id": 1, "username": "u"}}
        assert ma._user_blob_from_market_payload(payload) == {"id": 1, "username": "u"}

    def test_data_user(self):
        payload = {"data": {"user": {"id": 2, "username": "v"}}}
        assert ma._user_blob_from_market_payload(payload) == {"id": 2, "username": "v"}

    def test_data_with_id_and_username(self):
        payload = {"data": {"id": 3, "username": "w"}}
        assert ma._user_blob_from_market_payload(payload) == {"id": 3, "username": "w"}

    def test_top_level_id_and_username(self):
        payload = {"id": 4, "username": "x"}
        assert ma._user_blob_from_market_payload(payload) == {"id": 4, "username": "x"}

    def test_not_dict(self):
        assert ma._user_blob_from_market_payload("bad") == {}

    def test_no_user_info(self):
        assert ma._user_blob_from_market_payload({"data": {}}) == {}


# ========================= _market_identity_from_payloads =====================


class TestMarketIdentityFromPayloads:
    def test_enterprise_admin(self):
        payloads = [{"user": {"is_enterprise": True, "is_admin": True, "username": "u"}}]
        ent, admin, blob = ma._market_identity_from_payloads(*payloads)
        assert ent is True
        assert admin is True
        assert blob["username"] == "u"

    def test_proxy_error_skipped(self):
        payloads = [{"__proxy_error__": True}, {"user": {"username": "u"}}]
        ent, admin, blob = ma._market_identity_from_payloads(*payloads)
        assert blob["username"] == "u"

    def test_empty_payloads(self):
        ent, admin, blob = ma._market_identity_from_payloads()
        assert ent is False
        assert admin is False
        assert blob == {}


# ========================= _looks_like_verification_required ==================


class TestLooksLikeVerificationRequired:
    def test_verification_keyword(self):
        payload = {"detail": "需要验证码"}
        assert ma._looks_like_verification_required(payload) is True

    def test_verification_english(self):
        payload = {"detail": "verification required"}
        assert ma._looks_like_verification_required(payload) is True

    def test_no_verification(self):
        payload = {"detail": "username taken"}
        assert ma._looks_like_verification_required(payload) is False


# ========================= _is_local_market_base ==============================


class TestIsLocalMarketBase:
    def test_localhost(self):
        assert ma._is_local_market_base("http://localhost:8765") is True

    def test_127(self):
        assert ma._is_local_market_base("http://127.0.0.1:8765") is True

    def test_remote(self):
        assert ma._is_local_market_base("https://market.example.com") is False

    def test_empty(self):
        assert ma._is_local_market_base("") is False


# ========================= _degraded_account_overview =========================


class TestDegradedAccountOverview:
    def test_structure(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        result = ma._degraded_account_overview("test error")
        assert result["degraded"] is True
        assert result["market_unreachable"] is True
        assert result["sync_warning"] == "test error"
        assert isinstance(result["wallet"], dict)
        assert isinstance(result["membership"], dict)


# ========================= _merge_live_overview_fields ========================


class TestMergeLiveOverviewFields:
    def test_merge_wallet(self):
        data = {"wallet": {"balance": 0}}
        live = {"wallet": {"balance": 100}}
        ma._merge_live_overview_fields(data, live)
        assert data["wallet"]["balance"] == 100

    def test_merge_llm(self):
        data = {"llm": {"providers": []}}
        live = {"llm": {"providers": ["p1"]}}
        ma._merge_live_overview_fields(data, live)
        assert data["llm"]["providers"] == ["p1"]

    def test_merge_user(self):
        data = {"user": {}}
        live = {"user": {"id": 1}}
        ma._merge_live_overview_fields(data, live)
        assert data["user"]["id"] == 1

    def test_no_overwrite_none(self):
        data = {"wallet": {"balance": 0}}
        live = {"wallet": None}
        ma._merge_live_overview_fields(data, live)
        assert data["wallet"]["balance"] == 0


# ========================= session token management ===========================


class TestSessionMarketToken:
    """Test in-memory session token get/set/clear without DB."""

    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_save_and_get(self):
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "tok1")
        assert ma.session_market_token("sid1") == "tok1"

    def test_save_with_refresh(self):
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "tok1", "rt1")
        assert ma.session_market_refresh_token("sid1") == "rt1"

    def test_empty_session_id_ignored(self):
        ma.save_session_market_token("", "tok")
        assert "" not in ma._MARKET_SESSION_TOKENS

    def test_empty_token_ignored(self):
        ma.save_session_market_token("sid", "")
        assert "sid" not in ma._MARKET_SESSION_TOKENS

    def test_clear_token(self):
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "tok1", "rt1")
            ma.clear_session_market_token("sid1")
        assert ma.session_market_token("sid1") == ""

    def test_clear_empty_session_id(self):
        ma.clear_session_market_token("")  # should not raise

    def test_session_market_token_empty_sid(self):
        assert ma.session_market_token("") == ""

    def test_session_market_refresh_token_empty_sid(self):
        assert ma.session_market_refresh_token("") == ""


# ========================= _demo_market_login_payload =========================


class TestDemoMarketLoginPayload:
    def test_basic(self):
        shim = {
            "token": "demo_tok",
            "refresh_token": "demo_rt",
            "is_enterprise": True,
            "is_market_admin": False,
            "raw": {},
        }
        result = ma._demo_market_login_payload(shim, market_base_url="http://localhost:8765")
        assert result["success"] is True
        assert result["token"] == "demo_tok"
        assert result["is_enterprise"] is True
        assert isinstance(result["raw"]["user"], dict)

    def test_user_from_raw(self):
        shim = {
            "token": "t",
            "refresh_token": "",
            "is_enterprise": False,
            "is_market_admin": True,
            "raw": {"user": {"id": 5, "username": "test"}},
        }
        result = ma._demo_market_login_payload(shim, market_base_url="http://localhost:8765")
        assert result["raw"]["user"]["id"] == 5


# ========================= _xcagi_chat_timeout_seconds etc ====================


class TestXcagiChatTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_TIMEOUT_SEC", raising=False)
        # This is from chat_helpers, but let's test market_account's own config fns
        assert ma._market_http_timeout() == 20.0


# ========================= _authorization_from_request ========================


class TestAuthorizationFromRequest:
    def test_session_token(self):
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        ma._MARKET_SESSION_TOKENS["sid1"] = "sess_tok"
        try:
            result = ma._authorization_from_request(request, {})
            assert "sess_tok" in result
        finally:
            ma._MARKET_SESSION_TOKENS.pop("sid1", None)

    def test_body_token(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        result = ma._authorization_from_request(request, {"authorization": "body_tok"})
        assert "body_tok" in result

    def test_header_authorization(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {"Authorization": "Bearer hdr_tok"}
        result = ma._authorization_from_request(request, {})
        assert "hdr_tok" in result

    def test_no_auth(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        result = ma._authorization_from_request(request, {})
        assert result == ""


# ========================= send_market_reset_password_code ====================


class TestSendMarketResetPasswordCode:
    @pytest.mark.asyncio
    async def test_invalid_email(self):
        result = await ma.send_market_reset_password_code("")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_no_at_sign(self):
        result = await ma.send_market_reset_password_code("bademail")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_valid_email_proxy_error(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        error_payload = {
            "__proxy_error__": True,
            "status_code": 502,
            "payload": {"detail": "unavailable"},
        }
        with patch.object(ma, "_proxy_json", return_value=error_payload):
            result = await ma.send_market_reset_password_code("test@example.com")
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_valid_email_success(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        with patch.object(ma, "_proxy_json", return_value={"message": "ok"}):
            result = await ma.send_market_reset_password_code("test@example.com")
            assert result["success"] is True


# ========================= reset_market_password_with_code ====================


class TestResetMarketPasswordWithCode:
    @pytest.mark.asyncio
    async def test_invalid_email(self):
        result = await ma.reset_market_password_with_code("", "1234", "newpass")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_short_code(self):
        result = await ma.reset_market_password_with_code("a@b.com", "12", "newpass")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_short_password(self):
        result = await ma.reset_market_password_with_code("a@b.com", "1234", "12345")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        with patch.object(ma, "_proxy_json", return_value={"success": True}):
            result = await ma.reset_market_password_with_code("a@b.com", "123456", "newpassword")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_proxy_error(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        error_payload = {
            "__proxy_error__": True,
            "status_code": 400,
            "payload": {"detail": "bad code"},
        }
        with patch.object(ma, "_proxy_json", return_value=error_payload):
            result = await ma.reset_market_password_with_code("a@b.com", "123456", "newpassword")
            assert result["success"] is False


# ========================= register_market_user ===============================


class TestRegisterMarketUser:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        with patch.object(
            ma, "_proxy_json", return_value={"data": {"access_token": "tok", "refresh_token": "rt"}}
        ):
            result = await ma.register_market_user("user1", "pass123", "a@b.com")
            assert result["success"] is True
            assert result["token"] == "tok"

    @pytest.mark.asyncio
    async def test_proxy_error(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        error_payload = {
            "__proxy_error__": True,
            "status_code": 409,
            "payload": {"detail": "用户名已存在"},
        }
        with patch.object(ma, "_proxy_json", return_value=error_payload):
            result = await ma.register_market_user("user1", "pass123", "a@b.com")
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_verification_required_fallback(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        error_payload = {
            "__proxy_error__": True,
            "status_code": 400,
            "payload": {"detail": "需要验证码"},
        }
        open_reg_payload = {"data": {"access_token": "open_tok", "refresh_token": "open_rt"}}
        call_count = 0

        async def mock_proxy(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_payload
            return open_reg_payload

        with patch.object(ma, "_proxy_json", side_effect=mock_proxy):
            result = await ma.register_market_user("user1", "pass123", "a@b.com")
            assert result["success"] is True


# ========================= login_market_with_phone_code =======================


class TestLoginMarketWithPhoneCode:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        login_resp = {"data": {"access_token": "phone_tok", "refresh_token": "phone_rt"}}
        me_resp = {"user": {"id": 1, "username": "u"}}
        call_count = 0

        async def mock_proxy(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if path == "/api/auth/login-with-phone-code":
                return login_resp
            if path == "/api/auth/me":
                return me_resp
            return {}

        with patch.object(ma, "_proxy_json", side_effect=mock_proxy):
            result = await ma.login_market_with_phone_code("13800138000", "1234")
            assert result["success"] is True
            assert result["token"] == "phone_tok"


# ========================= send_market_phone_code =============================


class TestSendMarketPhoneCode:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(ma, "_proxy_json", return_value={"message": "验证码已发送"}):
            result = await ma.send_market_phone_code("13800138000")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_json_response_error(self):
        error_resp = ma.JSONResponse(
            {"success": False, "message": "市场服务不可用"}, status_code=502
        )
        with patch.object(ma, "_proxy_json", return_value=error_resp):
            result = await ma.send_market_phone_code("13800138000")
            assert result["success"] is False


# ========================= refresh_session_market_token =======================


class TestRefreshSessionMarketToken:
    @pytest.fixture(autouse=True)
    def _clear(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    @pytest.mark.asyncio
    async def test_no_refresh_token(self):
        result = await ma.refresh_session_market_token("sid1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_refresh_success(self):
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "old_tok", "old_rt")
        refresh_resp = {"data": {"access_token": "new_tok", "refresh_token": "new_rt"}}
        with patch.object(ma, "_proxy_json", return_value=refresh_resp):
            with patch("app.db.session.get_db", side_effect=ImportError("no db")):
                result = await ma.refresh_session_market_token("sid1")
        assert result == "new_tok"

    @pytest.mark.asyncio
    async def test_refresh_proxy_error(self):
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "old_tok", "old_rt")
        error_payload = {"__proxy_error__": True, "status_code": 401}
        with patch.object(ma, "_proxy_json", return_value=error_payload):
            with patch("app.db.session.get_db", side_effect=ImportError("no db")):
                result = await ma.refresh_session_market_token("sid1")
        assert result == ""


# ========================= session_id_from_request ============================


class TestSessionIdFromRequest:
    def test_from_cookie(self, monkeypatch):
        monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
        request = MagicMock()
        request.cookies = {"session_id": "abc123"}
        request.headers = {}
        assert ma.session_id_from_request(request) == "abc123"

    def test_from_header(self, monkeypatch):
        monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
        request = MagicMock()
        request.cookies = {}
        request.headers = {"X-Session-ID": "hdr_sid"}
        assert ma.session_id_from_request(request) == "hdr_sid"

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        assert ma.session_id_from_request(request) == ""


# Need httpx for transport error tests
import httpx
