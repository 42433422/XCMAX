"""抓取搜索结果链接页正文，供 LLM 联网上下文使用。"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
from html import unescape

import httpx
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


_BLOCK_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
)


def web_fetch_pages_enabled() -> bool:
    raw = (os.environ.get("MODSTORE_WEB_FETCH_PAGES") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def web_fetch_max_pages() -> int:
    try:
        n = int((os.environ.get("MODSTORE_WEB_FETCH_MAX_PAGES") or "3").strip())
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def web_fetch_max_chars_per_page() -> int:
    try:
        n = int((os.environ.get("MODSTORE_WEB_FETCH_MAX_CHARS") or "2500").strip())
    except ValueError:
        n = 2500
    return max(400, min(n, 8000))


def web_fetch_timeout_sec() -> float:
    try:
        n = float((os.environ.get("MODSTORE_WEB_FETCH_TIMEOUT") or "15").strip())
    except ValueError:
        n = 15.0
    return max(5.0, min(n, 45.0))


def _host_blocked(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return True
    if any(h.endswith(sfx) for sfx in _BLOCK_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(
            ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
        )
    except ValueError:
        pass
    if h.endswith(".localhost"):
        return True
    return False


def is_fetchable_http_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
        if (
            parsed.scheme not in ("http", "https")
            or "@" in parsed.netloc
            or parsed.fragment
            or parsed.port is not None and parsed.port <= 0
        ):
            return False
        return not _host_blocked(parsed.hostname or "")
    except ValueError:
        return False


def html_to_plain_text(html: str, *, max_chars: int) -> str:
    blob = html or ""
    blob = re.sub(r"(?is)<(script|style|noscript|iframe)[^>]*>.*?</\1>", " ", blob)
    blob = re.sub(r"(?is)<!--.*?-->", " ", blob)
    text = re.sub(r"<[^>]+>", " ", blob)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return _truncate(text, max_chars)


async def fetch_page_text(
    url: str,
    *,
    max_chars: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Tuple[str, Optional[str]]:
    """只抓取公网网页：逐跳校验并固定 DNS，流式限制响应体。"""
    u = (url or "").strip()
    if not is_fetchable_http_url(u):
        return "", "url 不可抓取"
    cap = min(8000, max(1, max_chars if max_chars is not None else web_fetch_max_chars_per_page()))
    deadline = timeout if timeout is not None else web_fetch_timeout_sec()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    from modstore_server.openapi_connector_runtime import pin_url_outbound_safe

    try:
        # No ambient proxies or implicit redirects: both can bypass the initial URL check.
        async with httpx.AsyncClient(timeout=deadline, trust_env=False, follow_redirects=False) as client:
            for _ in range(4):
                target = await asyncio.to_thread(pin_url_outbound_safe, u)
                async with client.stream(
                    "GET",
                    target.request_url,
                    headers={**headers, "Host": target.host_header},
                    extensions={"sni_hostname": target.server_hostname},
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            return "", "无效重定向"
                        next_url = urljoin(u, location)
                        if not is_fetchable_http_url(next_url):
                            return "", "重定向目标不可抓取"
                        u = next_url
                        continue
                    response.raise_for_status()
                    body_bytes = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        if len(body_bytes) + len(chunk) > 1_000_000:
                            return "", "响应过大"
                        body_bytes.extend(chunk)
                    try:
                        body = body_bytes.decode(response.encoding or "utf-8", errors="replace")
                    except LookupError:
                        body = body_bytes.decode("utf-8", errors="replace")
                    if not body.strip():
                        return "", "空响应"
                    ctype = (response.headers.get("content-type") or "").lower()
                    if "html" in ctype or "<html" in body[:800].lower():
                        return html_to_plain_text(body, max_chars=cap), None
                    if "json" in ctype:
                        return _truncate(body.replace("\n", " "), cap), None
                    return _truncate(body, cap), None
        return "", "跳转次数过多"
    except RECOVERABLE_ERRORS:
        return "", "抓取失败"


async def enrich_web_results_with_pages(
    results: List[Dict[str, Any]],
    *,
    max_pages: Optional[int] = None,
    max_chars_per_page: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """对前 N 条带 URL 的结果抓取正文，写入 page_content。"""
    if not web_fetch_pages_enabled() or not results:
        return results
    n = max_pages if max_pages is not None else web_fetch_max_pages()
    cap = max_chars_per_page if max_chars_per_page is not None else web_fetch_max_chars_per_page()
    sem = asyncio.Semaphore(3)

    async def _one(it: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(it)
        url = str(row.get("url") or "").strip()
        if not url or not is_fetchable_http_url(url):
            return row
        async with sem:
            text, err = await fetch_page_text(url, max_chars=cap)
        if text:
            row["page_content"] = text
            row["page_fetched"] = True
        else:
            row["page_fetched"] = False
            row["page_fetch_error"] = err or "抓取失败"
        return row

    head = [r for r in results if str(r.get("url") or "").strip()][:n]
    tail = results[len(head) :]
    if not head:
        return results
    enriched = await asyncio.gather(*[_one(it) for it in head])
    return list(enriched) + [dict(it) for it in tail]
