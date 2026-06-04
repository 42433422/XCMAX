"""OpenID Connect（OIDC）登录：可选企业 IdP 联邦。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 600


def oidc_enabled() -> bool:
    return os.environ.get("XCAGI_OIDC_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _config() -> dict[str, str]:
    issuer = os.environ.get("XCAGI_OIDC_ISSUER", "").strip().rstrip("/")
    client_id = os.environ.get("XCAGI_OIDC_CLIENT_ID", "").strip()
    client_secret = os.environ.get("XCAGI_OIDC_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("XCAGI_OIDC_REDIRECT_URI", "").strip()
    if not all((issuer, client_id, redirect_uri)):
        raise ValueError("OIDC 未完整配置：需要 XCAGI_OIDC_ISSUER / CLIENT_ID / REDIRECT_URI")
    return {
        "issuer": issuer,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "scopes": os.environ.get("XCAGI_OIDC_SCOPES", "openid profile email").strip(),
    }


def _state_secret() -> bytes:
    key = os.environ.get("SECRET_KEY", "").strip() or "dev-insecure-oidc-state"
    return key.encode("utf-8")


def sign_oidc_state(nonce: str | None = None) -> str:
    payload = {"ts": int(time.time()), "nonce": nonce or secrets.token_urlsafe(16)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_state_secret(), raw, hashlib.sha256).hexdigest()
    return f"{sig}.{raw.decode('utf-8')}"


def verify_oidc_state(state: str) -> bool:
    try:
        sig, raw = state.split(".", 1)
        expected = hmac.new(_state_secret(), raw.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(raw)
        ts = int(payload.get("ts", 0))
        return (time.time() - ts) <= _STATE_TTL_SECONDS
    except (ValueError, json.JSONDecodeError, TypeError):
        return False


async def _discovery(issuer: str) -> dict[str, Any]:
    url = f"{issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("invalid OIDC discovery document")
        return data


async def build_authorization_url() -> tuple[str, str]:
    cfg = _config()
    doc = await _discovery(cfg["issuer"])
    auth_endpoint = str(doc.get("authorization_endpoint") or "")
    if not auth_endpoint:
        raise ValueError("OIDC discovery missing authorization_endpoint")
    state = sign_oidc_state()
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scopes"],
        "state": state,
    }
    return f"{auth_endpoint}?{urllib.parse.urlencode(params)}", state


async def exchange_code_for_userinfo(code: str) -> dict[str, Any]:
    cfg = _config()
    doc = await _discovery(cfg["issuer"])
    token_endpoint = str(doc.get("token_endpoint") or "")
    userinfo_endpoint = str(doc.get("userinfo_endpoint") or "")
    if not token_endpoint or not userinfo_endpoint:
        raise ValueError("OIDC discovery missing token_endpoint or userinfo_endpoint")

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
        "client_id": cfg["client_id"],
    }
    if cfg["client_secret"]:
        token_data["client_secret"] = cfg["client_secret"]

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_resp = await client.post(token_endpoint, data=token_data)
        token_resp.raise_for_status()
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("OIDC token response missing access_token")
        ui_resp = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        ui_resp.raise_for_status()
        profile = ui_resp.json()
        if not isinstance(profile, dict):
            raise ValueError("invalid OIDC userinfo")
        return profile


def map_oidc_profile_to_username(profile: dict[str, Any]) -> str:
    for key in ("preferred_username", "email", "sub"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    raise ValueError("OIDC userinfo 缺少 preferred_username / email / sub")
