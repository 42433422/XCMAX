"""Tests for app.application.enterprise_login_flow — coverage ramp."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.enterprise_login_flow import (
    _login_client_http_status,
    ensure_local_user_after_market,
    market_auth_error_response,
    resolve_market_username,
)

# ---------------------------------------------------------------------------
# _login_client_http_status
# ---------------------------------------------------------------------------


class TestLoginClientHttpStatus:
    def test_5xx_preserved(self):
        assert _login_client_http_status(500) == 500
        assert _login_client_http_status(502) == 502

    def test_4xx_mapped_to_200(self):
        assert _login_client_http_status(401) == 200
        assert _login_client_http_status(403) == 200
        assert _login_client_http_status(400) == 200

    def test_2xx_mapped_to_200(self):
        assert _login_client_http_status(200) == 200

    def test_invalid_type_returns_502(self):
        assert _login_client_http_status("bad") == 502

    def test_none_returns_502(self):
        assert _login_client_http_status(None) == 502


# ---------------------------------------------------------------------------
# market_auth_error_response
# ---------------------------------------------------------------------------


class TestMarketAuthErrorResponse:
    def test_5xx_status(self):
        result = market_auth_error_response({"status_code": 500, "message": "server error"})
        assert result.status_code == 500
        body = result.body
        assert b"MARKET_AUTH_UNAVAILABLE" in body

    def test_4xx_status(self):
        result = market_auth_error_response({"status_code": 401, "message": "bad creds"})
        assert result.status_code == 200  # 4xx mapped to 200
        body = result.body
        assert b"MARKET_AUTH_FAILED" in body

    def test_missing_status_code(self):
        result = market_auth_error_response({"message": "fail"})
        assert result.status_code == 502

    def test_default_message(self):
        result = market_auth_error_response({"status_code": 500})
        assert "修茈市场账号验证失败" in result.body.decode("utf-8")

    def test_includes_market_base_url(self):
        result = market_auth_error_response(
            {
                "status_code": 500,
                "message": "err",
                "market_base_url": "https://example.com",
            }
        )
        assert b"example.com" in result.body


# ---------------------------------------------------------------------------
# resolve_market_username
# ---------------------------------------------------------------------------


class TestResolveMarketUsername:
    def test_returns_username_from_blob(self):
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "alice", "phone": "", "email": ""},
        ):
            assert resolve_market_username({}) == "alice"

    def test_returns_phone_from_blob(self):
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "", "phone": "123", "email": ""},
        ):
            assert resolve_market_username({}) == "123"

    def test_returns_email_from_blob(self):
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "", "phone": "", "email": "a@b.com"},
        ):
            assert resolve_market_username({}) == "a@b.com"

    def test_falls_back_to_raw(self):
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "", "phone": "", "email": ""},
        ):
            result = resolve_market_username({"raw": {"username": "raw_user"}})
            assert result == "raw_user"

    def test_returns_empty_when_nothing(self):
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "", "phone": "", "email": ""},
        ):
            assert resolve_market_username({"raw": {}}) == ""


# ---------------------------------------------------------------------------
# ensure_local_user_after_market
# ---------------------------------------------------------------------------


class TestEnsureLocalUserAfterMarket:
    @pytest.mark.asyncio
    async def test_login_success_with_password(self):
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "token": "abc"}
        result, err = await ensure_local_user_after_market(
            username="alice",
            password="pass",
            market_result={},
            auth_app_service=auth_svc,
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is not None
        assert result.get("success") is True
        assert err is None

    @pytest.mark.asyncio
    async def test_login_fails_and_user_exists_with_password(self):
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        mock_user = MagicMock()
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
        ):
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_user
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result, err = await ensure_local_user_after_market(
                username="alice",
                password="pass",
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 200  # 401 mapped to 200

    @pytest.mark.asyncio
    async def test_database_error(self):
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch(
                "app.db.init_db.ensure_runtime_auth_bootstrap", side_effect=RuntimeError("db down")
            ),
        ):
            mock_get_db.side_effect = RuntimeError("db down")
            result, err = await ensure_local_user_after_market(
                username="alice",
                password="pass",
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 503

    @pytest.mark.asyncio
    async def test_jit_create_fails(self):
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
        ):
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            with patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"email": ""},
            ):
                result, err = await ensure_local_user_after_market(
                    username="newuser",
                    password=None,
                    market_result={},
                    auth_app_service=auth_svc,
                    jit_create_fn=MagicMock(return_value=False),
                    market_user_email_from_raw=MagicMock(return_value=""),
                )
        assert result is None
        assert err is not None
        assert err.status_code == 500
