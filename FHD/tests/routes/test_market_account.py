"""Tests for app.fastapi_routes.market_account — coverage ramp.

Covers helper functions, route endpoints, token management, and error paths.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app.fastapi_routes.market_account as ma
from app.fastapi_routes.market_account import router


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    return TestClient(app_with_router, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clear_token_caches():
    """Clear in-memory token caches between tests."""
    ma._MARKET_SESSION_TOKENS.clear()
    ma._MARKET_SESSION_REFRESH_TOKENS.clear()
    yield
    ma._MARKET_SESSION_TOKENS.clear()
    ma._MARKET_SESSION_REFRESH_TOKENS.clear()


# ---------------------------------------------------------------------------
# _auth_header
# ---------------------------------------------------------------------------


class TestAuthHeader:
    def test_strips_and_adds_bearer(self) -> None:
        assert ma._auth_header("mytoken") == "Bearer mytoken"

    def test_already_has_bearer(self) -> None:
        assert ma._auth_header("Bearer mytoken") == "Bearer mytoken"

    def test_strips_authorization_prefix(self) -> None:
        assert ma._auth_header("Authorization: mytoken") == "Bearer mytoken"

    def test_empty_string(self) -> None:
        assert ma._auth_header("") == ""

    def test_none_input(self) -> None:
        assert ma._auth_header(None) == ""

    def test_bearer_case_insensitive(self) -> None:
        assert ma._auth_header("bearer mytoken") == "bearer mytoken"


# ---------------------------------------------------------------------------
# _normalize_bearer_token
# ---------------------------------------------------------------------------


class TestNormalizeBearerToken:
    def test_strips_bearer_prefix(self) -> None:
        assert ma._normalize_bearer_token("Bearer mytoken") == "mytoken"

    def test_no_prefix(self) -> None:
        assert ma._normalize_bearer_token("mytoken") == "mytoken"

    def test_empty(self) -> None:
        assert ma._normalize_bearer_token("") == ""

    def test_none(self) -> None:
        assert ma._normalize_bearer_token(None) == ""


# ---------------------------------------------------------------------------
# _market_base_url
# ---------------------------------------------------------------------------


class TestMarketBaseUrl:
    def test_default(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            # Remove env var if set
            import os

            os.environ.pop("XCAGI_MARKET_BASE_URL", None)
            url = ma._market_base_url()
        assert "127.0.0.1:8765" in url or url.startswith("http")

    def test_custom_env(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "http://custom:9999"}):
            assert ma._market_base_url() == "http://custom:9999"

    def test_trailing_slash_stripped(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "http://custom:9999/"}):
            assert ma._market_base_url() == "http://custom:9999"


# ---------------------------------------------------------------------------
# _body_snippet
# ---------------------------------------------------------------------------


class TestBodySnippet:
    def test_dict_payload(self) -> None:
        result = ma._body_snippet({"key": "value"})
        assert "key" in result

    def test_long_payload_truncated(self) -> None:
        result = ma._body_snippet({"key": "x" * 500})
        assert len(result) <= 241  # 240 + "…"

    def test_string_payload(self) -> None:
        result = ma._body_snippet("hello")
        assert result == "hello"

    def test_none_payload(self) -> None:
        result = ma._body_snippet(None)
        assert result == ""


# ---------------------------------------------------------------------------
# _error_message
# ---------------------------------------------------------------------------


class TestErrorMessage:
    def test_dict_with_detail(self) -> None:
        msg = ma._error_message({"detail": "bad request"}, 400)
        assert msg == "bad request"

    def test_dict_with_message(self) -> None:
        msg = ma._error_message({"message": "error occurred"}, 400)
        assert msg == "error occurred"

    def test_dict_with_list_detail(self) -> None:
        msg = ma._error_message({"detail": [{"msg": "field required"}]}, 422)
        assert "field required" in msg

    def test_500_error(self) -> None:
        msg = ma._error_message({"detail": "internal error"}, 500)
        assert "500" in msg
        assert "XCAGI_MARKET_BASE_URL" in msg

    def test_no_detail_returns_http_status(self) -> None:
        msg = ma._error_message({}, 403)
        assert "403" in msg


# ---------------------------------------------------------------------------
# _proxy_error_http_status
# ---------------------------------------------------------------------------


class TestProxyErrorHttpStatus:
    def test_valid_proxy_error(self) -> None:
        result = ma._proxy_error_http_status({"__proxy_error__": True, "status_code": 502})
        assert result == 502

    def test_non_proxy_error(self) -> None:
        result = ma._proxy_error_http_status({"detail": "error"})
        assert result is None

    def test_non_dict(self) -> None:
        result = ma._proxy_error_http_status("error")
        assert result is None

    def test_invalid_status_code(self) -> None:
        result = ma._proxy_error_http_status({"__proxy_error__": True, "status_code": "abc"})
        assert result is None


# ---------------------------------------------------------------------------
# _token_from_auth_response
# ---------------------------------------------------------------------------


class TestTokenFromAuthResponse:
    def test_data_access_token(self) -> None:
        payload = {"data": {"access_token": "tok123"}}
        assert ma._token_from_auth_response(payload) == "tok123"

    def test_data_token(self) -> None:
        payload = {"data": {"token": "tok456"}}
        assert ma._token_from_auth_response(payload) == "tok456"

    def test_top_level_token(self) -> None:
        payload = {"token": "tok789"}
        assert ma._token_from_auth_response(payload) == "tok789"

    def test_nested_tokens_dict(self) -> None:
        payload = {"data": {"tokens": {"access_token": "nested_tok"}}}
        assert ma._token_from_auth_response(payload) == "nested_tok"

    def test_no_token_returns_empty(self) -> None:
        payload = {"data": {}}
        assert ma._token_from_auth_response(payload) == ""

    def test_non_dict_returns_empty(self) -> None:
        assert ma._token_from_auth_response("not a dict") == ""

    def test_empty_token_skipped(self) -> None:
        payload = {"data": {"access_token": ""}, "token": "  ", "access_token": "real_tok"}
        assert ma._token_from_auth_response(payload) == "real_tok"


# ---------------------------------------------------------------------------
# _refresh_token_from_auth_response
# ---------------------------------------------------------------------------


class TestRefreshTokenFromAuthResponse:
    def test_data_refresh_token(self) -> None:
        payload = {"data": {"refresh_token": "rt123"}}
        assert ma._refresh_token_from_auth_response(payload) == "rt123"

    def test_top_level_refresh_token(self) -> None:
        payload = {"refresh_token": "rt456"}
        assert ma._refresh_token_from_auth_response(payload) == "rt456"

    def test_nested_tokens(self) -> None:
        payload = {"data": {"tokens": {"refresh_token": "nested_rt"}}}
        assert ma._refresh_token_from_auth_response(payload) == "nested_rt"

    def test_no_refresh_token(self) -> None:
        assert ma._refresh_token_from_auth_response({}) == ""


# ---------------------------------------------------------------------------
# _user_blob_from_market_payload
# ---------------------------------------------------------------------------


class TestUserBlobFromMarketPayload:
    def test_top_level_user(self) -> None:
        payload = {"user": {"id": 1, "username": "test"}}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 1

    def test_data_user(self) -> None:
        payload = {"data": {"user": {"id": 2, "username": "test2"}}}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 2

    def test_data_is_user(self) -> None:
        payload = {"data": {"id": 3, "username": "test3"}}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 3

    def test_top_level_is_user(self) -> None:
        payload = {"id": 4, "username": "test4"}
        result = ma._user_blob_from_market_payload(payload)
        assert result["id"] == 4

    def test_non_dict(self) -> None:
        assert ma._user_blob_from_market_payload("not a dict") == {}

    def test_empty_dict(self) -> None:
        assert ma._user_blob_from_market_payload({}) == {}


# ---------------------------------------------------------------------------
# _market_identity_from_payloads
# ---------------------------------------------------------------------------


class TestMarketIdentityFromPayloads:
    def test_extracts_identity(self) -> None:
        payload = {"user": {"is_enterprise": True, "is_admin": True, "id": 1}}
        is_ent, is_admin, blob = ma._market_identity_from_payloads(payload)
        assert is_ent is True
        assert is_admin is True
        assert blob["id"] == 1

    def test_skips_proxy_errors(self) -> None:
        payload1 = {"__proxy_error__": True, "status_code": 502}
        payload2 = {"user": {"is_enterprise": False, "is_admin": False}}
        is_ent, is_admin, blob = ma._market_identity_from_payloads(payload1, payload2)
        assert is_ent is False
        assert is_admin is False

    def test_no_valid_payloads(self) -> None:
        is_ent, is_admin, blob = ma._market_identity_from_payloads(
            {"__proxy_error__": True}, {}
        )
        assert is_ent is False
        assert is_admin is False
        assert blob == {}


# ---------------------------------------------------------------------------
# _is_local_market_base
# ---------------------------------------------------------------------------


class TestIsLocalMarketBase:
    def test_localhost(self) -> None:
        assert ma._is_local_market_base("http://localhost:8765") is True

    def test_127_0_0_1(self) -> None:
        assert ma._is_local_market_base("http://127.0.0.1:8765") is True

    def test_remote(self) -> None:
        assert ma._is_local_market_base("https://xiu-ci.com") is False


# ---------------------------------------------------------------------------
# _degraded_account_overview
# ---------------------------------------------------------------------------


class TestDegradedAccountOverview:
    def test_structure(self) -> None:
        result = ma._degraded_account_overview("service down")
        assert result["degraded"] is True
        assert result["market_unreachable"] is True
        assert "service down" in result["sync_warning"]
        assert isinstance(result["wallet"], dict)
        assert isinstance(result["membership"], dict)


# ---------------------------------------------------------------------------
# _merge_live_overview_fields
# ---------------------------------------------------------------------------


class TestMergeLiveOverviewFields:
    def test_merges_wallet(self) -> None:
        data: dict = {"wallet": {"balance": 0}}
        live = {"wallet": {"balance": 100}}
        ma._merge_live_overview_fields(data, live)
        assert data["wallet"]["balance"] == 100

    def test_merges_llm(self) -> None:
        data: dict = {"llm": {"providers": []}}
        live = {"llm": {"providers": [{"name": "openai"}]}}
        ma._merge_live_overview_fields(data, live)
        assert len(data["llm"]["providers"]) == 1

    def test_skips_none_fields(self) -> None:
        data: dict = {"wallet": {"balance": 50}}
        live = {"wallet": None, "plan": None}
        ma._merge_live_overview_fields(data, live)
        assert data["wallet"]["balance"] == 50


# ---------------------------------------------------------------------------
# _transport_error_message
# ---------------------------------------------------------------------------


class TestTransportErrorMessage:
    def test_read_timeout(self) -> None:
        import httpx

        msg, code = ma._transport_error_message(httpx.ReadTimeout("timeout"))
        assert "超时" in msg
        assert code == 503

    def test_other_error(self) -> None:
        msg, code = ma._transport_error_message(ConnectionError("refused"))
        assert "无法连接" in msg
        assert code == 502


# ---------------------------------------------------------------------------
# _looks_like_verification_required
# ---------------------------------------------------------------------------


class TestLooksLikeVerificationRequired:
    def test_verification_code(self) -> None:
        assert ma._looks_like_verification_required({"detail": "verification code required"}) is True

    def test_chinese_verification(self) -> None:
        assert ma._looks_like_verification_required({"detail": "需要验证码"}) is True

    def test_no_verification(self) -> None:
        assert ma._looks_like_verification_required({"detail": "wrong password"}) is False


# ---------------------------------------------------------------------------
# Token management functions
# ---------------------------------------------------------------------------


class TestSaveSessionMarketToken:
    def test_saves_to_memory(self) -> None:
        ma.save_session_market_token("sess1", "tok1")
        assert ma._MARKET_SESSION_TOKENS["sess1"] == "tok1"

    def test_saves_with_refresh(self) -> None:
        ma.save_session_market_token("sess1", "tok1", "rt1")
        assert ma._MARKET_SESSION_REFRESH_TOKENS["sess1"] == "rt1"

    def test_empty_sid_skipped(self) -> None:
        ma.save_session_market_token("", "tok1")
        assert "" not in ma._MARKET_SESSION_TOKENS

    def test_empty_tok_skipped(self) -> None:
        ma.save_session_market_token("sess1", "")
        assert "sess1" not in ma._MARKET_SESSION_TOKENS

    def test_db_persist_error_handled(self) -> None:
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.save_session_market_token("sess1", "tok1")
        # Should still save to memory
        assert ma._MARKET_SESSION_TOKENS["sess1"] == "tok1"


class TestClearSessionMarketToken:
    def test_clears_from_memory(self) -> None:
        ma._MARKET_SESSION_TOKENS["sess1"] = "tok1"
        ma._MARKET_SESSION_REFRESH_TOKENS["sess1"] = "rt1"
        ma.clear_session_market_token("sess1")
        assert "sess1" not in ma._MARKET_SESSION_TOKENS
        assert "sess1" not in ma._MARKET_SESSION_REFRESH_TOKENS

    def test_empty_sid_noop(self) -> None:
        ma.clear_session_market_token("")
        # Should not crash

    def test_db_clear_error_handled(self) -> None:
        ma._MARKET_SESSION_TOKENS["sess1"] = "tok1"
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            ma.clear_session_market_token("sess1")
        assert "sess1" not in ma._MARKET_SESSION_TOKENS


class TestSessionMarketToken:
    def test_returns_from_memory(self) -> None:
        ma._MARKET_SESSION_TOKENS["sess1"] = "tok1"
        assert ma.session_market_token("sess1") == "tok1"

    def test_empty_sid_returns_empty(self) -> None:
        assert ma.session_market_token("") == ""

    def test_fallback_to_db(self) -> None:
        mock_row = MagicMock()
        mock_row.market_access_token = "db_tok"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_row
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_ctx):
            result = ma.session_market_token("sess2")
        assert result == "db_tok"

    def test_db_error_returns_empty(self) -> None:
        with patch("app.db.session.get_db", side_effect=ImportError("no db")):
            result = ma.session_market_token("sess2")
        assert result == ""


class TestSessionMarketRefreshToken:
    def test_returns_from_memory(self) -> None:
        ma._MARKET_SESSION_REFRESH_TOKENS["sess1"] = "rt1"
        assert ma.session_market_refresh_token("sess1") == "rt1"

    def test_empty_sid_returns_empty(self) -> None:
        assert ma.session_market_refresh_token("") == ""


# ---------------------------------------------------------------------------
# Route endpoints
# ---------------------------------------------------------------------------


class TestMarketRegister:
    def test_missing_fields_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/market/register", json={})
        assert resp.status_code == 400

    def test_missing_password_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/market/register", json={"username": "u", "email": "e@e.com"}
        )
        assert resp.status_code == 400

    def test_registration_failure(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.register_market_user",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "用户已存在"},
        ):
            resp = client.post(
                "/api/market/register",
                json={"username": "u", "password": "p", "email": "e@e.com"},
            )
        assert resp.status_code == 400

    def test_registration_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account.register_market_user",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "token": "tok123",
                    "refresh_token": "rt123",
                    "market_base_url": "http://localhost",
                },
            ),
            patch(
                "app.fastapi_routes.market_account.bind_market_auth_to_session",
                return_value=("tok123", "rt123"),
            ),
        ):
            resp = client.post(
                "/api/market/register",
                json={"username": "u", "password": "p", "email": "e@e.com"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestMarketLogin:
    def test_missing_fields_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/market/login", json={})
        assert resp.status_code == 400

    def test_login_failure(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.login_market_with_password",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "密码错误"},
        ):
            resp = client.post(
                "/api/market/login",
                json={"username": "u", "password": "wrong"},
            )
        assert resp.status_code == 403

    def test_login_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "token": "tok123",
                    "refresh_token": "rt123",
                    "market_base_url": "http://localhost",
                    "raw": {},
                },
            ),
            patch(
                "app.fastapi_routes.market_account.bind_market_auth_to_session",
                return_value=("tok123", "rt123"),
            ),
        ):
            resp = client.post(
                "/api/market/login",
                json={"username": "u", "password": "p"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestMarketSendPhoneCode:
    def test_missing_phone_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/market/send-phone-code", json={})
        assert resp.status_code == 400

    def test_send_success(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.send_market_phone_code",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "验证码已发送"},
        ):
            resp = client.post(
                "/api/market/send-phone-code", json={"phone": "13800138000"}
            )
        assert resp.status_code == 200

    def test_send_failure(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.send_market_phone_code",
            new_callable=AsyncMock,
            return_value={"success": False, "status_code": 502, "message": "服务不可用"},
        ):
            resp = client.post(
                "/api/market/send-phone-code", json={"phone": "13800138000"}
            )
        assert resp.status_code == 502


class TestMarketLoginWithPhoneCode:
    def test_missing_fields_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/market/login-with-phone-code", json={})
        assert resp.status_code == 400

    def test_login_failure(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.login_market_with_phone_code",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "message": "验证码错误",
                "error_code": "MARKET_AUTH_FAILED",
            },
        ):
            resp = client.post(
                "/api/market/login-with-phone-code",
                json={"phone": "13800138000", "code": "0000"},
            )
        assert resp.status_code == 401

    def test_login_success(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.login_market_with_phone_code",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "token": "tok123",
                "refresh_token": "rt123",
                "market_base_url": "http://localhost",
            },
        ):
            resp = client.post(
                "/api/market/login-with-phone-code",
                json={"phone": "13800138000", "code": "1234"},
            )
        assert resp.status_code == 200


class TestMarketAccountSync:
    def test_missing_authorization_returns_400(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="",
        ):
            resp = client.post("/api/market/account-sync", json={})
        assert resp.status_code == 400

    def test_authorization_from_body(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"data": {"user": {"id": 1}}},
            ),
            patch(
                "app.fastapi_routes.market_account.save_session_market_token",
            ),
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="sess1",
            ),
        ):
            resp = client.post(
                "/api/market/account-sync",
                json={"authorization": "Bearer test-token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_authorization_from_header(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"data": {"user": {"id": 1}}},
            ),
            patch(
                "app.fastapi_routes.market_account.save_session_market_token",
            ),
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="sess1",
            ),
        ):
            resp = client.post(
                "/api/market/account-sync",
                json={},
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 200


class TestMarketStatus:
    def test_market_reachable(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ):
            resp = client.get("/api/market/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_market_unreachable(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value=JSONResponse(
                {"success": False, "message": "unreachable"}, status_code=502
            ),
        ):
            resp = client.get("/api/market/status")
        assert resp.status_code == 502


class TestMarketPaymentPlans:
    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._market_auth_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"plans": []},
            ),
        ):
            resp = client.get("/api/market/payment/plans")
        assert resp.status_code == 200

    def test_proxy_error(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._market_auth_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={
                    "__proxy_error__": True,
                    "status_code": 502,
                    "payload": {"detail": "bad gateway"},
                },
            ),
            patch(
                "app.fastapi_routes.market_account._error_message",
                return_value="市场服务返回 502",
            ),
        ):
            resp = client.get("/api/market/payment/plans")
        assert resp.status_code == 502


class TestMarketPaymentOrders:
    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._market_auth_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"orders": []},
            ),
        ):
            resp = client.get("/api/market/payment/orders")
        assert resp.status_code == 200

    def test_with_status_filter(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._market_auth_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"orders": []},
            ) as mock_proxy,
        ):
            resp = client.get("/api/market/payment/orders?status=paid")
        assert resp.status_code == 200
        call_path = mock_proxy.call_args[0][1]
        assert "status=paid" in call_path


class TestMarketPaymentQuery:
    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._market_auth_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"status": "paid"},
            ),
        ):
            resp = client.get("/api/market/payment/query/ORDER123")
        assert resp.status_code == 200


class TestMarketWalletOverview:
    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._market_auth_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"wallet": {"balance": 100}},
            ),
        ):
            resp = client.get("/api/market/wallet/overview")
        assert resp.status_code == 200


class TestMarketAccountOverview:
    def test_no_authorization_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account._authorization_from_request_resolved",
            new_callable=AsyncMock,
            return_value="",
        ):
            resp = client.post("/api/market/account-overview", json={})
        assert resp.status_code == 401

    def test_degraded_on_proxy_error(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value=JSONResponse(
                    {"success": False, "message": "unreachable"}, status_code=502
                ),
            ),
        ):
            resp = client.post("/api/market/account-overview", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"].get("degraded") is True or data["data"].get("market_unreachable") is True

    def test_authorization_resolve_error(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account._authorization_from_request_resolved",
            new_callable=AsyncMock,
            side_effect=RuntimeError("resolve failed"),
        ):
            resp = client.post("/api/market/account-overview", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"].get("degraded") is True


class TestMarketLlmCatalog:
    def test_no_authorization_returns_401(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account._authorization_from_request_resolved",
            new_callable=AsyncMock,
            return_value="",
        ):
            resp = client.post("/api/market/llm-catalog", json={})
        assert resp.status_code == 401

    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"providers": [{"name": "openai"}]},
            ),
        ):
            resp = client.post("/api/market/llm-catalog", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_get_endpoint(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account._authorization_from_request_resolved",
                new_callable=AsyncMock,
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"providers": []},
            ),
        ):
            resp = client.get("/api/market/llm-catalog")
        assert resp.status_code == 200


class TestMarketDevCreateAccount:
    def test_short_password_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/market/dev-create-account", json={"password": "12345"}
        )
        assert resp.status_code == 400

    def test_registration_proxy_error(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value=JSONResponse(
                {"success": False, "message": "unreachable"}, status_code=502
            ),
        ):
            resp = client.post("/api/market/dev-create-account", json={})
        assert resp.status_code == 502

    def test_registration_conflict_falls_back_to_login(self, client: TestClient) -> None:
        call_count = 0

        async def mock_proxy(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "__proxy_error__": True,
                    "status_code": 409,
                    "payload": {"detail": "用户名已存在"},
                }
            if call_count == 2:
                return {"token": "login_tok", "data": {"access_token": "login_tok"}}
            if call_count == 3:
                return {"data": {"user": {"id": 1}}}
            return {}

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            side_effect=mock_proxy,
        ), patch(
            "app.fastapi_routes.market_account._error_message",
            return_value="用户名已存在",
        ):
            resp = client.post("/api/market/dev-create-account", json={})
        assert resp.status_code == 200


class TestMarketSessionHandoff:
    def test_no_user_no_token_returns_404(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.market_account.latest_session_market_token",
                return_value="",
            ),
        ):
            resp = client.get("/api/market/session-handoff")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# send_market_reset_password_code / reset_market_password_with_code
# ---------------------------------------------------------------------------


class TestSendMarketResetPasswordCode:
    def test_invalid_email(self) -> None:
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            ma.send_market_reset_password_code("")
        )
        assert result["success"] is False

    def test_no_at_sign(self) -> None:
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            ma.send_market_reset_password_code("notanemail")
        )
        assert result["success"] is False


class TestResetMarketPasswordWithCode:
    def test_invalid_email(self) -> None:
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            ma.reset_market_password_with_code("", "1234", "newpass")
        )
        assert result["success"] is False

    def test_short_code(self) -> None:
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            ma.reset_market_password_with_code("a@b.com", "12", "newpass")
        )
        assert result["success"] is False

    def test_short_password(self) -> None:
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            ma.reset_market_password_with_code("a@b.com", "1234", "12")
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _market_http_timeout / _market_http_retries
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    def test_default_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("XCAGI_MARKET_HTTP_TIMEOUT", None)
            assert ma._market_http_timeout() == 20.0

    def test_custom_timeout(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": "30"}):
            assert ma._market_http_timeout() == 30.0

    def test_invalid_timeout(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_TIMEOUT": "abc"}):
            assert ma._market_http_timeout() == 20.0

    def test_default_retries(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("XCAGI_MARKET_HTTP_RETRIES", None)
            assert ma._market_http_retries() == 1

    def test_custom_retries(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MARKET_HTTP_RETRIES": "3"}):
            assert ma._market_http_retries() == 3

