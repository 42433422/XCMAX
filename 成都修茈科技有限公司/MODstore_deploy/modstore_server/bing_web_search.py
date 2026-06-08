"""微软 Bing / cn.bing SERP HTML 爬虫。可选本机 Edge（Playwright channel=msedge）。"""

from __future__ import annotations

import os
import re
from html import unescape
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import quote_plus, urlparse

import httpx

BingBrowserMode = Literal["auto", "http", "edge"]

_BING_SEARCH_URL = "https://cn.bing.com/search?q={query}&count={count}&setlang=zh-Hans"

_BING_SKIP_NETLOCS = frozenset(
    {"www.bing.com", "bing.com", "cn.bing.com", "www2.bing.com", "go.microsoft.com"}
)


def _request_error_fragment(exc: BaseException) -> str:
    msg = str(exc).strip()
    return msg if msg else type(exc).__name__


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def bing_browser_mode_from_env() -> BingBrowserMode:
    """联系页默认 edge（Playwright）；无 Chromium 时可设 MODSTORE_BING_BROWSER=http。"""
    contact = (os.environ.get("MODSTORE_CONTACT_WEB_BING") or "").strip().lower()
    if contact in ("edge", "msedge", "playwright", "browser"):
        return "edge"
    if contact in ("http", "httpx"):
        return "http"
    raw = (os.environ.get("MODSTORE_BING_BROWSER") or "edge").strip().lower()
    if raw in ("edge", "msedge", "microsoft-edge", "browser", "playwright"):
        return "edge"
    if raw in ("http", "httpx"):
        return "http"
    return "auto"


def _edge_user_agent() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
    )


def _default_headers(*, edge: bool = False) -> Dict[str, str]:
    ua = (
        _edge_user_agent()
        if edge
        else (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
        )
    )
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def filter_results_by_full_query(query: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按完整查询串过滤 SERP（整句命中或查询中连续 3 字出现在结果中）。"""
    if not rows:
        return []
    qn = re.sub(r"\s+", "", (query or "").strip().strip("\"'"))
    if len(qn) < 3:
        return rows
    good: List[Dict[str, Any]] = []
    for row in rows:
        blob = re.sub(
            r"\s+",
            "",
            f"{row.get('title') or ''}{row.get('content') or ''}{row.get('url') or ''}",
        )
        if qn in blob:
            good.append(row)
            continue
        for i in range(len(qn) - 2):
            if qn[i : i + 3] in blob:
                good.append(row)
                break
    return good


def _bing_href_skipped(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return True
    netloc = (parsed.netloc or "").lower()
    if netloc in _BING_SKIP_NETLOCS or netloc.endswith(".bing.com"):
        return True
    return False


def parse_bing_serp_html(html: str, *, max_results: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    blob = html or ""

    for block in re.finditer(
        r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>(.*?)</li>',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        chunk = block.group(1)
        link = re.search(
            r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            chunk,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not link:
            continue
        href, title_html = link.group(1), link.group(2)
        if _bing_href_skipped(href):
            continue
        title = strip_html(title_html)
        snippet = re.search(
            r'<(?:div|p)[^>]+class="[^"]*\bb_caption\b[^"]*"[^>]*>(.*?)</(?:div|p)>',
            chunk,
            flags=re.IGNORECASE | re.DOTALL,
        )
        content = strip_html(snippet.group(1)) if snippet else ""
        if not title and not content:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append({"title": title or href, "url": href, "content": content})
        if len(out) >= max_results:
            return out

    if out:
        return out

    for href, title_html in re.findall(
        r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        if _bing_href_skipped(href) or href in seen:
            continue
        title = strip_html(title_html)
        if not title:
            continue
        seen.add(href)
        out.append({"title": title, "url": href, "content": ""})
        if len(out) >= max_results:
            break
    return out


async def _fetch_bing_html(query: str, *, count: int) -> str:
    url = _BING_SEARCH_URL.format(query=quote_plus(query[:500]), count=count)
    headers = _default_headers()
    async with httpx.AsyncClient(follow_redirects=True, timeout=25.0) as client:
        await client.get("https://cn.bing.com/", headers=headers)
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.text or ""


async def _fetch_bing_html_via_edge(
    query: str, *, headless: Optional[bool] = None, count: int = 10
) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "未安装 playwright。请执行: pip install playwright && playwright install msedge"
        ) from e

    q = (query or "").strip()[:500]
    if headless is None:
        raw = os.environ.get("MODSTORE_BING_EDGE_HEADLESS") or "1"
        headless = raw.strip().lower() not in ("0", "false", "no", "off")

    rn = max(5, min(int(count), 50))
    search_url = _BING_SEARCH_URL.format(query=quote_plus(q), count=rn)
    channel = (os.environ.get("MODSTORE_BING_EDGE_CHANNEL") or "msedge").strip() or "msedge"

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(channel=channel, headless=headless)
        except Exception:
            browser = await playwright.chromium.launch(headless=headless)
        try:
            page = await (
                await browser.new_context(locale="zh-CN", user_agent=_edge_user_agent())
            ).new_page()
            await page.goto("https://cn.bing.com/", wait_until="domcontentloaded", timeout=25_000)
            try:
                box = page.locator("#sb_form_q, input[name='q']").first
                await box.wait_for(state="visible", timeout=8_000)
                await box.click()
                await box.fill("")
                await box.fill(q)
                await box.press("Enter")
                await page.wait_for_load_state("domcontentloaded", timeout=25_000)
                await page.wait_for_selector("li.b_algo, #b_results", timeout=15_000)
            except Exception:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=25_000)
                await page.wait_for_selector("li.b_algo, #b_results", timeout=15_000)
            return await page.content()
        finally:
            await browser.close()


def _tavily_fallback_enabled() -> bool:
    raw = (os.environ.get("MODSTORE_WEB_SEARCH_USE_TAVILY") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _apply_company_relevance(query: str, parsed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if "有限公司" not in q and "有限责任公司" not in q and "股份" not in q:
        return parsed
    return filter_results_by_full_query(q, parsed)


def _finalize_bing_parsed(
    query: str, parsed: List[Dict[str, Any]], *, max_results: int
) -> List[Dict[str, Any]]:
    """相关性过滤；过滤后为空仍保留 Bing 原结果，避免误丢 SERP。"""
    if not parsed:
        return []
    filtered = _apply_company_relevance(query, parsed)
    if filtered:
        return filtered[:max_results]
    return parsed[:max_results]


async def bing_html_search(
    query: str,
    max_results: int = 10,
    *,
    browser: Optional[BingBrowserMode] = None,
    edge_headless: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    rn = max(1, min(int(max_results), 50))
    mode = browser or bing_browser_mode_from_env()
    errors: List[str] = []

    async def _edge_crawl() -> List[Dict[str, Any]]:
        html = await _fetch_bing_html_via_edge(q, headless=edge_headless, count=max(rn, 10))
        return _finalize_bing_parsed(q, parse_bing_serp_html(html, max_results=rn), max_results=rn)

    async def _http_crawl() -> List[Dict[str, Any]]:
        html = await _fetch_bing_html(q, count=max(rn, 10))
        return _finalize_bing_parsed(q, parse_bing_serp_html(html, max_results=rn), max_results=rn)

    if mode == "edge":
        try:
            parsed = await _edge_crawl()
            if parsed:
                return parsed
            errors.append("edge+bing: 无可解析结果")
        except Exception as e:
            errors.append(f"edge+bing: {_request_error_fragment(e)}"[:160])
    elif mode == "http":
        try:
            parsed = await _http_crawl()
            if parsed:
                return parsed
            errors.append("cn.bing.com: 无可解析结果")
        except Exception as e:
            errors.append(f"cn.bing.com: {_request_error_fragment(e)}"[:120])
    else:
        try:
            parsed = await _edge_crawl()
            if parsed:
                return parsed
            errors.append("edge+bing: 无可解析结果")
        except Exception as e:
            errors.append(f"edge+bing: {_request_error_fragment(e)}"[:160])
        try:
            parsed = await _http_crawl()
            if parsed:
                return parsed
            errors.append("cn.bing.com: 无可解析结果")
        except Exception as e:
            errors.append(f"cn.bing.com: {_request_error_fragment(e)}"[:120])

    if errors:
        raise RuntimeError(" ; ".join(errors)[:320])
    raise RuntimeError("bing: 无可用结果")
