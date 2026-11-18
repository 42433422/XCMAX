"""Notion 页面导入（REST API + 块树纯文本化）。

管理员配置 ``XCAGI_NOTION_TOKEN``（内部集成 token），可选 ``XCAGI_NOTION_BASE_URL``
（默认 ``https://api.notion.com/v1``）。只读取页面标题与块文本，不落任何 Notion 结构。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.infrastructure.document_parsing.errors import DocumentSourceError
from app.utils.operational_errors import BOUNDARY_ERRORS

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 200_000
MAX_DEPTH = 3
MAX_BLOCK_PAGES = 5
TIMEOUT_S = 15
NOTION_VERSION = "2022-06-28"
_DEFAULT_BASE = "https://api.notion.com/v1"
_LOGGER = logging.getLogger(__name__)
_PAGE_ID = re.compile(r"^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")

_TEXT_BLOCKS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "quote",
        "code",
        "callout",
        "toggle",
        "child_page",
    }
)
_NESTED_BLOCKS = frozenset(
    {
        "paragraph",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "quote",
        "callout",
    }
)


@dataclass(frozen=True)
class FetchedNotionPage:
    page_id: str
    url: str
    title: str
    text: str


def _base_url() -> str:
    base = (os.environ.get("XCAGI_NOTION_BASE_URL") or _DEFAULT_BASE).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DocumentSourceError("未配置有效的 XCAGI_NOTION_BASE_URL")
    return base


def _headers() -> dict[str, str]:
    token = (os.environ.get("XCAGI_NOTION_TOKEN") or "").strip()
    if not token:
        raise DocumentSourceError("未配置 XCAGI_NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }


def _rich_text(value: object) -> str:
    parts: list[str] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        text = item.get("plain_text")
        if not text and isinstance(item.get("text"), dict):
            text = item["text"].get("content")
        if text:
            parts.append(str(text))
    return "".join(parts).strip()


def _block_text(block: dict) -> str:
    block_type = str(block.get("type") or "")
    if block_type not in _TEXT_BLOCKS:
        return ""
    payload = block.get(block_type)
    if not isinstance(payload, dict):
        return ""
    text = _rich_text(payload.get("rich_text"))
    if not text and block_type == "child_page":
        text = str(payload.get("title") or "").strip()
    if not text:
        return ""
    prefix = "#" if block_type.startswith("heading") else ""
    return f"{prefix}{text}" if prefix else text


def _page_title(page: dict) -> str:
    properties = page.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title = _rich_text(prop.get("title"))
                if title:
                    return title[:200]
    return ""


def _get_json(getter, url: str, headers: dict[str, str]) -> dict:
    try:
        response = getter(url, headers=headers, timeout=TIMEOUT_S)
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Notion request failed")
        raise DocumentSourceError("Notion 请求失败") from exc
    if response.status_code >= 400:
        raise DocumentSourceError(f"Notion 返回 HTTP {response.status_code}")
    raw = bytes(response.content or b"")
    if len(raw) > MAX_BYTES:
        raise DocumentSourceError(f"Notion 响应超过大小限制（>{MAX_BYTES // 1024 // 1024}MB）")
    try:
        payload = response.json()
    except BOUNDARY_ERRORS as exc:
        _LOGGER.exception("Notion response decoding failed")
        raise DocumentSourceError("Notion 响应无法解析") from exc
    if not isinstance(payload, dict):
        raise DocumentSourceError("Notion 响应格式不正确")
    if payload.get("object") == "error":
        _LOGGER.warning(
            "Notion request rejected: %s", payload.get("message") or payload.get("code")
        )
        raise DocumentSourceError("Notion 读取失败")
    return payload


def _children_text(
    block_id: str,
    *,
    getter,
    base: str,
    headers: dict[str, str],
    depth: int,
    budget: list[int],
) -> list[str]:
    lines: list[str] = []
    cursor: str | None = None
    for _ in range(MAX_BLOCK_PAGES):
        url = f"{base}/blocks/{block_id}/children?page_size=100"
        if cursor:
            url = f"{url}&start_cursor={cursor}"
        payload = _get_json(getter, url, headers)
        for block in payload.get("results") or []:
            if budget[0] <= 0:
                return lines
            budget[0] -= 1
            if not isinstance(block, dict):
                continue
            text = _block_text(block)
            if text:
                lines.append(text)
            block_type = str(block.get("type") or "")
            if (
                block.get("has_children")
                and depth < MAX_DEPTH
                and block_type in _NESTED_BLOCKS
                and block.get("id")
            ):
                lines.extend(
                    _children_text(
                        str(block["id"]),
                        getter=getter,
                        base=base,
                        headers=headers,
                        depth=depth + 1,
                        budget=budget,
                    )
                )
        cursor = payload.get("next_cursor")
        if not payload.get("has_more") or not cursor:
            break
    return lines


def fetch_page(page_id: str, *, getter=None) -> FetchedNotionPage:
    """读取 Notion 页面文本；失败抛 ValueError（调用方转 400）。"""
    pid = (page_id or "").strip()
    if not _PAGE_ID.fullmatch(pid):
        raise DocumentSourceError("Notion 页面 ID 不合法")
    base = _base_url()
    headers = _headers()
    if getter is None:
        import requests

        getter = requests.get
    page = _get_json(getter, f"{base}/pages/{pid}", headers)
    title = _page_title(page)
    lines = _children_text(pid, getter=getter, base=base, headers=headers, depth=0, budget=[500])
    text = "\n".join(line for line in lines if line.strip()).strip()
    if not text:
        raise DocumentSourceError("Notion 页面没有可导入的文本")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return FetchedNotionPage(
        page_id=pid,
        url=str(page.get("url") or f"notion://{pid}"),
        title=title or text.splitlines()[0][:120],
        text=text,
    )
