"""Tests for app.fastapi_routes.market_account — uncovered branches (v3).

Focus: bind_market_auth_to_session, save/clear with DB fallback,
_authorization_from_request_resolved, _proxy_json retry/error branches,
_register_without_verification, resolve_valid_market_access_token,
login_market_with_password, _normalize_market_auth_payload, _market_auth_from_request,
_legacy_account_overview, and route handler edge cases.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.fastapi_routes import market_account as ma

# ========================= bind_market_auth_to_session ======================


class TestBindMarketAuthToSession:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_binds_token_to_session(self):
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        result = {"token": "tok1", "refresh_token": "rt1"}
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            token, refresh = ma.bind_market_auth_to_session(request, result)
        assert token == "tok1"
        assert refresh == "rt1"
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"

    def test_empty_token_skips_save(self):
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        result = {"token": "", "refresh_token": "rt1"}
        token, refresh = ma.bind_market_auth_to_session(request, result)
        assert token == ""
        assert "sid1" not in ma._MARKET_SESSION_TOKENS

    def test_no_token_key(self):
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        result = {}
        token, refresh = ma.bind_market_auth_to_session(request, result)
        assert token == ""
        assert refresh == ""


# ========================= save_session_market_token with DB ================


class TestSaveSessionMarketTokenWithDB:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_save_in_memory_only(self):
        """When DB is unavailable, token is saved in-memory only."""
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "tok1", "rt1")
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"
        assert ma._MARKET_SESSION_REFRESH_TOKENS["sid1"] == "rt1"

    def test_save_with_db_recoverable_error(self):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            ma.save_session_market_token("sid1", "tok1")
        assert ma._MARKET_SESSION_TOKENS["sid1"] == "tok1"

    def test_save_without_refresh_token(self):
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sid1", "tok1")
        assert "sid1" not in ma._MARKET_SESSION_REFRESH_TOKENS

    def test_save_empty_sid_skips(self):
        ma.save_session_market_token("", "tok1")
        assert not ma._MARKET_SESSION_TOKENS

    def test_save_empty_tok_skips(self):
        ma.save_session_market_token("sid1", "")
        assert "sid1" not in ma._MARKET_SESSION_TOKENS


# ========================= clear_session_market_token with DB ===============


class TestClearSessionMarketTokenWithDB:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_clear_with_db_recoverable_error(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "tok1"
        with patch("app.db.session.get_db", side_effect=RuntimeError("db error")):
            ma.clear_session_market_token("sid1")
        assert "sid1" not in ma._MARKET_SESSION_TOKENS

    def test_clear_empty_sid_noop(self):
        ma.clear_session_market_token("")
        # Should not crash


# ========================= session_market_token with DB fallback ============


class TestSessionMarketTokenWithDB:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_in_memory_token_returned(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "mem_tok"
        result = ma.session_market_token("sid1")
        assert result == "mem_tok"

    def test_empty_sid_returns_empty(self):
        result = ma.session_market_token("")
        assert result == ""

    def test_db_fallback_recoverable_error(self):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db error")):
            result = ma.session_market_token("sid1")
        assert result == ""


# ========================= session_market_refresh_token with DB fallback ====


class TestSessionMarketRefreshTokenWithDB:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_in_memory_refresh_token_returned(self):
        ma._MARKET_SESSION_REFRESH_TOKENS["sid1"] = "mem_rt"
        result = ma.session_market_refresh_token("sid1")
        assert result == "mem_rt"

    def test_empty_sid_returns_empty(self):
        result = ma.session_market_refresh_token("")
        assert result == ""


# ========================= latest_session_market_token =====================


class TestLatestSessionMarketToken:
    def test_returns_empty_on_db_error(self):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db error")):
            result = ma.latest_session_market_token()
        assert result == ""


# ========================= latest_session_market_refresh_token ==============


class TestLatestSessionMarketRefreshToken:
    def test_returns_empty_on_db_error(self):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db error")):
            result = ma.latest_session_market_refresh_token()
        assert result == ""


# ========================= _authorization_from_request_resolved ============


class TestAuthorizationFromRequestResolved:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    @pytest.mark.asyncio
    async def test_with_session_token_resolved(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "sess_tok"
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        with (
            patch("app.db.session.get_db", side_effect=ImportError("no db")),
            patch.object(ma, "resolve_valid_market_access_token", return_value="resolved_tok"),
        ):
            result = await ma._authorization_from_request_resolved(request, {})
        assert "resolved_tok" in result

    @pytest.mark.asyncio
    async def test_no_session_token_falls_back(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {"Authorization": "Bearer hdr_tok"}
        with (
            patch.object(ma, "resolve_valid_market_access_token", return_value=""),
        ):
            result = await ma._authorization_from_request_resolved(request, {})
        assert "hdr_tok" in result

    @pytest.mark.asyncio
    async def test_empty_session_falls_back(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        result = await ma._authorization_from_request_resolved(
            request, {"authorization": "body_tok"}
        )
        assert "body_tok" in result


# ========================= _proxy_json - retry/error branches ===============


class TestProxyJsonRetryBranches:
    @pytest.mark.asyncio
    async def test_successful_request(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "ok"}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test")
        assert result == {"data": "ok"}

    @pytest.mark.asyncio
    async def test_server_error_with_return_error_payload(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"detail": "internal error"}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test", return_error_payload=True)
        assert result["__proxy_error__"] is True
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_client_error_without_return_error_payload(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"detail": "bad request"}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test")
        assert isinstance(result, ma.JSONResponse)

    @pytest.mark.asyncio
    async def test_http_error_with_retry(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        monkeypatch.setenv("XCAGI_MARKET_HTTP_RETRIES", "2")
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test")
        assert isinstance(result, ma.JSONResponse)

    @pytest.mark.asyncio
    async def test_recoverable_error_returns_json_response(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=RuntimeError("unexpected"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test")
        assert isinstance(result, ma.JSONResponse)

    @pytest.mark.asyncio
    async def test_json_parse_failure_uses_text(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "plain text response"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test")
        assert result["detail"] == "plain text response"

    @pytest.mark.asyncio
    async def test_with_authorization_header(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await ma._proxy_json("GET", "/api/test", authorization="mytoken")
        assert result == {"ok": True}


# ========================= _register_without_verification ==================


class TestRegisterWithoutVerification:
    @pytest.mark.asyncio
    async def test_first_endpoint_succeeds(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        success_payload = {"data": {"access_token": "tok1"}}
        with patch.object(ma, "_proxy_json", return_value=success_payload):
            result = await ma._register_without_verification("u1", "pass", "a@b.com")
        assert result == success_payload

    @pytest.mark.asyncio
    async def test_first_fails_tries_second(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        error_payload = {"__proxy_error__": True, "status_code": 404}
        success_payload = {"data": {"access_token": "tok2"}}
        call_count = 0

        async def mock_proxy(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_payload
            return success_payload

        with patch.object(ma, "_proxy_json", side_effect=mock_proxy):
            result = await ma._register_without_verification("u1", "pass", "a@b.com")
        assert result == success_payload

    @pytest.mark.asyncio
    async def test_both_fail(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        error_payload = {"__proxy_error__": True, "status_code": 500}
        with patch.object(ma, "_proxy_json", return_value=error_payload):
            result = await ma._register_without_verification("u1", "pass", "a@b.com")
        assert result["__proxy_error__"] is True


# ========================= resolve_valid_market_access_token ===============


class TestResolveValidMarketAccessToken:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    @pytest.mark.asyncio
    async def test_no_token_returns_empty(self):
        result = await ma.resolve_valid_market_access_token("sid1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_demo_token_returned_directly(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "demo_market_token"
        with (
            patch("app.db.session.get_db", side_effect=ImportError("no db")),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=True,
            ),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "demo_market_token"

    @pytest.mark.asyncio
    async def test_valid_token_returns_token(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "valid_tok"
        with (
            patch("app.db.session.get_db", side_effect=ImportError("no db")),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=False,
            ),
            patch.object(ma, "_proxy_json", return_value={"user": {"id": 1}}),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "valid_tok"

    @pytest.mark.asyncio
    async def test_401_triggers_refresh(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "expired_tok"
        with (
            patch("app.db.session.get_db", side_effect=ImportError("no db")),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=False,
            ),
            patch.object(
                ma, "_proxy_json", return_value={"__proxy_error__": True, "status_code": 401}
            ),
            patch.object(ma, "refresh_session_market_token", return_value="new_tok"),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "new_tok"

    @pytest.mark.asyncio
    async def test_market_unreachable_returns_local_token(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "local_tok"
        with (
            patch("app.db.session.get_db", side_effect=ImportError("no db")),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=False,
            ),
            patch.object(
                ma,
                "_proxy_json",
                return_value=ma.JSONResponse({"error": "unreachable"}, status_code=502),
            ),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "local_tok"

    @pytest.mark.asyncio
    async def test_non_401_error_returns_local_token(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "local_tok"
        with (
            patch("app.db.session.get_db", side_effect=ImportError("no db")),
            patch(
                "app.application.surface_audit_demo_account.is_local_demo_market_token",
                return_value=False,
            ),
            patch.object(
                ma, "_proxy_json", return_value={"__proxy_error__": True, "status_code": 500}
            ),
        ):
            result = await ma.resolve_valid_market_access_token("sid1")
        assert result == "local_tok"


# ========================= login_market_with_password ======================


class TestLoginMarketWithPassword:
    @pytest.mark.asyncio
    async def test_demo_mode_login(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        with (
            patch(
                "app.application.surface_audit_demo_account.try_local_demo_market_login",
                return_value={"token": "demo_tok", "raw": {}},
            ),
            patch.object(ma, "_is_local_market_base", return_value=True),
        ):
            result = await ma.login_market_with_password("u", "p")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_normal_login_success(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        login_resp = {"data": {"access_token": "tok1", "refresh_token": "rt1"}}
        me_resp = {"user": {"id": 1, "username": "u"}}
        call_count = 0

        async def mock_proxy(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if "/api/auth/login" in path:
                return login_resp
            if "/api/auth/me" in path:
                return me_resp
            return {}

        with (
            patch(
                "app.application.surface_audit_demo_account.try_local_demo_market_login",
                return_value=None,
            ),
            patch.object(ma, "_proxy_json", side_effect=mock_proxy),
        ):
            result = await ma.login_market_with_password("u", "p")
        assert result["success"] is True
        assert result["token"] == "tok1"

    @pytest.mark.asyncio
    async def test_login_proxy_error(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        error_payload = {
            "__proxy_error__": True,
            "status_code": 401,
            "payload": {"detail": "invalid credentials"},
        }
        with (
            patch(
                "app.application.surface_audit_demo_account.try_local_demo_market_login",
                return_value=None,
            ),
            patch.object(ma, "_proxy_json", return_value=error_payload),
        ):
            result = await ma.login_market_with_password("u", "wrong_p")
        assert result["success"] is False


# ========================= _normalize_market_auth_payload ===================


class TestNormalizeMarketAuthPayload:
    @pytest.mark.asyncio
    async def test_normalizes_login_json(self):
        payload = {
            "data": {
                "access_token": "tok1",
                "refresh_token": "rt1",
                "user": {"id": 1, "username": "u", "is_enterprise": True, "is_admin": False},
            }
        }
        with patch.object(
            ma,
            "_proxy_json",
            return_value={"user": {"id": 1, "username": "u", "is_enterprise": True}},
        ):
            result = await ma._normalize_market_auth_payload(payload)
        assert result["token"] == "tok1"
        assert result["refresh_token"] == "rt1"
        assert result["is_enterprise"] is True

    @pytest.mark.asyncio
    async def test_empty_payload(self):
        with patch.object(ma, "_proxy_json", return_value={"user": {}}):
            result = await ma._normalize_market_auth_payload({})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_proxy_error_payload(self):
        payload = {
            "__proxy_error__": True,
            "status_code": 401,
            "payload": {"detail": "unauthorized"},
        }
        result = await ma._normalize_market_auth_payload(payload)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_json_response_payload(self):
        jr = ma.JSONResponse({"message": "unauthorized", "detail": "bad token"}, status_code=401)
        result = await ma._normalize_market_auth_payload(jr)
        assert result["success"] is False
        assert result["status_code"] == 401


# ========================= _market_auth_from_request =======================


class TestMarketAuthFromRequest:
    @pytest.fixture(autouse=True)
    def _clear_tokens(self):
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()
        yield
        ma._MARKET_SESSION_TOKENS.clear()
        ma._MARKET_SESSION_REFRESH_TOKENS.clear()

    def test_with_session_token(self):
        ma._MARKET_SESSION_TOKENS["sid1"] = "sess_tok"
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            result = ma._market_auth_from_request(request)
        assert result == "sess_tok"

    def test_with_header_token(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {"Authorization": "Bearer hdr_tok"}
        result = ma._market_auth_from_request(request)
        assert "hdr_tok" in result

    def test_no_token_returns_empty(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        result = ma._market_auth_from_request(request)
        assert result == ""


# ========================= _legacy_account_overview ========================


class TestLegacyAccountOverview:
    @pytest.mark.asyncio
    async def test_composes_from_apis(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        wallet_resp = {"wallet": {"balance": 100}}
        membership_resp = {"membership": {"level": "pro"}}
        call_count = 0

        async def mock_proxy(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if "wallet" in path:
                return wallet_resp
            if "membership" in path:
                return membership_resp
            return {}

        with patch.object(ma, "_proxy_json", side_effect=mock_proxy):
            result = await ma._legacy_account_overview("Bearer tok1")
        assert isinstance(result, dict)


# ========================= _error_message edge cases =======================


class TestErrorMessageEdgeCases:
    def test_500_internal_server_error_exact_match(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        result = ma._error_message({"detail": "Internal Server Error"}, 500)
        assert "500" in result
        assert "服务器内部错误" in result

    def test_500_with_non_internal_detail(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        result = ma._error_message({"detail": "Database connection failed"}, 500)
        assert "500" in result
        assert "Database connection failed" in result

    def test_400_with_error_key(self):
        result = ma._error_message({"error": "bad request"}, 400)
        assert result == "bad request"


# ========================= market_session_handoff route ====================


class TestMarketSessionHandoffRoute:
    @pytest.mark.asyncio
    async def test_no_user_with_desktop_token(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        with (
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
            patch.object(ma, "latest_session_market_token", return_value="desktop_tok"),
        ):
            result = await ma.market_session_handoff(request)
        assert result["success"] is True
        assert result["data"]["market_access_token"] == "desktop_tok"

    @pytest.mark.asyncio
    async def test_no_user_no_token(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        with (
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
            patch.object(ma, "latest_session_market_token", return_value=""),
        ):
            result = await ma.market_session_handoff(request)
        assert isinstance(result, ma.JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_with_user_and_valid_token(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=MagicMock(),
            ),
            patch.object(ma, "resolve_valid_market_access_token", return_value="valid_tok"),
            patch.object(ma, "session_market_refresh_token", return_value=""),
            patch.object(ma, "latest_session_market_refresh_token", return_value=""),
        ):
            result = await ma.market_session_handoff(request)
        assert result["success"] is True
        assert result["data"]["market_access_token"] == "valid_tok"

    @pytest.mark.asyncio
    async def test_recoverable_error_fallback(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        request = MagicMock()
        request.cookies = {"session_id": "sid1"}
        request.headers = {}
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                side_effect=RuntimeError("auth error"),
            ),
            patch.object(ma, "session_market_token", return_value="fallback_tok"),
            patch.object(ma, "latest_session_market_token", return_value=""),
        ):
            result = await ma.market_session_handoff(request)
        assert result["success"] is True
        assert result["data"]["market_access_token"] == "fallback_tok"

    @pytest.mark.asyncio
    async def test_recoverable_error_no_fallback(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://localhost:8765")
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                side_effect=RuntimeError("auth error"),
            ),
            patch.object(ma, "session_market_token", return_value=""),
            patch.object(ma, "latest_session_market_token", return_value=""),
        ):
            result = await ma.market_session_handoff(request)
        assert isinstance(result, ma.JSONResponse)
        assert result.status_code == 502
