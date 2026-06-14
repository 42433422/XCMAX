"""OIDC 企业 SSO（Keycloak / 通用 IdP）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, cast
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 600
_discovery_cache: dict[str, Any] = {}


def oidc_enabled() -> bool:
    return (os.environ.get("XCAGI_OIDC_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _secret_key() -> str:
    key = (os.environ.get("SECRET_KEY") or os.environ.get("XCAGI_SECRET_KEY") or "").strip()
    if len(key) < 16:
        key = "xcagi-dev-oidc-state-key"
    return key


def sign_oidc_state(*, return_to: str = "") -> str:
    exp = int(time.time()) + _STATE_TTL_SECONDS
    payload = json.dumps({"exp": exp, "rt": (return_to or "")[:512]}, separators=(",", ":"))
    sig = hmac.new(_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_oidc_state(state: str) -> tuple[bool, str]:
    raw = (state or "").strip()
    if "." not in raw:
        return False, ""
    payload_raw, sig = raw.rsplit(".", 1)
    expected = hmac.new(_secret_key().encode(), payload_raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, ""
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return False, ""
    if int(payload.get("exp") or 0) < int(time.time()):
        return False, ""
    return True, str(payload.get("rt") or "")


def _issuer() -> str:
    return (os.environ.get("XCAGI_OIDC_ISSUER") or "").strip().rstrip("/")


def _client_id() -> str:
    return (os.environ.get("XCAGI_OIDC_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.environ.get("XCAGI_OIDC_CLIENT_SECRET") or "").strip()


def _redirect_uri() -> str:
    return (os.environ.get("XCAGI_OIDC_REDIRECT_URI") or "").strip()


def _scopes() -> str:
    return (os.environ.get("XCAGI_OIDC_SCOPES") or "openid profile email").strip()


def frontend_redirect_path() -> str:
    return (os.environ.get("XCAGI_OIDC_FRONTEND_REDIRECT") or "/login").strip() or "/login"


async def _discovery() -> dict[str, Any]:
    issuer = _issuer()
    if not issuer:
        return {}
    cached = _discovery_cache.get(issuer)
    if cached:
        return cast("dict[str, Any]", cached)
    url = f"{issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        res = await client.get(url)
        res.raise_for_status()
        data = res.json()
    _discovery_cache[issuer] = data
    return cast("dict[str, Any]", data)


async def build_authorize_url(*, state: str) -> str:
    return await _build_authorize_url_async(state=state)


async def _build_authorize_url_async(*, state: str) -> str:
    disc = await _discovery()
    auth_ep = str(disc.get("authorization_endpoint") or "").strip()
    if not auth_ep:
        auth_ep = f"{_issuer()}/protocol/openid-connect/auth"
    q = urlencode(
        {
            "response_type": "code",
            "client_id": _client_id(),
            "redirect_uri": _redirect_uri(),
            "scope": _scopes(),
            "state": state,
        }
    )
    return f"{auth_ep}?{q}"


async def exchange_code_for_userinfo(code: str) -> dict[str, Any]:
    disc = await _discovery()
    token_ep = str(disc.get("token_endpoint") or "").strip()
    if not token_ep:
        token_ep = f"{_issuer()}/protocol/openid-connect/token"
    userinfo_ep = str(disc.get("userinfo_endpoint") or "").strip()
    if not userinfo_ep:
        userinfo_ep = f"{_issuer()}/protocol/openid-connect/userinfo"

    data = {
        "grant_type": "authorization_code",
        "code": (code or "").strip(),
        "redirect_uri": _redirect_uri(),
        "client_id": _client_id(),
    }
    secret = _client_secret()
    if secret:
        data["client_secret"] = secret

    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        tok_res = await client.post(token_ep, data=data)
        tok_res.raise_for_status()
        tokens = tok_res.json()
        access = str(tokens.get("access_token") or "").strip()
        if not access:
            raise RuntimeError("OIDC token endpoint 未返回 access_token")
        ui_res = await client.get(userinfo_ep, headers={"Authorization": f"Bearer {access}"})
        ui_res.raise_for_status()
        profile = ui_res.json()
    if not isinstance(profile, dict):
        return {}
    return profile
