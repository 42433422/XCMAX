# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


async def get_access_token(force_refresh: bool = False) -> str:
    """取或刷新 AccessToken。提前 5 分钟续期，单飞防雪崩。"""
    now = _facade().time.time()
    if (
        not force_refresh
        and _facade()._token_state.token
        and (_facade()._token_state.expires_at - now > _facade()._TOKEN_REFRESH_LEAD_SECONDS)
    ):
        return _facade()._token_state.token
    async with _facade()._token_state._lock_or_create():
        now = _facade().time.time()
        if (
            not force_refresh
            and _facade()._token_state.token
            and (_facade()._token_state.expires_at - now > _facade()._TOKEN_REFRESH_LEAD_SECONDS)
        ):
            return _facade()._token_state.token
        app_id = _facade()._qq_app_id()
        app_secret = _facade()._qq_app_secret()
        if not (app_id and app_secret):
            raise _facade().HTTPException(503, "BUTLER_QQ_APP_ID / BUTLER_QQ_APP_SECRET 未配置")
        async with _facade().httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                _facade()._qq_token_endpoint(), json={"appId": app_id, "clientSecret": app_secret}
            )
            if r.status_code >= 400:
                raise _facade().HTTPException(
                    502, f"QQ getAppAccessToken 失败: {r.status_code} {r.text[:200]}"
                )
            data = r.json()
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise _facade().HTTPException(502, f"QQ access_token 缺失：{data}")
        try:
            ttl = int(data.get("expires_in") or 7200)
        except Exception:
            ttl = 7200
        _facade()._token_state.token = token
        _facade()._token_state.expires_at = now + max(ttl, 60)
        return token
