"""Tests for app.fastapi_routes.mobile_api — mobile auth, me, health endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mobile_api import (
    MobileLoginRequest,
    MobileRefreshRequest,
    _parse_web_auth_login_response,
    _user_public_dict,
    _web_login_error_message,
    router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_mobile():
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app_with_mobile):
    return TestClient(app_with_mobile, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _parse_web_auth_login_response
# ---------------------------------------------------------------------------


class TestParseWebAuthLoginResponse:
    def test_json_response_bytes(self):
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={"success": True, "session_id": "sid1"})
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is True
        assert status == 200

    def test_json_response_empty_body(self):
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={})
        resp.body = b""
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is False

    def test_dict_passthrough(self):
        payload, status = _parse_web_auth_login_response({"success": True})
        assert payload["success"] is True
        assert status == 200

    def test_unknown_type(self):
        payload, status = _parse_web_auth_login_response(42)
        assert payload["success"] is False

    def test_memoryview_body(self):
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={"success": True})
        raw = resp.body
        if isinstance(raw, bytes):
            resp.body = memoryview(raw)
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is True

    def test_none_status_code_defaults_200(self):
        """When status_code is None, default to 200."""
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={"success": True})
        resp.status_code = None  # type: ignore[assignment]
        payload, status = _parse_web_auth_login_response(resp)
        assert status == 200


# ---------------------------------------------------------------------------
# _web_login_error_message
# ---------------------------------------------------------------------------


class TestWebLoginErrorMessage:
    def test_error_dict_with_message(self):
        msg = _web_login_error_message({"error": {"message": "bad creds"}})
        assert msg == "bad creds"

    def test_error_dict_no_message(self):
        msg = _web_login_error_message({"error": {"message": ""}})
        assert msg == "登录失败"

    def test_top_level_message(self):
        msg = _web_login_error_message({"message": "账号禁用"})
        assert msg == "账号禁用"

    def test_empty_message(self):
        msg = _web_login_error_message({"message": ""})
        assert msg == "登录失败"

    def test_no_message_key(self):
        msg = _web_login_error_message({"other": "data"})
        assert msg == "登录失败"


# ---------------------------------------------------------------------------
# _user_public_dict
# ---------------------------------------------------------------------------


class TestUserPublicDict:
    def test_basic_fields(self):
        user = MagicMock()
        user.id = 1
        user.username = "testuser"
        user.display_name = "Test User"
        user.email = "test@example.com"
        user.role = "admin"
        user.is_active = True
        user.wx_avatar_url = None
        with patch(
            "app.utils.user_avatar_storage.public_avatar_url", return_value="/avatar/default.png"
        ):
            result = _user_public_dict(user)
        assert result["id"] == 1
        assert result["username"] == "testuser"
        assert result["role"] == "admin"
        assert result["is_active"] is True

    def test_with_wx_avatar_url(self):
        user = MagicMock()
        user.id = 2
        user.username = "avataruser"
        user.display_name = "Avatar User"
        user.email = "a@b.com"
        user.role = "user"
        user.is_active = True
        user.wx_avatar_url = "https://example.com/avatar.jpg"
        with patch(
            "app.utils.user_avatar_storage.public_avatar_url",
            return_value="https://example.com/avatar.jpg",
        ):
            result = _user_public_dict(user)
        assert result["avatar_url"] == "https://example.com/avatar.jpg"


# ---------------------------------------------------------------------------
# MobileLoginRequest / MobileRefreshRequest
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_mobile_login_request_defaults(self):
        body = MobileLoginRequest(username="u", password="p")
        assert body.account_kind == "enterprise"

    def test_mobile_login_request_validation(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MobileLoginRequest(username="", password="p")

    def test_mobile_refresh_request_validation(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MobileRefreshRequest(refresh_token="short")

    def test_mobile_login_request_custom_kind(self):
        body = MobileLoginRequest(username="u", password="p", account_kind="personal")
        assert body.account_kind == "personal"


# ---------------------------------------------------------------------------
# /api/mobile/v1/health
# ---------------------------------------------------------------------------


class TestMobileHealth:
    def test_health(self, client):
        resp = client.get("/api/mobile/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["status"] == "ok"


# ---------------------------------------------------------------------------
# /api/mobile/v1/auth/refresh
# ---------------------------------------------------------------------------


class TestMobileAuthRefresh:
    def test_invalid_token(self, client):
        with patch(
            "app.fastapi_routes.mobile_api.refresh_mobile_access_token",
            return_value=None,
        ):
            resp = client.post(
                "/api/mobile/v1/auth/refresh",
                json={"refresh_token": "invalid_token_12345"},
            )
        assert resp.status_code == 401

    def test_valid_token(self, client):
        with patch(
            "app.fastapi_routes.mobile_api.refresh_mobile_access_token",
            return_value={"access_token": "new_at", "refresh_token": "new_rt"},
        ):
            resp = client.post(
                "/api/mobile/v1/auth/refresh",
                json={"refresh_token": "valid_refresh_token_123"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "expires_in" in data["data"]


# ---------------------------------------------------------------------------
# /api/mobile/v1/host/discover-hint
# ---------------------------------------------------------------------------


class TestMobileHostDiscoverHint:
    def test_success(self, client):
        mock_info = MagicMock()
        mock_info.model_dump.return_value = {"ip": "192.168.1.1", "port": 5100}
        with (
            patch(
                "app.fastapi_routes.lan_routes.host_info",
                new_callable=AsyncMock,
                return_value=mock_info,
            ),
            patch(
                "app.utils.listen_port.resolve_listen_port",
                return_value=5100,
            ),
        ):
            resp = client.get("/api/mobile/v1/host/discover-hint")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["api_port"] == 5100


# ---------------------------------------------------------------------------
# /api/mobile/v1/auth/login  (unit-level logic test)
# ---------------------------------------------------------------------------


class TestMobileAuthLoginLogic:
    """Test the login flow logic at the unit level by testing _parse_web_auth_login_response
    and _web_login_error_message which are the core parsing helpers."""

    def test_parse_failed_login_response(self):
        """When web auth returns failure, _parse_web_auth_login_response extracts it."""
        from fastapi.responses import JSONResponse

        resp = JSONResponse(
            content={"success": False, "message": "bad creds"},
            status_code=401,
        )
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is False
        assert status == 401

    def test_error_message_extraction(self):
        """_web_login_error_message extracts meaningful error from payload."""
        msg = _web_login_error_message({"success": False, "error": {"message": "密码错误"}})
        assert msg == "密码错误"


# ---------------------------------------------------------------------------
# /api/mobile/v1/me  (unit-level logic test)
# ---------------------------------------------------------------------------


class TestMobileMeLogic:
    """Test the /me endpoint helper logic at the unit level."""

    def test_user_public_dict_fields(self):
        user = MagicMock()
        user.id = 1
        user.username = "meuser"
        user.display_name = "Me User"
        user.email = "me@test.com"
        user.role = "admin"
        user.is_active = True
        user.wx_avatar_url = None
        with patch(
            "app.utils.user_avatar_storage.public_avatar_url", return_value="/avatar/default.png"
        ):
            result = _user_public_dict(user)
        assert result["id"] == 1
        assert result["username"] == "meuser"
        assert result["email"] == "me@test.com"
