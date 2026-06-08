"""从修茈门户等 HTTPS 接口代拉取 wallet_secret（一次性 Bearer，不落盘）。"""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

_SYNC_TIMEOUT = 15.0


def _hostname_forbidden(host: str) -> bool:
    h = (host or "").strip().lower()
    if not h or h == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return False


def assert_safe_https_sync_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("sync_url 为空：请在「路径与同步」配置 portal_wallet_sync_url，或在请求体中传入 sync_url")
    p = urlparse(raw)
    if (p.scheme or "").lower() != "https":
        raise ValueError("仅允许 https:// 同步地址")
    host = (p.hostname or "").strip()
    if not host:
        raise ValueError("URL 缺少主机名")
    if _hostname_forbidden(host):
        raise ValueError("不允许使用 loopback / 内网 / 链路本地地址作为同步目标")
    return raw


def _extract_wallet_secret(payload: Any) -> str:
    if isinstance(payload, dict):
        v = payload.get("wallet_secret")
        if v is not None and str(v).strip():
            return str(v).strip()
        data = payload.get("data")
        if isinstance(data, dict):
            v2 = data.get("wallet_secret")
            if v2 is not None and str(v2).strip():
                return str(v2).strip()
    raise ValueError("响应 JSON 中未找到 wallet_secret 字段")


def fetch_wallet_secret(sync_url: str, authorization: str) -> Dict[str, Any]:
    """
    GET sync_url，携带 Authorization 头；期望 200 与 JSON 含 ``wallet_secret``。
    """
    url = assert_safe_https_sync_url(sync_url)
    auth = (authorization or "").strip()
    if not auth:
        raise ValueError("缺少 authorization（建议传 Bearer <修茈访问令牌>，仅本次请求使用）")

    headers: Dict[str, str] = {}
    if auth.lower().startswith("bearer "):
        headers["Authorization"] = auth
    else:
        headers["Authorization"] = f"Bearer {auth}" if " " not in auth else auth

    with httpx.Client(timeout=_SYNC_TIMEOUT) as client:
        r = client.get(url, headers=headers)
    if r.status_code >= 400:
        raise ValueError(f"远程返回 HTTP {r.status_code}: {r.text[:500]}")
    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        raise ValueError("响应不是合法 JSON") from e
    secret = _extract_wallet_secret(payload)
    if len(secret) > 8192:
        raise ValueError("wallet_secret 长度过大")
    return {"ok": True, "wallet_secret": secret}
