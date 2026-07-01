"""Real-behavior tests for the OIDC provider (coverage uplift).

Targets ``app/infrastructure/auth/oidc_provider.py``.

The existing route-level tests (``tests/test_routes/test_oidc_auth.py``) cover
the happy callback path through FastAPI but mock ``exchange_oidc_authorization``
entirely, leaving the provider's own helpers (env getters, state TTL/exp
branches, discovery cache, authorize-URL building, token+userinfo exchange and
its error branches) untested. This file exercises those units directly.

All outbound HTTP is mocked at ``httpx.AsyncClient`` (an async context manager),
so tests are deterministic, offline and fast. Time is patched where the exp
branch matters; env is driven via ``monkeypatch``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.infrastructure.auth import oidc_provider as op

MODULE = "app.infrastructure.auth.oidc_provider"

# Every env var the module reads, so each test starts from a clean slate.
_OIDC_ENV_VARS = [
    "XCAGI_OIDC_ENABLED",
    "SECRET_KEY",
    "XCAGI_SECRET_KEY",
    "XCAGI_OIDC_ISSUER",
    "XCAGI_OIDC_CLIENT_ID",
    "XCAGI_OIDC_CLIENT_SECRET",
    "XCAGI_OIDC_REDIRECT_URI",
    "XCAGI_OIDC_SCOPES",
    "XCAGI_OIDC_FRONTEND_REDIRECT",
]


@pytest.fixture(autouse=True)
def _clean_oidc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _OIDC_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Discovery cache is module-global; reset so tests don't leak into each other.
    op._discovery_cache.clear()


def _make_async_client(get_responses=None, post_responses=None) -> MagicMock:
    """Build a MagicMock standing in for ``httpx.AsyncClient(...)``.

    Returns an object usable as ``async with httpx.AsyncClient(...) as client``.
    ``get_responses`` / ``post_responses`` are response objects returned by the
    awaited ``client.get`` / ``client.post`` calls (single object or iterable).
    """
    client = MagicMock()

    async def _aenter(_self=None):
        return client

    async def _aexit(*_a, **_kw):
        return False

    # The factory call returns an object whose __aenter__ yields ``client``.
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    if get_responses is not None:
        if isinstance(get_responses, (list, tuple)):
            client.get = AsyncMock(side_effect=list(get_responses))
        else:
            client.get = AsyncMock(return_value=get_responses)
    if post_responses is not None:
        if isinstance(post_responses, (list, tuple)):
            client.post = AsyncMock(side_effect=list(post_responses))
        else:
            client.post = AsyncMock(return_value=post_responses)

    factory = MagicMock(return_value=ctx)
    factory._client = client  # expose for assertions
    return factory


def _resp(json_data: Any) -> MagicMock:
    r = MagicMock()
    r.json = MagicMock(return_value=json_data)
    r.raise_for_status = MagicMock(return_value=None)
    return r


# ---------------------------------------------------------------------------
# oidc_enabled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "On", " on "])
def test_oidc_enabled_truthy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ENABLED", val)
    assert op.oidc_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "maybe"])
def test_oidc_enabled_falsy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ENABLED", val)
    assert op.oidc_enabled() is False


def test_oidc_enabled_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_OIDC_ENABLED", raising=False)
    assert op.oidc_enabled() is False


# ---------------------------------------------------------------------------
# _secret_key (dev fallback when too short / unset)
# ---------------------------------------------------------------------------


def test_secret_key_falls_back_when_unset() -> None:
    assert op._secret_key() == "xcagi-dev-oidc-state-key"


def test_secret_key_falls_back_when_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "short")  # < 16 chars -> fallback
    assert op._secret_key() == "xcagi-dev-oidc-state-key"


def test_secret_key_uses_secret_key_env_when_long_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_key = "a" * 20
    monkeypatch.setenv("SECRET_KEY", long_key)
    assert op._secret_key() == long_key


def test_secret_key_uses_xcagi_secret_key_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    long_key = "x" * 20
    monkeypatch.setenv("XCAGI_SECRET_KEY", long_key)
    assert op._secret_key() == long_key


# ---------------------------------------------------------------------------
# sign_oidc_state / verify_oidc_state round-trip + branches
# ---------------------------------------------------------------------------


def test_sign_verify_roundtrip_preserves_return_to() -> None:
    state = op.sign_oidc_state(return_to="/dashboard?tab=1")
    ok, rt = op.verify_oidc_state(state)
    assert ok is True
    assert rt == "/dashboard?tab=1"


def test_sign_oidc_state_truncates_return_to_to_512() -> None:
    long_rt = "/x" + "y" * 1000
    state = op.sign_oidc_state(return_to=long_rt)
    ok, rt = op.verify_oidc_state(state)
    assert ok is True
    assert len(rt) == 512
    assert rt == long_rt[:512]


def test_verify_state_no_dot_returns_false() -> None:
    ok, rt = op.verify_oidc_state("no-separator-here")
    assert ok is False
    assert rt == ""


def test_verify_state_empty_returns_false() -> None:
    ok, rt = op.verify_oidc_state("")
    assert ok is False
    assert rt == ""


def test_verify_state_bad_signature_returns_false() -> None:
    state = op.sign_oidc_state(return_to="/home")
    payload, _sig = state.rsplit(".", 1)
    tampered = f"{payload}.deadbeef"
    ok, rt = op.verify_oidc_state(tampered)
    assert ok is False
    assert rt == ""


def test_verify_state_payload_not_json_returns_false() -> None:
    # Build a state whose signature is valid but payload is not JSON, so the
    # json.JSONDecodeError branch (lines 53-56) executes.
    import hashlib
    import hmac

    bad_payload = "this-is-not-json"
    sig = hmac.new(op._secret_key().encode(), bad_payload.encode(), hashlib.sha256).hexdigest()
    state = f"{bad_payload}.{sig}"
    ok, rt = op.verify_oidc_state(state)
    assert ok is False
    assert rt == ""


def test_verify_state_expired_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sign at t=1000, verify at t=1000 + TTL + 1 so exp < now.
    monkeypatch.setattr(f"{MODULE}.time.time", lambda: 1000.0)
    state = op.sign_oidc_state(return_to="/late")
    monkeypatch.setattr(f"{MODULE}.time.time", lambda: 1000.0 + op._STATE_TTL_SECONDS + 1)
    ok, rt = op.verify_oidc_state(state)
    assert ok is False
    assert rt == ""


def test_verify_state_just_before_expiry_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.time.time", lambda: 5000.0)
    state = op.sign_oidc_state(return_to="/ok")
    # Exactly at exp boundary: exp == now -> NOT (exp < now) -> still valid.
    monkeypatch.setattr(f"{MODULE}.time.time", lambda: 5000.0 + op._STATE_TTL_SECONDS)
    ok, rt = op.verify_oidc_state(state)
    assert ok is True
    assert rt == "/ok"


# ---------------------------------------------------------------------------
# env getter helpers
# ---------------------------------------------------------------------------


def test_issuer_strips_and_trims_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "  https://idp.example/realms/x/  ")
    assert op._issuer() == "https://idp.example/realms/x"


def test_issuer_empty_when_unset() -> None:
    assert op._issuer() == ""


def test_client_id_and_secret_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "  cid  ")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_SECRET", "  sec  ")
    monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "  https://cb/  ")
    assert op._client_id() == "cid"
    assert op._client_secret() == "sec"
    assert op._redirect_uri() == "https://cb/"


def test_scopes_default_when_unset() -> None:
    assert op._scopes() == "openid profile email"


def test_scopes_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_SCOPES", "  openid roles  ")
    assert op._scopes() == "openid roles"


def test_frontend_redirect_default() -> None:
    assert op.frontend_redirect_path() == "/login"


def test_frontend_redirect_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "/sso-land")
    assert op.frontend_redirect_path() == "/sso-land"


def test_frontend_redirect_blank_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # Whitespace-only -> stripped to "" -> ``or "/login"`` fallback.
    monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "   ")
    assert op.frontend_redirect_path() == "/login"


# ---------------------------------------------------------------------------
# _discovery
# ---------------------------------------------------------------------------


async def test_discovery_empty_when_no_issuer() -> None:
    assert await op._discovery() == {}


async def test_discovery_fetches_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    doc = {"authorization_endpoint": "https://idp.example/auth"}
    factory = _make_async_client(get_responses=_resp(doc))
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        first = await op._discovery()
    assert first == doc
    # Second call must hit the cache (no new client constructed).
    factory2 = _make_async_client(get_responses=_resp({"never": "used"}))
    with patch(f"{MODULE}.httpx.AsyncClient", factory2):
        second = await op._discovery()
    assert second == doc
    factory2.assert_not_called()
    # The discovery URL was the well-known path.
    called_url = factory._client.get.call_args.args[0]
    assert called_url == "https://idp.example/realms/t/.well-known/openid-configuration"


async def test_discovery_propagates_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    resp = _resp({})
    resp.raise_for_status = MagicMock(side_effect=RuntimeError("502 bad gateway"))
    factory = _make_async_client(get_responses=resp)
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError, match="502"):
            await op._discovery()
    # A failed discovery must NOT poison the cache.
    assert "https://idp.example/realms/t" not in op._discovery_cache


# ---------------------------------------------------------------------------
# build_authorize_url / _build_authorize_url_async
# ---------------------------------------------------------------------------


async def test_build_authorize_url_uses_discovery_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "fhd-web")
    monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
    monkeypatch.setenv("XCAGI_OIDC_SCOPES", "openid email")
    op._discovery_cache["https://idp.example/realms/t"] = {
        "authorization_endpoint": "https://idp.example/custom/authorize"
    }
    url = await op.build_authorize_url(state="STATE123")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://idp.example/custom/authorize"
    )
    q = parse_qs(parsed.query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["fhd-web"]
    assert q["redirect_uri"] == ["https://app/cb"]
    assert q["scope"] == ["openid email"]
    assert q["state"] == ["STATE123"]


async def test_build_authorize_url_falls_back_to_keycloak_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "cid")
    # Discovery returns no authorization_endpoint -> fallback to Keycloak path.
    op._discovery_cache["https://idp.example/realms/t"] = {"foo": "bar"}
    url = await op.build_authorize_url(state="S")
    assert url.startswith("https://idp.example/realms/t/protocol/openid-connect/auth?")
    assert "state=S" in url


# ---------------------------------------------------------------------------
# exchange_oidc_authorization
# ---------------------------------------------------------------------------


async def test_exchange_success_returns_profile_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_SECRET", "shh")
    monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "https://app/cb")
    op._discovery_cache["https://idp.example/realms/t"] = {
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    tokens = {
        "access_token": "AT",
        "refresh_token": "RT",
        "id_token": "IDT",
    }
    profile = {"sub": "u1", "email": "u1@example.com"}
    factory = _make_async_client(get_responses=_resp(profile), post_responses=_resp(tokens))
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        result = await op.exchange_oidc_authorization("  the-code  ")

    assert result["profile"] == profile
    assert result["access_token"] == "AT"
    assert result["refresh_token"] == "RT"
    assert result["id_token"] == "IDT"

    # POST went to the token endpoint with stripped code + client_secret present.
    post_call = factory._client.post.call_args
    assert post_call.args[0] == "https://idp.example/token"
    sent = post_call.kwargs["data"]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the-code"
    assert sent["client_id"] == "cid"
    assert sent["redirect_uri"] == "https://app/cb"
    assert sent["client_secret"] == "shh"

    # GET userinfo carried the bearer token.
    get_call = factory._client.get.call_args
    assert get_call.args[0] == "https://idp.example/userinfo"
    assert get_call.kwargs["headers"]["Authorization"] == "Bearer AT"


async def test_exchange_omits_client_secret_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "cid")
    # No client secret set.
    op._discovery_cache["https://idp.example/realms/t"] = {}
    factory = _make_async_client(
        get_responses=_resp({"sub": "x"}),
        post_responses=_resp({"access_token": "AT"}),
    )
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        result = await op.exchange_oidc_authorization("c")
    sent = factory._client.post.call_args.kwargs["data"]
    assert "client_secret" not in sent
    assert result["access_token"] == "AT"
    # Missing refresh/id token fields default to "".
    assert result["refresh_token"] == ""
    assert result["id_token"] == ""


async def test_exchange_falls_back_to_keycloak_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    # Discovery present but lacks token/userinfo endpoints -> fallback paths.
    op._discovery_cache["https://idp.example/realms/t"] = {"misc": True}
    factory = _make_async_client(
        get_responses=_resp({"sub": "x"}),
        post_responses=_resp({"access_token": "AT"}),
    )
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        await op.exchange_oidc_authorization("c")
    assert (
        factory._client.post.call_args.args[0]
        == "https://idp.example/realms/t/protocol/openid-connect/token"
    )
    assert (
        factory._client.get.call_args.args[0]
        == "https://idp.example/realms/t/protocol/openid-connect/userinfo"
    )


async def test_exchange_raises_when_no_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    op._discovery_cache["https://idp.example/realms/t"] = {
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    factory = _make_async_client(
        get_responses=_resp({"sub": "x"}),
        post_responses=_resp({"token_type": "bearer"}),  # no access_token
    )
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError, match="access_token"):
            await op.exchange_oidc_authorization("c")
    # userinfo must NOT have been fetched after the missing-token raise.
    factory._client.get.assert_not_called()


async def test_exchange_token_endpoint_http_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    op._discovery_cache["https://idp.example/realms/t"] = {
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    bad = _resp({})
    bad.raise_for_status = MagicMock(side_effect=RuntimeError("401 unauthorized"))
    factory = _make_async_client(get_responses=_resp({"sub": "x"}), post_responses=bad)
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError, match="401"):
            await op.exchange_oidc_authorization("c")


async def test_exchange_non_dict_profile_coerced_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/t")
    op._discovery_cache["https://idp.example/realms/t"] = {
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    factory = _make_async_client(
        get_responses=_resp(["not", "a", "dict"]),  # userinfo returns a list
        post_responses=_resp({"access_token": "AT"}),
    )
    with patch(f"{MODULE}.httpx.AsyncClient", factory):
        result = await op.exchange_oidc_authorization("c")
    assert result["profile"] == {}
    assert result["access_token"] == "AT"


# ---------------------------------------------------------------------------
# exchange_code_for_userinfo (thin wrapper)
# ---------------------------------------------------------------------------


async def test_exchange_code_for_userinfo_returns_profile() -> None:
    profile = {"sub": "abc", "name": "Alice"}
    with patch(
        f"{MODULE}.exchange_oidc_authorization",
        new_callable=AsyncMock,
        return_value={"profile": profile, "access_token": "AT"},
    ):
        out = await op.exchange_code_for_userinfo("code")
    assert out == profile


async def test_exchange_code_for_userinfo_non_dict_profile_returns_empty() -> None:
    with patch(
        f"{MODULE}.exchange_oidc_authorization",
        new_callable=AsyncMock,
        return_value={"profile": None, "access_token": "AT"},
    ):
        out = await op.exchange_code_for_userinfo("code")
    assert out == {}
