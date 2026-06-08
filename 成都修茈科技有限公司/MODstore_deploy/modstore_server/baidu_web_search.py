"""百度搜索 SERP HTML 解析（联系页公司名联网核对，国内命中率高于 Bing）。"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict, List, Set
from urllib.parse import quote_plus, urlparse

from modstore_server.bing_web_search import strip_html

_BAIDU_SEARCH_URL = "https://www.baidu.com/s?wd={query}&rn={count}"

_BAIDU_SKIP_NETLOCS = frozenset(
    {
        "www.baidu.com",
        "baidu.com",
        "m.baidu.com",
        "map.baidu.com",
        "zhidao.baidu.com",
    }
)


def _default_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _baidu_href_skipped(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        return True
    netloc = (parsed.netloc or "").lower()
    if netloc in _BAIDU_SKIP_NETLOCS or netloc.endswith(".baidu.com"):
        return True
    return False


def parse_baidu_serp_html(html: str, *, max_results: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    blob = html or ""

    title_pat = re.compile(
        r'<h3[^>]*class="[^"]*\bt\b[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for m in title_pat.finditer(blob):
        href, title_html = m.group(1), m.group(2)
        if _baidu_href_skipped(href):
            continue
        title = strip_html(title_html)
        if not title or href in seen:
            continue
        seen.add(href)
        out.append({"title": title, "url": href, "content": ""})
        if len(out) >= max_results:
            return out

    for block in re.finditer(
        r'<div[^>]+class="[^"]*\bc-container\b[^"]*"[^>]*>(.*?)</div>\s*</div>',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        chunk = block.group(1)
        link = re.search(
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            chunk,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not link:
            continue
        href, title_html = link.group(1), link.group(2)
        if _baidu_href_skipped(href):
            continue
        title = strip_html(title_html)
        if not title or href in seen:
            continue
        seen.add(href)
        out.append({"title": title, "url": href, "content": ""})
        if len(out) >= max_results:
            break
    return out


def baidu_serp_blocked(html: str) -> bool:
    blob = html or ""
    if "百度安全验证" in blob or "网络不给力" in blob:
        return True
    if len(blob) < 12_000 and "c-container" not in blob and 'class="t "' not in blob:
        return True
    return False


async def baidu_html_search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    rn = max(1, min(int(max_results), 50))
    url = _BAIDU_SEARCH_URL.format(query=quote_plus(q[:500]), count=max(rn, 10))
    headers = _default_headers()
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    await client.get("https://www.baidu.com/", headers=headers, timeout=18.0, follow_redirects=True)
    headers = {**headers, "Referer": "https://www.baidu.com/"}
    r = await client.get(url, headers=headers, timeout=22.0, follow_redirects=True)
    r.raise_for_status()
    html = r.text or ""
    if baidu_serp_blocked(html):
        raise RuntimeError("百度返回安全验证页")
    return parse_baidu_serp_html(html, max_results=rn)
