"""Coverage tests for app.fastapi_routes.domains.auth.routes.

Targets previously-uncovered units:
  * MFA endpoints: auth_mfa_setup / auth_mfa_enable / auth_mfa_disable
    (lines ~145-211) — success paths plus every error branch
    (no session, user-not-found, missing secret, bad TOTP).
  * auth_token_refresh (lines ~217-225) — success + invalid-token branch.
  * auth_login web_tokens issuance (lines ~782-783) — INFRA_TRANSIENT except
    path when issue_web_tokens raises.
  * auth_qr_issue account_kind branch (line ~946).

Routes are exercised by direct function calls with all external deps mocked
(DB, account_security TOTP helpers, web_jwt), keeping the tests offline and
deterministic. Patches target the binding actually used:
  * resolve_session_user is imported at module load → patched on routes module.
  * get_db / account_security / web_jwt are function-local imports → patched at
    their origin modules.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_db_cm(user_obj):
    """Build a context-manager mock whose ``get(User, id)`` returns user_obj."""
    db = MagicMock()
    db.get.return_value = user_obj
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def _mk_user(uid=7, username="alice"):
    u = MagicMock()
    u.id = uid
    u.username = username
    return u


# ---------------------------------------------------------------------------
# auth_mfa_setup  (lines ~145-163)
# ---------------------------------------------------------------------------


class TestAuthMfaSetup:
    def test_no_session_returns_unauthorized_200(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_setup

        with patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=None,
        ):
            result = auth_mfa_setup(MagicMock())
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    def test_success_sets_secret_and_commits(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_setup

        user = _mk_user()
        db_user = MagicMock()
        db_user.username = "alice"
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.account_security.generate_totp_secret",
                return_value="SECRET32",
            ),
            patch(
                "app.application.account_security.provisioning_uri",
                return_value="otpauth://x",
            ),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_setup(MagicMock())

        assert result["success"] is True
        assert result["data"]["secret"] == "SECRET32"
        assert result["data"]["otpauth_uri"] == "otpauth://x"
        # secret persisted on the ORM row + committed
        assert db_user.totp_secret == "SECRET32"
        db.commit.assert_called_once()

    def test_user_not_found_in_db_returns_unauthorized(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_setup

        user = _mk_user()
        db = _fake_db_cm(None)  # db.get → None

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.account_security.generate_totp_secret",
                return_value="SECRET32",
            ),
            patch(
                "app.application.account_security.provisioning_uri",
                return_value="otpauth://x",
            ),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_setup(MagicMock())

        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# auth_mfa_enable  (lines ~169-188)
# ---------------------------------------------------------------------------


class TestAuthMfaEnable:
    def test_no_session_returns_unauthorized_200(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_enable

        with patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=None,
        ):
            result = auth_mfa_enable(MagicMock(), {"code": "123456"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    def test_missing_secret_returns_400(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_enable

        user = _mk_user()
        db_user = MagicMock()
        db_user.totp_secret = ""  # secret not yet generated
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.application.account_security.verify_totp", return_value=True),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_enable(MagicMock(), {"code": "000000"})

        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        db.commit.assert_not_called()

    def test_wrong_code_returns_400(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_enable

        user = _mk_user()
        db_user = MagicMock()
        db_user.totp_secret = "SECRET32"
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.application.account_security.verify_totp", return_value=False),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_enable(MagicMock(), {"totp_code": "999999"})

        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        db.commit.assert_not_called()

    def test_success_enables_mfa(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_enable

        user = _mk_user()
        db_user = MagicMock()
        db_user.totp_secret = "SECRET32"
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.application.account_security.verify_totp", return_value=True),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_enable(MagicMock(), {"code": "123456"})

        assert result == {"success": True, "message": "MFA 已开启"}
        assert db_user.mfa_enabled is True
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# auth_mfa_disable  (lines ~194-211)
# ---------------------------------------------------------------------------


class TestAuthMfaDisable:
    def test_no_session_returns_unauthorized_200(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_disable

        with patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=None,
        ):
            result = auth_mfa_disable(MagicMock(), {})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    def test_user_not_found_returns_unauthorized(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_disable

        user = _mk_user()
        db = _fake_db_cm(None)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_disable(MagicMock(), {})

        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
        db.commit.assert_not_called()

    def test_enabled_wrong_code_returns_400(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_disable

        user = _mk_user()
        db_user = MagicMock()
        db_user.mfa_enabled = True
        db_user.totp_secret = "SECRET32"
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.application.account_security.verify_totp", return_value=False),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_disable(MagicMock(), {"code": "000000"})

        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        db.commit.assert_not_called()

    def test_enabled_correct_code_disables(self):
        from app.fastapi_routes.domains.auth.routes import auth_mfa_disable

        user = _mk_user()
        db_user = MagicMock()
        db_user.mfa_enabled = True
        db_user.totp_secret = "SECRET32"
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.application.account_security.verify_totp", return_value=True),
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_disable(MagicMock(), {"code": "123456"})

        assert result == {"success": True, "message": "MFA 已关闭"}
        assert db_user.mfa_enabled is False
        assert db_user.totp_secret is None
        db.commit.assert_called_once()

    def test_not_enabled_skips_verify(self):
        """When mfa not enabled, verify_totp is short-circuited (no code needed)."""
        from app.fastapi_routes.domains.auth.routes import auth_mfa_disable

        user = _mk_user()
        db_user = MagicMock()
        db_user.mfa_enabled = False
        db_user.totp_secret = "SECRET32"
        db = _fake_db_cm(db_user)

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=user,
            ),
            patch("app.application.account_security.verify_totp") as mock_verify,
            patch("app.db.session.get_db", return_value=db),
        ):
            result = auth_mfa_disable(MagicMock(), {})

        assert result == {"success": True, "message": "MFA 已关闭"}
        # mfa_enabled was falsy → `and` short-circuits before verify_totp
        mock_verify.assert_not_called()
        assert db_user.mfa_enabled is False
        assert db_user.totp_secret is None
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# auth_token_refresh  (lines ~217-225)
# ---------------------------------------------------------------------------


class TestAuthTokenRefresh:
    def test_success_returns_tokens(self):
        from app.fastapi_routes.domains.auth.routes import auth_token_refresh

        tokens = {"access_token": "a", "refresh_token": "r"}
        with patch(
            "app.security.web_jwt.refresh_web_access_token",
            return_value=tokens,
        ) as mock_refresh:
            result = auth_token_refresh({"refresh_token": "  old-rt  "})

        assert result == {"success": True, "data": tokens}
        # body is stripped before passing through
        mock_refresh.assert_called_once_with("old-rt")

    def test_invalid_token_returns_401(self):
        from app.fastapi_routes.domains.auth.routes import auth_token_refresh

        with patch(
            "app.security.web_jwt.refresh_web_access_token",
            return_value=None,
        ):
            result = auth_token_refresh({"refresh_token": "bad"})

        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    def test_empty_body_treated_as_invalid(self):
        from app.fastapi_routes.domains.auth.routes import auth_token_refresh

        with patch(
            "app.security.web_jwt.refresh_web_access_token",
            return_value=None,
        ) as mock_refresh:
            result = auth_token_refresh({})

        assert isinstance(result, JSONResponse)
        assert result.status_code == 401
        mock_refresh.assert_called_once_with("")


# ---------------------------------------------------------------------------
# auth_qr_issue — account_kind branch  (line ~946)
# ---------------------------------------------------------------------------


class TestAuthQrIssueAccountKind:
    @pytest.mark.asyncio
    async def test_account_kind_in_body_normalized_and_forwarded(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_issue

        request = MagicMock()
        request.headers = {"User-Agent": "ua"}
        with (
            patch(
                "app.security.auth_qr_login.issue_auth_qr",
                return_value={"qr_id": "q1", "poll_secret": "s1"},
            ) as mock_issue,
            patch(
                "app.application.session_account_meta.normalize_account_kind",
                return_value="personal",
            ) as mock_norm,
        ):
            result = await auth_qr_issue(request, {"account_kind": "personal"})

        assert result["success"] is True
        assert result["data"]["qr_id"] == "q1"
        mock_norm.assert_called_once()
        # account_kind makes it into the kwargs forwarded to issue_auth_qr
        _, kwargs = mock_issue.call_args
        assert kwargs["account_kind"] == "personal"
        assert kwargs["client_hint"] == "ua"


# ---------------------------------------------------------------------------
# auth_login — web_tokens issuance success + INFRA_TRANSIENT except branch
# (lines ~770-788)
# ---------------------------------------------------------------------------


class TestAuthLoginWebTokens:
    def _patches(self, run_login_return):
        """Common patch set for auth_login; returns a context-manager list."""
        return [
            patch(
                "app.application.auth_app_service.get_auth_app_service",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=run_login_return),
            ),
            patch(
                "app.application.session_account_meta.normalize_account_kind",
                return_value="enterprise",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new=MagicMock(),
            ),
            patch(
                "app.mod_sdk.product_skus.resolve_product_sku",
                return_value="enterprise",
            ),
        ]

    @pytest.mark.asyncio
    async def test_web_tokens_attached_on_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        result_payload = {
            "success": True,
            "user": {"id": 5, "username": "bob"},
            "account_kind": "enterprise",
            "session_id": "sid-9",
        }
        web_tokens = {"access_token": "AT", "refresh_token": "RT"}

        with contextlib.ExitStack() as stack:
            for cm in self._patches((result_payload, None)):
                stack.enter_context(cm)
            mock_issue = stack.enter_context(
                patch("app.security.web_jwt.issue_web_tokens", return_value=web_tokens)
            )
            request = MagicMock()
            resp = await auth_login(request, {"username": "bob", "password": "pw"})

        assert isinstance(resp, JSONResponse)
        mock_issue.assert_called_once()
        # web_tokens injected into the result dict that becomes the response body
        assert result_payload["web_tokens"] == web_tokens

    @pytest.mark.asyncio
    async def test_web_tokens_exception_is_swallowed(self):
        """issue_web_tokens raising INFRA_TRANSIENT (RuntimeError) must not 500."""
        from app.fastapi_routes.domains.auth.routes import auth_login

        result_payload = {
            "success": True,
            "user": {"id": 6, "username": "carol"},
            "account_kind": "enterprise",
            "session_id": "sid-10",
        }
        with contextlib.ExitStack() as stack:
            for cm in self._patches((result_payload, None)):
                stack.enter_context(cm)
            mock_issue = stack.enter_context(
                patch(
                    "app.security.web_jwt.issue_web_tokens",
                    side_effect=RuntimeError("jwt backend down"),
                )
            )
            request = MagicMock()
            resp = await auth_login(request, {"username": "carol", "password": "pw"})

        assert isinstance(resp, JSONResponse)
        mock_issue.assert_called_once()
        # exception swallowed → no web_tokens key added
        assert "web_tokens" not in result_payload

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_invalid_input(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        resp = await auth_login(request, {"username": "", "password": ""})
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 200
