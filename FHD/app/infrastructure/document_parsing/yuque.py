"""语雀（Yuque）文档导入（官方 REST API）。

管理员配置 ``XCAGI_YUQUE_TOKEN``（个人/团队 token），可选 ``XCAGI_YUQUE_BASE_URL``
（默认 ``https://www.yuque.com``，私有化部署可指向自有域名）。
文档引用写成 ``namespace/repo/doc`` 三段，读取标题与 Markdown 正文。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.utils.operational_errors import BOUNDARY_ERRORS

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 200_000
TIMEOUT_S = 15
_DEFAULT_BASE = "https://www.yuque.com"
_LOGGER = logging.getLogger(__name__)
_DOC_REF = re.compile(r"^[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,120}$")
_TAG = re.compile(r"<[^<>]+>")


@dataclass(frozen=True)
class FetchedYuqueDoc:
    namespace: str
    slug: str
    url: str
    title: str
    text: str


def _base_url() -> str:
    base = (os.environ.get("XCAGI_YUQUE_BASE_URL") or _DEFAULT_BASE).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("未配置有效的 XCAGI_YUQUE_BASE_URL")
    return base


def _headers() -> dict[str, str]:
    token = (os.environ.get("XCAGI_YUQUE_TOKEN") or "").strip()
    if not token:
        raise ValueError("未配置 XCAGI_YUQUE_TOKEN")
    return {"X-Auth-Token": token, "User-Agent": "XCMAX-Knowledge/1.0"}


def _split_ref(ref: str) -> tuple[str, str]:
    """拆成语雀仓库命名空间（group/repo）与文档 slug。"""
    cleaned = (ref or "").strip()
    if not _DOC_REF.fullmatch(cleaned):
        raise ValueError("语雀文档引用不合法，应为 namespace/repo/doc")
    group, repo, slug = cleaned.split("/")
    return f"{group}/{repo}", slug


def _plain(html: str) -> str:
    text = _TAG.sub("\n", html or "")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def fetch_document(ref: str, *, getter=None) -> FetchedYuqueDoc:
    """读取语雀文档正文；失败抛 ValueError（调用方转 400）。"""
    namespace, slug = _split_ref(ref)
    base = _base_url()
    headers = _headers()
    if getter is None:
        import requests

        getter = requests.get
    url = f"{base}/api/v2/repos/{namespace}/docs/{slug}"
    try:
        response = getter(url, headers=headers, timeout=TIMEOUT_S)
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Yuque request failed")
        raise ValueError("语雀请求失败") from exc
    if response.status_code in {401, 403}:
        raise ValueError("语雀鉴权失败，请检查 XCAGI_YUQUE_TOKEN 与文档权限")
    if response.status_code == 404:
        raise ValueError("语雀文档不存在或无权访问")
    if response.status_code >= 400:
        raise ValueError(f"语雀返回 HTTP {response.status_code}")
    raw = bytes(response.content or b"")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"语雀响应超过大小限制（>{MAX_BYTES // 1024 // 1024}MB）")
    try:
        payload = response.json()
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Yuque response decoding failed")
        raise ValueError("语雀响应无法解析") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("语雀响应缺少 data")
    body = str(data.get("body") or "").strip()
    if not body:
        body = _plain(str(data.get("body_html") or ""))
    if not body:
        raise ValueError("语雀文档没有可导入的文本")
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS]
    title = str(data.get("title") or "").strip()[:200] or body.splitlines()[0][:120]
    return FetchedYuqueDoc(
        namespace=namespace,
        slug=slug,
        url=f"{base}/{namespace}/{slug}",
        title=title,
        text=f"# {title}\n\n{body}" if title else body,
    )
