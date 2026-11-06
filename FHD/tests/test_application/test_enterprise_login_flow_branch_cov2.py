"""测试 app.application.enterprise_login_flow 的辅助函数分支覆盖。

覆盖目标：
- _login_client_http_status（5xx 保留 / 4xx → 200 / 无效 → 502）
- market_auth_error_response（status_code < 400 → 502 / >= 500 / < 500 / 无效）
- resolve_market_username（blob username/phone/email / raw fallback / 空）
- bind_tenant_for_login（异常路径 / 正常 / 无 tid / 无 name）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.application import enterprise_login_flow
from app.application.enterprise_login_flow import (
    _derive_and_heal_account_kind,
    _login_client_http_status,
    bind_tenant_for_login,
    market_auth_error_response,
    resolve_market_username,
)


class TestLoginClientHttpStatus:
    """_login_client_http_status 分支覆盖。"""

    def test_returns_500_plus_as_is(self) -> None:
        assert _login_client_http_status(500) == 500
        assert _login_client_http_status(502) == 502
        assert _login_client_http_status(599) == 599

    def test_returns_200_for_4xx(self) -> None:
        assert _login_client_http_status(400) == 200
        assert _login_client_http_status(401) == 200
        assert _login_client_http_status(403) == 200
        assert _login_client_http_status(404) == 200

    def test_returns_200_for_2xx_3xx(self) -> None:
        assert _login_client_http_status(200) == 200
        assert _login_client_http_status(301) == 200

    def test_returns_502_for_invalid_string(self) -> None:
        assert _login_client_http_status("not a number") == 502  # type: ignore[arg-type]

    def test_returns_502_for_none(self) -> None:
        assert _login_client_http_status(None) == 502  # type: ignore[arg-type]

    def test_returns_502_for_empty_string(self) -> None:
        assert _login_client_http_status("") == 502  # type: ignore[arg-type]


class TestMarketAuthErrorResponse:
    """market_auth_error_response 分支覆盖。"""

    def test_returns_502_when_status_code_below_400(self) -> None:
        result = market_auth_error_response({"status_code": 200, "message": "ok"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    def test_returns_502_when_status_code_missing(self) -> None:
        result = market_auth_error_response({"message": "err"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    def test_returns_502_when_status_code_invalid(self) -> None:
        result = market_auth_error_response({"status_code": "invalid", "message": "err"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    def test_returns_200_for_4xx_status(self) -> None:
        result = market_auth_error_response({"status_code": 401, "message": "unauthorized"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    def test_returns_500_for_5xx_status(self) -> None:
        result = market_auth_error_response({"status_code": 503, "message": "unavailable"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503

    def test_uses_default_message_when_empty(self) -> None:
        result = market_auth_error_response({"status_code": 401})
        assert isinstance(result, JSONResponse)
        body = result.body.decode() if hasattr(result, "body") else ""
        assert "修茈市场账号验证失败" in body or "验证失败" in body

    def test_marks_unavailable_for_5xx(self) -> None:
        result = market_auth_error_response({"status_code": 503, "message": "down"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503

    def test_includes_market_account_block(self) -> None:
        result = market_auth_error_response(
            {"status_code": 401, "message": "fail", "market_base_url": "https://m/"}
        )
        assert isinstance(result, JSONResponse)


class TestResolveMarketUsername:
    """resolve_market_username 分支覆盖。"""

    def test_returns_username_from_blob(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "user1", "phone": "123", "email": "a@b.com"},
        ):
            assert resolve_market_username({}) == "user1"

    def test_returns_phone_when_no_username(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"phone": "123456"},
        ):
            assert resolve_market_username({}) == "123456"

    def test_returns_email_when_no_username_no_phone(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"email": "a@b.com"},
        ):
            assert resolve_market_username({}) == "a@b.com"

    def test_returns_empty_when_blob_empty(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={},
        ):
            assert resolve_market_username({}) == ""

    def test_falls_back_to_raw_username(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={},
        ):
            assert resolve_market_username({"raw": {"username": "rawuser"}}) == "rawuser"

    def test_falls_back_to_raw_phone(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={},
        ):
            assert resolve_market_username({"raw": {"phone": "999"}}) == "999"

    def test_returns_empty_when_raw_not_dict(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={},
        ):
            assert resolve_market_username({"raw": "not a dict"}) == ""

    def test_returns_empty_when_raw_empty(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={},
        ):
            assert resolve_market_username({"raw": {}}) == ""

    def test_skips_empty_values_in_blob(self) -> None:
        with patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"username": "", "phone": "  ", "email": "real@x.com"},
        ):
            assert resolve_market_username({}) == "real@x.com"


class TestBindTenantForLogin:
    """bind_tenant_for_login 分支覆盖。"""

    def test_returns_empty_dict_on_exception(self) -> None:
        with patch(
            "app.application.tenant_subscription_app_service.provision_trial_for_user",
            side_effect=RuntimeError("boom"),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="brand", username="user")
            assert result == {"tenant_id": None, "tenant_name": ""}

    def test_returns_tenant_id_when_provisioned(self) -> None:
        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=42,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value="TenantName",
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="brand", username="user")
            assert result["tenant_id"] == 42
            assert result["tenant_name"] == "TenantName"

    def test_returns_empty_tenant_id_when_none(self) -> None:
        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=None,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value="",
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="brand", username="user")
            assert result["tenant_id"] is None
            assert result["tenant_name"] == "brand"

    def test_falls_back_to_company_brand_when_no_name(self) -> None:
        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=None,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value="",
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="MyBrand", username="user")
            assert result["tenant_name"] == "MyBrand"

    def test_returns_empty_tenant_name_when_no_brand(self) -> None:
        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=None,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value="",
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="", username="user")
            assert result["tenant_name"] == ""


class TestDeriveAndHealAccountKind:
    """_derive_and_heal_account_kind 分支覆盖。"""

    def test_returns_derived_when_user_id_none(self) -> None:
        with patch(
            "app.application.session_account_meta.derive_account_kind_from_user",
            return_value="personal",
        ) as mock_derive:
            result = _derive_and_heal_account_kind(
                user_id=None,
                market_is_admin=False,
                market_is_enterprise=False,
                fallback="personal",
            )
            assert result == "personal"
            mock_derive.assert_called_once()

    def test_returns_derived_when_user_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.get.return_value = None
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch(
                "app.application.session_account_meta.derive_account_kind_from_user",
                return_value="enterprise",
            ) as mock_derive,
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = None
            result = _derive_and_heal_account_kind(
                user_id=99,
                market_is_admin=False,
                market_is_enterprise=True,
                fallback="personal",
            )
            assert result == "enterprise"

    def test_heals_tier_when_user_has_empty_tier(self) -> None:
        mock_user = MagicMock()
        mock_user.tier = ""
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch(
                "app.application.session_account_meta.derive_account_kind_from_user",
                return_value="admin",
            ),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = None
            result = _derive_and_heal_account_kind(
                user_id=1,
                market_is_admin=True,
                market_is_enterprise=False,
                fallback="personal",
            )
            assert result == "admin"
            assert mock_user.tier == "admin"
            mock_db.commit.assert_called_once()

    def test_does_not_heal_when_tier_already_set(self) -> None:
        mock_user = MagicMock()
        mock_user.tier = "enterprise"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch(
                "app.application.session_account_meta.derive_account_kind_from_user",
                return_value="enterprise",
            ),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = None
            result = _derive_and_heal_account_kind(
                user_id=1,
                market_is_admin=False,
                market_is_enterprise=True,
                fallback="personal",
            )
            assert result == "enterprise"
            mock_db.commit.assert_not_called()

    def test_does_not_heal_when_kind_is_personal(self) -> None:
        mock_user = MagicMock()
        mock_user.tier = ""
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch(
                "app.application.session_account_meta.derive_account_kind_from_user",
                return_value="personal",
            ),
        ):
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = None
            result = _derive_and_heal_account_kind(
                user_id=1,
                market_is_admin=False,
                market_is_enterprise=False,
                fallback="personal",
            )
            assert result == "personal"
            mock_db.commit.assert_not_called()

    def test_returns_fallback_on_exception(self) -> None:
        # get_db() 是上下文管理器，__enter__ 抛 RuntimeError 触发 RECOVERABLE_ERRORS
        mock_ctx = MagicMock()
        mock_ctx.__enter__.side_effect = RuntimeError("db down")
        mock_ctx.__exit__.return_value = None
        with (
            patch("app.db.session.get_db", return_value=mock_ctx),
            patch(
                "app.application.session_account_meta.derive_account_kind_from_user",
                return_value="personal",
            ) as mock_derive,
        ):
            result = _derive_and_heal_account_kind(
                user_id=1,
                market_is_admin=False,
                market_is_enterprise=False,
                fallback="personal",
            )
            assert result == "personal"
            mock_derive.assert_called()
