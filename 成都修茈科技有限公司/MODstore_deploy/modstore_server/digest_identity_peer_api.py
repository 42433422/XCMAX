"""跨部署身份码校验（digest identity peer）。

自建 MODstore 上生成的每日摘要 6 位身份码默认只存在于该库。若公网站点（如 xiu-ci.com）
与自建库分离，可在公网实例配置 ``MODSTORE_DIGEST_IDENTITY_UPSTREAM_URL``，在本地库校验
失败后由服务端代为请求自建实例的只读校验接口。

- **自建（签发端）**：设置 ``MODSTORE_DIGEST_PEER_SERVICE_TOKEN``（长随机串）且
  ``MODSTORE_DIGEST_PEER_ENABLE_INBOUND=1``，对外暴露
  ``POST /api/internal/verify-digest-identity``（Bearer 同上 Token）。
- **公网（消费端）**：设置 ``MODSTORE_DIGEST_IDENTITY_UPSTREAM_URL``（无尾斜杠，须从公网
  服务器能 HTTP(S) 访问到自建 API 根）及**相同**的 ``MODSTORE_DIGEST_PEER_SERVICE_TOKEN``。
  管理员 ``POST /api/auth/verify-admin-digest-code`` 在本地未命中时会尝试上游。

安全说明：内部接口仅凭共享密钥保护，须配合防火墙/IP 限制与高强度 Token；泄露等同于
可对该部署做离线空间内的身份码枚举，生产务必限制来源 IP。
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from modstore_server.digest_identity import normalize_digest_identity_code, verify_digest_identity
from modstore_server.models import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["internal", "digest"])


def peer_service_token() -> str:
    return (os.environ.get("MODSTORE_DIGEST_PEER_SERVICE_TOKEN") or "").strip()


def inbound_enabled() -> bool:
    if not peer_service_token():
        return False
    flag = (os.environ.get("MODSTORE_DIGEST_PEER_ENABLE_INBOUND") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def upstream_base_url() -> str:
    return (os.environ.get("MODSTORE_DIGEST_IDENTITY_UPSTREAM_URL") or "").strip().rstrip("/")


def _bearer_token(request: Request) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _authorize_peer(request: Request) -> None:
    if not inbound_enabled():
        raise HTTPException(404, "Not Found")
    expected = peer_service_token()
    presented = _bearer_token(request)
    if not presented or not expected:
        raise HTTPException(401, "Unauthorized")
    try:
        ok = hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    except ValueError:
        ok = False
    if not ok:
        raise HTTPException(401, "Unauthorized")


class VerifyDigestIdentityBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)


@router.post("/internal/verify-digest-identity")
def internal_verify_digest_identity(
    request: Request, body: VerifyDigestIdentityBody
) -> dict[str, Any]:
    """服务间：用共享 Bearer 校验 6 位身份码，返回与 ``verify_digest_identity`` 一致的过期时间。"""
    _authorize_peer(request)
    code = normalize_digest_identity_code(body.code or "")
    if len(code) != 6 or any(c not in "0123456789ABCDEF" for c in code):
        raise HTTPException(400, "身份码格式错误，应为 6 位十六进制")

    sf = get_session_factory()
    with sf() as session:
        expires_iso = verify_digest_identity(session, code)
    if expires_iso:
        return {"ok": True, "expires_at": expires_iso}
    return {"ok": False}


def call_upstream_digest_verify(code: str) -> str | None:
    """若配置了上游 URL 与 Token，则请求上游 ``/api/internal/verify-digest-identity``；成功返回 expires_at ISO 字符串。"""
    base = upstream_base_url()
    token = peer_service_token()
    if not base or not token:
        return None
    url = f"{base}/api/internal/verify-digest-identity"
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.post(
                url,
                json={"code": code},
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code != 200:
            logger.info(
                "digest upstream verify non-200: status=%s body=%s",
                r.status_code,
                (r.text or "")[:300],
            )
            return None
        data = r.json()
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        exp = data.get("expires_at")
        return str(exp).strip() if exp else None
    except Exception as exc:
        logger.warning("digest upstream verify request failed: %s", exc)
        return None


__all__ = [
    "router",
    "call_upstream_digest_verify",
    "inbound_enabled",
    "upstream_base_url",
    "peer_service_token",
]
