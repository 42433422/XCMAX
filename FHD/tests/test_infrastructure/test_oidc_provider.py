"""Branch-coverage tests for app.infrastructure.auth.oidc_provider.

Covers: oidc_enabled, _secret_key, sign_oidc_state, verify_oidc_state,
env readers, _discovery (cache + empty issuer), build_authorize_url,
exchange_oidc_authorization, exchange_code_for_userinfo.
Focus on signature verification branches, expiry, and error paths.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.auth import oidc_provider

# ---------------------------------------------------------------------------
# oidc_enabled
# ---------------------------------------------------------------------------


class TestOidcEnabled:
    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "true")
        assert oidc_provider.oidc_enabled() is True

    def test_enabled_1(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "1")
        assert oidc_provider.oidc_enabled() is True

    def test_enabled_yes(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "yes")
        assert oidc_provider.oidc_enabled() is True

    def test_enabled_on(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "on")
        assert oidc_provider.oidc_enabled() is True

    def test_disabled_false(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "false")
        assert oidc_provider.oidc_enabled() is False

    def test_disabled_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "")
        assert oidc_provider.oidc_enabled() is False

    def test_disabled_unset(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OIDC_ENABLED", raising=False)
        assert oidc_provider.oidc_enabled() is False

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ENABLED", "TRUE")
        assert oidc_provider.oidc_enabled() is True


# ---------------------------------------------------------------------------
# _secret_key
# ---------------------------------------------------------------------------


class TestSecretKey:
    def test_uses_secret_key_env(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "a-very-long-secret-key-value")
        monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
        assert oidc_provider._secret_key() == "a-very-long-secret-key-value"

    def test_uses_xcagi_secret_key_env(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("XCAGI_SECRET_KEY", "xcagi-long-secret-key-value")
        assert oidc_provider._secret_key() == "xcagi-long-secret-key-value"

    def test_short_key_uses_dev_fallback(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "short")
        monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
        assert oidc_provider._secret_key() == "xcagi-dev-oidc-state-key"

    def test_empty_key_uses_dev_fallback(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "")
        monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
        assert oidc_provider._secret_key() == "xcagi-dev-oidc-state-key"

    def test_no_key_uses_dev_fallback(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
        assert oidc_provider._secret_key() == "xcagi-dev-oidc-state-key"


# ---------------------------------------------------------------------------
# sign_oidc_state / verify_oidc_state
# ---------------------------------------------------------------------------


class TestSignVerifyState:
    def test_sign_and_verify_valid(self):
        state = oidc_provider.sign_oidc_state(return_to="/dashboard")
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is True
        assert return_to == "/dashboard"

    def test_sign_without_return_to(self):
        state = oidc_provider.sign_oidc_state()
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is True
        assert return_to == ""

    def test_verify_empty_state(self):
        ok, return_to = oidc_provider.verify_oidc_state("")
        assert ok is False
        assert return_to == ""

    def test_verify_none_state(self):
        ok, return_to = oidc_provider.verify_oidc_state(None)
        assert ok is False
        assert return_to == ""

    def test_verify_no_dot(self):
        ok, return_to = oidc_provider.verify_oidc_state("nodot")
        assert ok is False
        assert return_to == ""

    def test_verify_invalid_signature(self):
        state = oidc_provider.sign_oidc_state(return_to="/x")
        # Tamper with the signature
        payload, _ = state.rsplit(".", 1)
        tampered = f"{payload}.invalidsignature"
        ok, return_to = oidc_provider.verify_oidc_state(tampered)
        assert ok is False
        assert return_to == ""

    def test_verify_expired_state(self):
        # Create a state with past expiry by manipulating time
        payload = json.dumps({"exp": int(time.time()) - 100, "rt": "/old"})
        sig = hmac.new(
            oidc_provider._secret_key().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        state = f"{payload}.{sig}"
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is False
        assert return_to == ""

    def test_verify_invalid_json_payload(self):
        sig = hmac.new(
            oidc_provider._secret_key().encode(), b"not-json", hashlib.sha256
        ).hexdigest()
        state = f"not-json.{sig}"
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is False
        assert return_to == ""

    def test_verify_missing_exp_field(self):
        payload = json.dumps({"rt": "/x"})
        sig = hmac.new(
            oidc_provider._secret_key().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        state = f"{payload}.{sig}"
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is False
        assert return_to == ""

    def test_verify_exp_zero(self):
        payload = json.dumps({"exp": 0, "rt": "/x"})
        sig = hmac.new(
            oidc_provider._secret_key().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        state = f"{payload}.{sig}"
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is False

    def test_verify_strips_whitespace(self):
        state = oidc_provider.sign_oidc_state(return_to="/x")
        ok, return_to = oidc_provider.verify_oidc_state(f"  {state}  ")
        assert ok is True

    def test_return_to_truncated_to_512(self):
        long_path = "/" + "a" * 600
        state = oidc_provider.sign_oidc_state(return_to=long_path)
        ok, return_to = oidc_provider.verify_oidc_state(state)
        assert ok is True
        assert len(return_to) <= 512


# ---------------------------------------------------------------------------
# env readers
# ---------------------------------------------------------------------------


class TestEnvReaders:
    def test_issuer(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com/")
        assert oidc_provider._issuer() == "https://idp.example.com"

    def test_issuer_empty(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OIDC_ISSUER", raising=False)
        assert oidc_provider._issuer() == ""

    def test_client_id(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "my-client")
        assert oidc_provider._client_id() == "my-client"

    def test_client_secret(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_SECRET", "secret")
        assert oidc_provider._client_secret() == "secret"

    def test_redirect_uri(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        assert oidc_provider._redirect_uri() == "https://app/cb"

    def test_scopes_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OIDC_SCOPES", raising=False)
        assert oidc_provider._scopes() == "openid profile email"

    def test_scopes_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_SCOPES", "openid email groups")
        assert oidc_provider._scopes() == "openid email groups"

    def test_frontend_redirect_path_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OIDC_FRONTEND_REDIRECT", raising=False)
        assert oidc_provider.frontend_redirect_path() == "/login"

    def test_frontend_redirect_path_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "/custom")
        assert oidc_provider.frontend_redirect_path() == "/custom"

    def test_frontend_redirect_path_empty_returns_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "")
        assert oidc_provider.frontend_redirect_path() == "/login"

    def test_frontend_redirect_path_whitespace_returns_default(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "   ")
        assert oidc_provider.frontend_redirect_path() == "/login"


# ---------------------------------------------------------------------------
# _discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_empty_issuer_returns_empty(self, monkeypatch):
        monkeypatch.delenv("XCAGI_OIDC_ISSUER", raising=False)
        # Clear cache
        oidc_provider._discovery_cache.clear()
        result = await oidc_provider._discovery()
        assert result == {}

    @pytest.mark.asyncio
    async def test_fetches_discovery_doc(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        oidc_provider._discovery_cache.clear()
        mock_response = MagicMock()
        mock_response.json.return_value = {"authorization_endpoint": "https://idp/auth"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await oidc_provider._discovery()
        assert result["authorization_endpoint"] == "https://idp/auth"
        # Verify cached
        assert "https://idp.example.com" in oidc_provider._discovery_cache

    @pytest.mark.asyncio
    async def test_uses_cached_discovery(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {"cached": True}
        result = await oidc_provider._discovery()
        assert result == {"cached": True}


# ---------------------------------------------------------------------------
# build_authorize_url
# ---------------------------------------------------------------------------


class TestBuildAuthorizeUrl:
    @pytest.mark.asyncio
    async def test_with_discovery_endpoint(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "authorization_endpoint": "https://idp.example.com/auth"
        }
        url = await oidc_provider.build_authorize_url(state="mystate")
        assert "https://idp.example.com/auth" in url
        assert "state=mystate" in url
        assert "client_id=client" in url

    @pytest.mark.asyncio
    async def test_fallback_endpoint_when_missing(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        # Cache a non-empty dict without authorization_endpoint so fallback path is taken.
        # (An empty dict is falsy and would trigger a real network fetch.)
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "issuer": "https://idp.example.com"
        }
        url = await oidc_provider.build_authorize_url(state="st")
        assert "https://idp.example.com/protocol/openid-connect/auth" in url


# ---------------------------------------------------------------------------
# exchange_oidc_authorization
# ---------------------------------------------------------------------------


class TestExchangeOidcAuthorization:
    @pytest.mark.asyncio
    async def test_successful_exchange(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_SECRET", "secret")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {
            "access_token": "atk",
            "refresh_token": "rtk",
            "id_token": "itk",
        }
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = {"sub": "user1", "email": "u@e.com"}
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await oidc_provider.exchange_oidc_authorization("code123")

        assert result["access_token"] == "atk"
        assert result["refresh_token"] == "rtk"
        assert result["id_token"] == "itk"
        assert result["profile"]["sub"] == "user1"

    @pytest.mark.asyncio
    async def test_no_client_secret_omitted(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.delenv("XCAGI_OIDC_CLIENT_SECRET", raising=False)
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "atk"}
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = {"sub": "user1"}
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await oidc_provider.exchange_oidc_authorization("code")
            # Verify client_secret not in posted data
            posted_data = mock_client.post.call_args.kwargs.get("data", {})
            assert "client_secret" not in posted_data

    @pytest.mark.asyncio
    async def test_fallback_endpoints_when_missing(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {}

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "atk"}
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = {"sub": "user1"}
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await oidc_provider.exchange_oidc_authorization("code")
            posted_url = mock_client.post.call_args.args[0]
            assert "protocol/openid-connect/token" in posted_url
            get_url = mock_client.get.call_args.args[0]
            assert "protocol/openid-connect/userinfo" in get_url

    @pytest.mark.asyncio
    async def test_no_access_token_raises(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": ""}
        token_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="access_token"):
                await oidc_provider.exchange_oidc_authorization("code")

    @pytest.mark.asyncio
    async def test_non_dict_profile_returns_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "atk"}
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = ["not", "a", "dict"]
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await oidc_provider.exchange_oidc_authorization("code")
        assert result["profile"] == {}

    @pytest.mark.asyncio
    async def test_empty_code_stripped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "atk"}
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = {"sub": "u"}
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await oidc_provider.exchange_oidc_authorization("  code  ")
            posted_data = mock_client.post.call_args.kwargs.get("data", {})
            assert posted_data["code"] == "code"


# ---------------------------------------------------------------------------
# exchange_code_for_userinfo
# ---------------------------------------------------------------------------


class TestExchangeCodeForUserinfo:
    @pytest.mark.asyncio
    async def test_returns_profile_dict(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "atk"}
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = {"sub": "u1", "email": "u@e.com"}
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            profile = await oidc_provider.exchange_code_for_userinfo("code")
        assert profile["sub"] == "u1"

    @pytest.mark.asyncio
    async def test_non_dict_profile_returns_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "client")
        monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
        oidc_provider._discovery_cache.clear()
        oidc_provider._discovery_cache["https://idp.example.com"] = {
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "atk"}
        token_resp.raise_for_status = MagicMock()

        userinfo_resp = MagicMock()
        userinfo_resp.json.return_value = "not-a-dict"
        userinfo_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=userinfo_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            profile = await oidc_provider.exchange_code_for_userinfo("code")
        assert profile == {}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_discovery_cache():
    """Clear discovery cache before and after each test."""
    oidc_provider._discovery_cache.clear()
    yield
    oidc_provider._discovery_cache.clear()
