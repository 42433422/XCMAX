"""飞书云文档导入（开放平台 REST + 纯文本 raw_content）。

管理员配置 ``XCAGI_FEISHU_APP_ID`` / ``XCAGI_FEISHU_APP_SECRET``；``XCAGI_FEISHU_BASE_URL``
可指向私有化域名，默认 ``https://open.feishu.cn``。租户 token 进程内缓存。
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.infrastructure.document_parsing.errors import DocumentSourceError
from app.utils.operational_errors import BOUNDARY_ERRORS

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 15
_DOC_ID = re.compile(r"^[A-Za-z0-9]{8,64}$")
_DEFAULT_BASE = "https://open.feishu.cn"
_LOGGER = logging.getLogger(__name__)

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[str, float]] = {}


@dataclass(frozen=True)
class FetchedFeishuDoc:
    document_id: str
    url: str
    title: str
    text: str


def reset_token_cache_for_tests() -> None:
    with _token_lock:
        _token_cache.clear()


def _base_url() -> str:
    base = (os.environ.get("XCAGI_FEISHU_BASE_URL") or _DEFAULT_BASE).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DocumentSourceError("未配置有效的 XCAGI_FEISHU_BASE_URL")
    return base


def _credentials() -> tuple[str, str]:
    app_id = (os.environ.get("XCAGI_FEISHU_APP_ID") or "").strip()
    secret = (os.environ.get("XCAGI_FEISHU_APP_SECRET") or "").strip()
    if not app_id or not secret:
        raise DocumentSourceError("未配置 XCAGI_FEISHU_APP_ID / XCAGI_FEISHU_APP_SECRET")
    return app_id, secret


def _tenant_token(base: str, poster) -> str:
    app_id, secret = _credentials()
    cache_key = f"{base}:{app_id}"
    now = time.time()
    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached and cached[1] > now + 30:
            return cached[0]
    try:
        response = poster(
            f"{base}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": secret},
            timeout=TIMEOUT_S,
        )
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Feishu authentication request failed")
        raise DocumentSourceError("飞书鉴权请求失败") from exc
    if response.status_code >= 400:
        raise DocumentSourceError(f"飞书鉴权返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Feishu authentication response decoding failed")
        raise DocumentSourceError("飞书鉴权响应无法解析") from exc
    token = str((payload or {}).get("tenant_access_token") or "")
    if (payload or {}).get("code") not in (0, None) or not token:
        message = str((payload or {}).get("msg") or "未返回 tenant_access_token")
        _LOGGER.warning("Feishu authentication rejected: %s", message)
        raise DocumentSourceError("飞书鉴权失败")
    expire = int((payload or {}).get("expire") or 3600)
    with _token_lock:
        _token_cache[cache_key] = (token, now + expire)
    return token


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:120]
    return ""


def fetch_document(document_id: str, *, getter=None, poster=None) -> FetchedFeishuDoc:
    """读取飞书文档纯文本；失败抛 ValueError（调用方转 400）。"""
    doc_id = (document_id or "").strip()
    if not _DOC_ID.fullmatch(doc_id):
        raise DocumentSourceError("飞书文档 ID 不合法")
    base = _base_url()
    if getter is None or poster is None:
        import requests

        getter = getter or requests.get
        poster = poster or requests.post
    token = _tenant_token(base, poster)
    url = f"{base}/open-apis/docx/v1/documents/{doc_id}/raw_content"
    try:
        response = getter(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_S,
        )
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Feishu document request failed")
        raise DocumentSourceError("飞书文档请求失败") from exc
    if response.status_code >= 400:
        raise DocumentSourceError(f"飞书文档返回 HTTP {response.status_code}")
    raw = bytes(response.content or b"")
    if len(raw) > MAX_BYTES:
        raise DocumentSourceError(f"飞书文档超过大小限制（>{MAX_BYTES // 1024 // 1024}MB）")
    try:
        payload = response.json()
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Feishu document response decoding failed")
        raise DocumentSourceError("飞书文档响应无法解析") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (0, None):
        message = payload.get("msg") if isinstance(payload, dict) else "响应格式不正确"
        _LOGGER.warning("Feishu document rejected: %s", message)
        raise DocumentSourceError("飞书文档读取失败")
    text = str(((payload.get("data") or {}).get("content")) or "").strip()
    if not text:
        raise DocumentSourceError("飞书文档内容为空")
    return FetchedFeishuDoc(
        document_id=doc_id,
        url=f"feishu://docx/{doc_id}",
        title=_title_from_text(text),
        text=text,
    )
