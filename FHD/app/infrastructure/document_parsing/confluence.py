"""Confluence 页面导入（REST API + trafilatura 正文抽取）。

管理员通过环境变量配置连接，不接受用户传入主机地址：
``XCAGI_CONFLUENCE_BASE_URL``（如 ``https://company.atlassian.net/wiki``）、
``XCAGI_CONFLUENCE_API_TOKEN``，以及可选的 ``XCAGI_CONFLUENCE_EMAIL``
（填写时用 Basic Auth，否则用 Bearer Token）。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.infrastructure.document_parsing.web_fetch import extract_html_text
from app.utils.operational_errors import BOUNDARY_ERRORS

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 15
_PAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedConfluencePage:
    page_id: str
    url: str
    title: str
    text: str


def _base_url() -> str:
    base = (os.environ.get("XCAGI_CONFLUENCE_BASE_URL") or "").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("未配置有效的 XCAGI_CONFLUENCE_BASE_URL")
    return base


def _auth() -> tuple[dict[str, str], tuple[str, str] | None]:
    token = (
        os.environ.get("XCAGI_CONFLUENCE_API_TOKEN")
        or os.environ.get("XCAGI_CONFLUENCE_TOKEN")
        or ""
    ).strip()
    if not token:
        raise ValueError("未配置 XCAGI_CONFLUENCE_API_TOKEN")
    email = (os.environ.get("XCAGI_CONFLUENCE_EMAIL") or "").strip()
    if email:
        return {}, (email, token)
    return {"Authorization": f"Bearer {token}"}, None


def fetch_page(page_id: str, *, getter=None) -> FetchedConfluencePage:
    """读取单个 Confluence 页面并抽取正文；失败抛 ValueError（调用方转 400）。"""
    pid = (page_id or "").strip()
    if not _PAGE_ID.fullmatch(pid):
        raise ValueError("Confluence 页面 ID 不合法")
    base = _base_url()
    headers, auth = _auth()
    url = f"{base}/rest/api/content/{pid}?expand=body.storage"
    requester = getter
    if requester is None:
        import requests

        requester = requests.get
    try:
        response = requester(url, timeout=TIMEOUT_S, headers=headers, auth=auth)
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Confluence request failed")
        raise ValueError("Confluence 请求失败") from exc
    if response.status_code >= 400:
        raise ValueError(f"Confluence 返回 HTTP {response.status_code}")
    raw = bytes(response.content or b"")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Confluence 页面超过大小限制（>{MAX_BYTES // 1024 // 1024}MB）")
    try:
        payload = response.json()
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Confluence response decoding failed")
        raise ValueError("Confluence 响应无法解析") from exc
    if not isinstance(payload, dict):
        raise ValueError("Confluence 响应格式不正确")
    storage = ((payload.get("body") or {}).get("storage") or {}).get("value") or ""
    title = str(payload.get("title") or "")
    page_url = f"{base}/pages/{pid}"
    text, extracted_title = extract_html_text(str(storage), url=page_url)
    return FetchedConfluencePage(
        page_id=pid,
        url=page_url,
        title=title or extracted_title,
        text=text,
    )
