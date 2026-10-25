"""OIDC bearer validation and the explicitly keyed internal market SSO bridge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.application.market_bridge.protocols import JsonObject, NormalizeAuth, ProxyJSON


def _oidc_identity_from_profile(profile: dict[str, Any]) -> tuple[str, str, str]:
    username = str(
        profile.get("preferred_username") or profile.get("email") or profile.get("sub") or ""
    ).strip()
    email = str(profile.get("email") or "").strip()
    oidc_sub = str(profile.get("sub") or "").strip()
    return (username, email, oidc_sub)


@dataclass
class OIDCBridge:
    proxy: ProxyJSON
    base_url: Callable[[], str]
    profile_identity: Callable[[JsonObject], tuple[str, str, str]]
    normalize_token: Callable[[str], str]
    identity: Callable[[Any, Any], tuple[bool, bool, JsonObject]]
    internal_key: Callable[[], str]
    normalize_auth: NormalizeAuth

    async def login(
        self, profile: dict[str, Any], *, oidc_access_token: str = ""
    ) -> dict[str, Any]:
        """OIDC SSO 后自动签发/绑定 MODstore JWT（内部桥接；可选 IdP bearer 探测）。"""
        market_base = self.base_url()
        username, email, oidc_sub = self.profile_identity(profile or {})
        if not username and (not email):
            return {
                "success": False,
                "message": "OIDC 未返回可用于市场同步的身份字段",
                "market_base_url": market_base,
            }
        oidc_tok = self.normalize_token(oidc_access_token or "")
        if oidc_tok:
            me_payload = await self.proxy(
                "GET", "/api/auth/me", authorization=f"Bearer {oidc_tok}", return_error_payload=True
            )
            if isinstance(me_payload, dict) and (not me_payload.get("__proxy_error__")):
                is_enterprise, is_market_admin, user_blob = self.identity(me_payload, me_payload)
                raw_out: dict[str, Any] = dict(me_payload) if isinstance(me_payload, dict) else {}
                if user_blob and (not isinstance(raw_out.get("user"), dict)):
                    raw_out["user"] = user_blob
                return {
                    "success": True,
                    "market_base_url": market_base,
                    "token": oidc_tok,
                    "refresh_token": "",
                    "is_enterprise": is_enterprise,
                    "is_market_admin": is_market_admin,
                    "raw": raw_out,
                }
        internal_key = self.internal_key()
        if not internal_key:
            return {
                "success": False,
                "message": "未配置 XCAGI_MARKET_INTERNAL_API_KEY，SSO 会话无法自动绑定修茈市场 token",
                "market_base_url": market_base,
            }
        payload = await self.proxy(
            "POST",
            "/api/auth/internal/sso-issue-token",
            json_body={
                "username": username,
                "email": email,
                "oidc_sub": oidc_sub,
                "display_name": str(
                    profile.get("name") or profile.get("given_name") or username
                ).strip()[:128],
            },
            extra_headers={"X-Internal-Api-Key": internal_key},
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            raw = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            if not isinstance(raw, dict):
                raw = {}
            msg = str(raw.get("detail") or raw.get("message") or "市场 SSO 桥接失败")
            return {
                "success": False,
                "message": msg,
                "status_code": int(payload.get("status_code") or 502),
                "market_base_url": market_base,
            }
        return await self.normalize_auth(payload, market_base=market_base)
