"""联网检索 + GitHub 公开资料（微软 Bing HTML 爬虫，Tavily 兜底，再 DDG/SearXNG）。

供工作台、每日摘要、Agent 工具、联系页公司名检索复用；支持独立速率配额。"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import date
from html import unescape
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

# ── rate limits（内存计数，进程重启清零）──────────────────────────────────────
_DEFAULT_USER_CAP = 40
_counters: Dict[str, Tuple[date, int]] = {}


def _cap_for_key(counter_key: str) -> int:
    if counter_key == "bucket:daily_digest":
        return max(1, int(os.environ.get("MODSTORE_DIGEST_RESEARCH_CAP", "64")))
    if counter_key == "bucket:agent_tool":
        return max(1, int(os.environ.get("MODSTORE_AGENT_RESEARCH_TOOL_DAILY_CAP", "80")))
    return max(1, int(os.environ.get("MODSTORE_RESEARCH_DAILY_CAP", str(_DEFAULT_USER_CAP))))


def _today_allowed(counter_key: str) -> Tuple[bool, int]:
    """返回 (allowed, count_after_increment)."""
    d = date.today()
    cap = _cap_for_key(counter_key)
    prev = _counters.get(counter_key)
    if not prev or prev[0] != d:
        _counters[counter_key] = (d, 1)
        return True, 1
    if prev[1] >= cap:
        return False, prev[1]
    n = prev[1] + 1
    _counters[counter_key] = (d, n)
    return True, n


def _resolve_counter_key(
    *,
    skip_rate_limit: bool,
    rate_limit_bucket: Optional[str],
    user_id: int,
) -> Optional[str]:
    """返回 None 表示跳过计数；否则返回计数键。"""
    if skip_rate_limit:
        return None
    if rate_limit_bucket == "daily_digest":
        return "bucket:daily_digest"
    if rate_limit_bucket == "agent_tool":
        return "bucket:agent_tool"
    return f"user:{int(user_id)}"


_GH_URL_RE = re.compile(
    r"https?://github\.com/([a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38})/([a-zA-Z0-9._-]+)",
    re.IGNORECASE,
)

_SKIP_FIRST_SEG = frozenset(
    {
        "topics",
        "apps",
        "features",
        "sponsors",
        "settings",
        "organizations",
        "explore",
        "marketplace",
        "login",
        "signup",
        "security",
        "team",
        "enterprise",
        "readme",
    }
)

_TAVILY_API_KEY_ENV_NAMES = (
    "MODSTORE_TAVILY_API_KEY",
    "TAVILY_API_KEY",
    "TVLY_API_KEY",
    "TAVILY_KEY",
)

_DDG_HTML_ENDPOINTS = (
    "https://duckduckgo.com/html/?q={query}",
    "https://html.duckduckgo.com/html/?q={query}",
    "https://lite.duckduckgo.com/lite/?q={query}",
)


def _request_error_fragment(exc: BaseException) -> str:
    """httpx 等异常在部分环境下 ``str(e)`` 为空，避免日志里出现 ``host: ;``。"""
    msg = str(exc).strip()
    if msg:
        return msg
    return type(exc).__name__


def searxng_instance_url() -> str:
    """自建 SearXNG 基址（无尾斜杠）；国内或受限网络可在未配 Tavily 时代替 DDG HTML 抓取。"""
    return (os.environ.get("MODSTORE_SEARXNG_URL") or "").strip().rstrip("/")


async def _searxng_search_at_base(base: str, query: str, max_results: int) -> List[Dict[str, Any]]:
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    params = {"q": query[:500], "format": "json", "language": "zh-CN"}
    r = await client.get(
        f"{base.rstrip('/')}/search", params=params, timeout=22.0, follow_redirects=True
    )
    r.raise_for_status()
    try:
        data = r.json()
    except Exception:
        return []
    raw = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        content_raw = it.get("content")
        if isinstance(content_raw, list):
            content = ", ".join(str(x) for x in content_raw[:6])
        else:
            content = str(content_raw or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        out.append({"title": title or url, "url": url, "content": content})
        if len(out) >= max(1, min(max_results, 15)):
            break
    return out


def _contact_searxng_fallback_bases() -> List[str]:
    raw = (os.environ.get("MODSTORE_CONTACT_SEARXNG_FALLBACKS") or "").strip()
    bases: List[str] = []
    if raw:
        bases.extend(part.strip().rstrip("/") for part in raw.split(",") if part.strip())
    primary = searxng_instance_url()
    if primary:
        bases.insert(0, primary)
    return bases


async def searxng_search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    base = searxng_instance_url()
    if not base:
        return []
    return await _searxng_search_at_base(base, query, max_results)


async def contact_searxng_search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """联系页：依次尝试自建与备用 SearXNG 实例。"""
    errors: List[str] = []
    for base in _contact_searxng_fallback_bases():
        try:
            rows = await _searxng_search_at_base(base, query, max_results)
            if rows:
                return rows
            errors.append(f"{base}: 无结果")
        except Exception as e:
            errors.append(f"{base}: {_request_error_fragment(e)}"[:100])
    if errors:
        raise RuntimeError(" ; ".join(errors)[:280])
    return []


def extract_github_pairs(text: str, limit: int = 24) -> List[Tuple[str, str]]:
    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []
    for m in _GH_URL_RE.finditer(text or ""):
        owner_l, repo_l = m.group(1).lower(), m.group(2).lower()
        if owner_l in _SKIP_FIRST_SEG:
            continue
        repo_clean = m.group(2)
        if repo_clean.endswith(".git"):
            repo_clean = repo_clean[:-4]
        if not owner_l or not repo_l:
            continue
        key = (owner_l, repo_l)
        if key in seen:
            continue
        seen.add(key)
        out.append((m.group(1), m.group(2)))
        if len(out) >= limit:
            break
    return out


def web_search_use_tavily() -> bool:
    """是否允许 Tavily 兜底（测试默认关：MODSTORE_WEB_SEARCH_USE_TAVILY=0）。"""
    raw = (os.environ.get("MODSTORE_WEB_SEARCH_USE_TAVILY") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def tavily_api_key() -> str:
    if not web_search_use_tavily():
        return ""
    for env_name in _TAVILY_API_KEY_ENV_NAMES:
        key = (os.environ.get(env_name) or "").strip()
        if key:
            return key
    return ""


def github_token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("MODSTORE_GITHUB_TOKEN") or "").strip()


def truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def format_web_result_item(
    title: str,
    url: str,
    content: str,
    per_content_cap: int = 420,
    *,
    page_content: str = "",
    per_page_cap: int = 2000,
) -> str:
    t = (title or "").strip() or "（无标题）"
    u = (url or "").strip()
    c = truncate((content or "").strip(), per_content_cap)
    p = truncate((page_content or "").strip(), per_page_cap)
    lines = [f"### {t}"]
    if u:
        lines.append(f"URL: {u}")
    if c:
        lines.append(f"摘要: {c}")
    if p:
        lines.append(f"正文: {p}")
    return "\n".join(lines)


async def tavily_search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    key = tavily_api_key()
    if not key:
        return []
    body = {
        "api_key": key,
        "query": query[:500],
        "search_depth": "basic",
        "include_answer": False,
        "max_results": max(1, min(max_results, 15)),
    }
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    r = await client.post("https://api.tavily.com/search", json=body, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    results = data.get("results")
    return results if isinstance(results, list) else []


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def ddg_result_url(raw: str) -> str:
    url = unescape(raw or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        q = parse_qs(parsed.query)
        uddg = q.get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return url


async def duckduckgo_html_search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MODstore-Workbench/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    from modstore_server.infrastructure.http_clients import get_external_client

    def _append_result(
        out: List[Dict[str, Any]],
        seen: Set[str],
        *,
        href: str,
        title_html: str,
        content_html: str = "",
    ) -> None:
        result_url = ddg_result_url(href)
        if not result_url or result_url in seen:
            return
        parsed = urlparse(result_url)
        if parsed.scheme not in ("http", "https"):
            return
        if "duckduckgo.com" in parsed.netloc.lower():
            return
        title = strip_html(title_html)
        content = strip_html(content_html)
        if not title and not content:
            return
        seen.add(result_url)
        out.append({"title": title or result_url, "url": result_url, "content": content})

    def _parse_ddg_html(html: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE,
        ):
            href, title_html = m.group(1), m.group(2)
            tail = html[m.end() : m.end() + 1800]
            snippet = re.search(
                r'<(?:a|div)[^>]+class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
                tail,
                flags=re.IGNORECASE | re.DOTALL,
            )
            _append_result(
                out,
                seen,
                href=href,
                title_html=title_html,
                content_html=snippet.group(1) if snippet else "",
            )
            if len(out) >= max_results:
                return out

        if out:
            return out

        # lite 页面没有 result__a/result__snippet 结构，回退到更宽松的 a 标签提取。
        for href, title_html in re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE,
        ):
            _append_result(out, seen, href=href, title_html=title_html)
            if len(out) >= max_results:
                break
        return out

    client = get_external_client()
    encoded_query = quote_plus(query[:500])
    errors: List[str] = []
    for endpoint_tpl in _DDG_HTML_ENDPOINTS:
        url = endpoint_tpl.format(query=encoded_query)
        try:
            r = await client.get(url, headers=headers, timeout=20.0, follow_redirects=True)
            r.raise_for_status()
            parsed_results = _parse_ddg_html(r.text or "")
            if parsed_results:
                return parsed_results
            errors.append(f"{urlparse(url).netloc} 无可解析结果")
        except Exception as e:
            errors.append(f"{urlparse(url).netloc}: {_request_error_fragment(e)}"[:160])
    if errors:
        raise RuntimeError(" ; ".join(errors)[:320])
    return []


def web_crawl_engines_from_env() -> List[str]:
    """启用的 HTML 爬虫引擎（默认仅 bing）。MODSTORE_WEB_CRAWL_ENGINES=bing"""
    raw = (os.environ.get("MODSTORE_WEB_CRAWL_ENGINES") or "bing").strip().lower()
    allowed = {"bing", "microsoft", "msedge"}
    out: List[str] = []
    for part in raw.split(","):
        key = part.strip()
        if not key or key == "baidu":
            continue
        if key in ("microsoft", "msedge"):
            key = "bing"
        if key in allowed and key not in out:
            out.append(key)
    return out or ["bing"]


def web_crawl_per_engine_limit() -> int:
    """每个搜索引擎并行抓取的结果条数（默认 5，允许 3–5）。"""
    try:
        n = int((os.environ.get("MODSTORE_WEB_CRAWL_PER_ENGINE") or "5").strip())
    except ValueError:
        n = 5
    return max(3, min(n, 5))


def merge_crawl_results(
    chunks: List[Tuple[str, List[Dict[str, Any]]]],
    *,
    total_cap: int,
) -> Tuple[List[Dict[str, Any]], str]:
    """合并多引擎并行爬取结果，按 URL 去重并保留来源标签。"""
    merged: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    via_parts: List[str] = []
    for engine, items in chunks:
        if not items:
            continue
        via_parts.append(engine)
        for it in items:
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or "").strip()
            title = str(it.get("title") or "").strip()
            key = url or title
            if not key or key in seen:
                continue
            seen.add(key)
            row = dict(it)
            row["crawl_engine"] = engine
            merged.append(row)
            if len(merged) >= total_cap:
                break
        if len(merged) >= total_cap:
            break
    return merged, "+".join(via_parts)


def format_web_results_combined(
    results: List[Dict[str, Any]], *, per_content_cap: int = 380
) -> str:
    """将并行爬取的网页结果按引擎分组，拼成综合摘要文本。"""
    if not results:
        return "（无结果）"
    by_engine: Dict[str, List[Dict[str, Any]]] = {}
    for it in results:
        eng = str(it.get("crawl_engine") or "web")
        by_engine.setdefault(eng, []).append(it)
    sections: List[str] = []
    for eng, items in by_engine.items():
        label = {"bing": "微软 Bing", "tavily": "Tavily"}.get(eng, eng)
        blocks: List[str] = []
        for it in items:
            blocks.append(
                format_web_result_item(
                    str(it.get("title") or ""),
                    str(it.get("url") or ""),
                    str(it.get("content") or ""),
                    per_content_cap=per_content_cap,
                    page_content=str(it.get("page_content") or ""),
                )
            )
        sections.append(f"## {label}（{len(blocks)} 条）\n\n" + "\n\n---\n\n".join(blocks))
    return "\n\n".join(sections)


async def _crawl_one_engine(
    engine: str, query: str, *, per_engine: int
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    try:
        if engine != "bing":
            return engine, [], None
        from modstore_server.bing_web_search import bing_html_search

        rows = await bing_html_search(query, max_results=per_engine, browser="http")
        return engine, rows or [], None
    except Exception as e:
        return engine, [], _request_error_fragment(e)[:140]


async def web_search_crawl_parallel(
    query: str, *, max_results: int = 10
) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """并行爬取各搜索引擎（每引擎 3–5 条），合并去重。返回 (results, via, errors)。"""
    q = (query or "").strip()
    if len(q) < 2:
        return [], "", ["query 过短"]
    per_engine = web_crawl_per_engine_limit()
    total_cap = max(1, min(int(max_results), 50))
    engines = web_crawl_engines_from_env()
    if not engines:
        return [], "", []

    outcomes = await asyncio.gather(
        *[_crawl_one_engine(eng, q, per_engine=per_engine) for eng in engines]
    )
    err_parts: List[str] = []
    chunks: List[Tuple[str, List[Dict[str, Any]]]] = []
    for engine, rows, err in outcomes:
        if err:
            err_parts.append(f"{engine}: {err}")
        if rows:
            chunks.append((engine, rows))

    if not chunks:
        return [], "", err_parts

    merged, via = merge_crawl_results(chunks, total_cap=total_cap)
    return merged, via, err_parts


async def web_search_with_fallback(
    query: str, max_results: int = 10
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """网页检索：多引擎并行爬虫（各 3–5 条合并）→ Tavily → DDG/SearXNG。"""
    q = (query or "").strip()
    if len(q) < 2:
        return [], "", "query 过短"
    rn = max(1, min(int(max_results), 50))
    err_parts: List[str] = []

    crawled, via, crawl_errors = await web_search_crawl_parallel(q, max_results=rn)
    err_parts.extend(crawl_errors)
    if crawled:
        return crawled, via, None

    per_engine = web_crawl_per_engine_limit()
    if tavily_api_key():
        try:
            tv = await tavily_search(q, max_results=per_engine)
            if tv:
                for it in tv:
                    if isinstance(it, dict):
                        it["crawl_engine"] = "tavily"
                return tv, "tavily", None
        except Exception as e:
            err_parts.append(f"tavily: {_request_error_fragment(e)}"[:140])

    free_results, free_err, free_via = await _web_search_free_tier(q, per_engine)
    if free_results:
        for it in free_results:
            if isinstance(it, dict):
                it["crawl_engine"] = free_via or "duckduckgo"
        return free_results, free_via or "duckduckgo", None
    if free_err:
        err_parts.append(free_err[:200])
    return [], "", (" ; ".join(err_parts) if err_parts else "无可用结果")[:320]


_COMPANY_SUFFIXES = (
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "有限公司",
    "合伙企业",
    "分公司",
    "股份公司",
)

_BAD_COMPANY_NAME_MARKERS = (
    "人民政府",
    "攻略",
    "旅游",
    "景点",
    "旅游局",
    "大盘点",
    "爱学",
    "怎么样",
    "必去",
    "百科",
    "知道",
    "黄页",
    "在成都市搜索",
    "在百度",
    "百度地图",
    "BOSS直聘",
    "猎聘",
)
_COMPANY_NAME_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9（）()·．.\-&]{2,50}?(?:"
    + "|".join(re.escape(s) for s in _COMPANY_SUFFIXES)
    + ")"
)


def _company_name_key(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().casefold())


def _normalize_company_key(name: str) -> str:
    return _company_name_key(name)


def _query_matches_company_name(query: str, name: str) -> bool:
    q = (query or "").strip()
    n = re.sub(r"\s+", "", (name or "").strip())
    if not q or not n:
        return False
    qk = _company_name_key(q)
    nk = _company_name_key(n)
    if qk in nk or nk in qk or q in n:
        return True
    m = re.match(r"^(.{2,4}?)(市)?(.+)$", qk)
    if m and not m.group(2) and m.group(3):
        alt = f"{m.group(1)}市{m.group(3)}"
        if alt in nk:
            return True
    return False


def sanitize_contact_company_web_error(raw: str | None) -> str | None:
    """联系页 API：不向访客暴露爬虫引擎名、TimeoutError 等内部信息。"""
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in ("无可用结果", "未从网页标题解析到公司全称"):
        return "联网核对暂不可用"
    low = text.lower()
    internal = (
        "timeout",
        "timeouterror",
        "connect",
        "connection",
        "ssl",
        "certificate",
        "duckduckgo",
        "bing",
        "tavily",
        "searxng",
        "playwright",
        "crawl",
        "httpx",
        "aiohttp",
        "refused",
        "reset",
        "dns",
        "proxy",
        "exception",
        "traceback",
    )
    if any(m in low for m in internal):
        return "联网核对暂不可用"
    if len(text) > 48:
        return "联网核对暂不可用"
    return text


def is_plausible_company_name(name: str) -> bool:
    """联系页展示：须含公司后缀，且排除攻略/政府等标题误识别。"""
    n = re.sub(r"\s+", "", (name or "").strip())
    if len(n) < 4 or len(n) > 80:
        return False
    if any(marker in n for marker in _BAD_COMPANY_NAME_MARKERS):
        return False
    return any(suffix in n for suffix in _COMPANY_SUFFIXES)


def extract_company_names_from_text(text: str, query: str, *, limit: int = 10) -> List[str]:
    """从网页文本启发式提取公司全称。"""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    qk = _company_name_key(q)
    out: List[str] = []
    seen: Set[str] = set()
    candidates: List[str] = []
    for m in _COMPANY_NAME_RE.finditer(unescape(text or "")):
        name = re.sub(r"\s+", "", m.group(0).strip())
        if len(name) < 4 or len(name) > 80:
            continue
        nk = _company_name_key(name)
        if nk in seen:
            continue
        if not _query_matches_company_name(q, name):
            continue
        seen.add(nk)
        candidates.append(name)
    if not candidates:
        return []
    candidates.sort(
        key=lambda n: (
            1 if _normalize_company_key(q) == _normalize_company_key(n) else 0,
            1 if _query_matches_company_name(q, n) else 0,
            len(n),
        ),
        reverse=True,
    )
    return candidates[: max(1, limit)]


def _extract_companies_for_query(blob: str, query: str, *, limit: int) -> List[str]:
    names = extract_company_names_from_text(blob, query, limit=limit)
    if names:
        return names
    q = (query or "").strip()
    if q.startswith("深圳") and not q.startswith("深圳市"):
        names = extract_company_names_from_text(blob, "深圳市" + q[2:], limit=limit)
        if names:
            return names
    skip = frozenset({"深圳", "北京", "上海", "包装", "工商", "公司", "有限公司"})
    for size in range(min(8, len(q)), 1, -1):
        for i in range(0, len(q) - size + 1):
            token = q[i : i + size]
            if token in skip:
                continue
            names = extract_company_names_from_text(blob, token, limit=limit)
            if names:
                return names
    return []


def contact_web_company_search_enabled() -> bool:
    raw = (os.environ.get("MODSTORE_CONTACT_WEB_COMPANY_SEARCH") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


_TITLE_SOURCE_MARKERS = (
    "爱企查",
    "启信宝",
    "企查查",
    "天眼查",
    "水滴信用",
    "百度百科",
    "百度知道",
    "企查猫",
    "利查查",
    "知了爱学",
    "黄页网",
    "查企业",
    "顺企网",
)


def clean_web_company_candidate(title: str, query: str = "") -> str:
    """SERP 标题 → 联系页展示用公司全称（去来源后缀、去多余空格）。"""
    raw = re.sub(r"\s+", " ", unescape((title or "").strip()))
    if len(raw) < 2:
        return ""
    if re.search(r"在.{0,6}市搜索", raw) or "百度地图" in raw:
        return ""
    head = raw
    for sep in (" - ", "－", " — ", " | ", "｜", "_", "＿"):
        if sep in head:
            head = head.split(sep, 1)[0].strip()
    # SERP 标题常在「科技」与「有限公司」之间插空格，先合并再提取
    head_compact = re.sub(r"\s+", "", head)
    for marker in _TITLE_SOURCE_MARKERS:
        if head.endswith(marker):
            head = head[: -len(marker)].rstrip(" -_｜|").strip()
            head_compact = re.sub(r"\s+", "", head)
    names = extract_company_names_from_text(head_compact or head, query, limit=1)
    if names and is_plausible_company_name(names[0]):
        return names[0]
    return ""


def web_search_result_titles(
    results: List[Dict[str, Any]], *, limit: int = 10, query: str = ""
) -> List[str]:
    """联网检索标题 → 清洗后的公司名列表（无「爱企查」等来源后缀）。"""
    out: List[str] = []
    seen: Set[str] = set()
    for it in results:
        name = clean_web_company_candidate(str(it.get("title") or ""), query)
        if not is_plausible_company_name(name):
            continue
        nk = _company_name_key(name)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(name)
        if len(out) >= max(1, limit):
            break
    return out


def _contact_web_search_timeout_sec() -> float:
    try:
        default = "28" if _contact_bing_uses_edge() else "18"
        raw = (os.environ.get("MODSTORE_CONTACT_WEB_SEARCH_TIMEOUT") or default).strip()
        return max(8.0, min(float(raw), 45.0))
    except ValueError:
        return 28.0 if _contact_bing_uses_edge() else 18.0


def _contact_bing_uses_edge() -> bool:
    contact = (os.environ.get("MODSTORE_CONTACT_WEB_BING") or "edge").strip().lower()
    if contact in ("http", "httpx"):
        return False
    if contact in ("edge", "msedge", "playwright", "browser", "auto"):
        return True
    browser = (os.environ.get("MODSTORE_BING_BROWSER") or "edge").strip().lower()
    return browser not in ("http", "httpx")


def contact_company_web_search_queries(query: str) -> List[str]:
    """联系页联网检索：用户原词 + 工商平台定向（爱企查/企查查/天眼查），不改写 API 的 q。"""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    seen: Set[str] = set()
    out: List[str] = []

    def add(item: str) -> None:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)

    add(q)
    if not is_plausible_company_name(q) and "公司" not in q:
        add(f"{q} 有限公司")
    for tpl in (
        f"{q} site:aiqicha.baidu.com",
        f"{q} site:qcc.com",
        f"{q} 企查查",
        f"{q} site:tianyancha.com",
        f"{q} 爱企查",
    ):
        add(tpl)
    return out[:6]


def _contact_query_match_core(query: str) -> str:
    qn = re.sub(r"\s+", "", (query or "").strip())
    core = qn
    m = re.match(r"^(.{2,4}?)市", core)
    if m and len(core) > len(m.group(0)) + 2:
        rest = core[len(m.group(0)) :]
        if len(rest) >= 2:
            core = rest
    return core if len(core) >= 2 else qn


def rank_contact_serp_rows(query: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """联系页 SERP 按与查询相关性排序（避免「成都市_百度百科」等泛结果压过目标公司）。"""
    if not rows:
        return []
    qn = re.sub(r"\s+", "", (query or "").strip())
    core = _contact_query_match_core(query)
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for row in rows:
        blob = re.sub(
            r"\s+",
            "",
            f"{row.get('title') or ''}{row.get('content') or ''}{row.get('url') or ''}",
        )
        score = 0
        if qn and qn in blob:
            score += 120
        if core and len(core) >= 2 and core in blob:
            score += 90
        if any(x in blob for x in ("旅游", "攻略", "景点", "大盘点", "市人民政府")):
            score -= 70
        if any(x in blob for x in ("在成都市搜索", "百度地图", "搜索 - 百度")):
            score -= 90
        if "百度百科" in blob and core and core not in blob:
            score -= 40
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    good = [row for score, row in scored if score > -25]
    return good if good else [row for _, row in scored]


async def contact_known_site_company_lookup(query: str, *, max_results: int = 5) -> List[str]:
    """从配置的官网域名 HTML 提取公司全称（不依赖搜索引擎，避免百度验证/ Bing 泛结果）。"""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    raw_domains = (os.environ.get("MODSTORE_CONTACT_COMPANY_DOMAINS") or "xiu-ci.com").strip()
    domains = [d.strip().lstrip(".") for d in raw_domains.split(",") if d.strip()]
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    found: List[str] = []
    seen: Set[str] = set()
    for domain in domains[:6]:
        for scheme in ("https", "http"):
            url = f"{scheme}://{domain}/"
            try:
                r = await client.get(url, timeout=14.0, follow_redirects=True)
                if r.status_code >= 400:
                    continue
                blob = r.text or ""
                for name in extract_company_names_from_text(blob, q, limit=max_results):
                    nk = _company_name_key(name)
                    if nk in seen or not is_plausible_company_name(name):
                        continue
                    if not _query_matches_company_name(q, name):
                        continue
                    seen.add(nk)
                    found.append(name)
                    if len(found) >= max_results:
                        return found
            except Exception:
                continue
    return found


async def _contact_company_web_fetch_one(
    search_query: str, *, user_query: str, max_results: int
) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """单条搜索词：百度 → Bing → Tavily/SearXNG/DDG（企查查式 SERP，不走官网捷径）。"""
    sq = (search_query or "").strip()
    uq = (user_query or sq).strip()
    rn = max(8, min(int(max_results), 20))
    deadline = _contact_web_search_timeout_sec()
    edge_bing = _contact_bing_uses_edge()
    per_try = min(32.0, deadline * 0.92) if edge_bing else min(11.0, deadline * 0.55)
    ddg_try = min(7.0, deadline * 0.4)
    err_parts: List[str] = []
    merged: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()
    via_labels: List[str] = []

    def _append_rows(rows: List[Dict[str, Any]], engine: str) -> None:
        for it in rows or []:
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or "").strip()
            key = url or str(it.get("title") or "").strip()
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            row = dict(it)
            row["crawl_engine"] = engine
            merged.append(row)

    def _names_from_merged() -> List[str]:
        return web_search_result_titles(merged, limit=rn, query=uq)

    async def _tavily() -> List[Dict[str, Any]]:
        return await tavily_search(sq, max_results=rn)

    async def _baidu() -> List[Dict[str, Any]]:
        from modstore_server.baidu_web_search import baidu_html_search

        return await baidu_html_search(sq, max_results=rn)

    async def _bing() -> List[Dict[str, Any]]:
        from modstore_server.bing_web_search import bing_html_search

        mode = (os.environ.get("MODSTORE_CONTACT_WEB_BING") or "edge").strip().lower()
        if mode in ("edge", "msedge", "playwright", "browser"):
            browser = "edge"
        elif mode in ("http", "httpx"):
            browser = "http"
        else:
            browser = "auto"
        return await bing_html_search(sq, max_results=rn, browser=browser)

    async def _searx() -> List[Dict[str, Any]]:
        return await contact_searxng_search(sq, max_results=rn)

    ordered: List[Tuple[str, Any]] = [
        ("baidu", _baidu()),
        ("bing", _bing()),
    ]
    if tavily_api_key():
        ordered.append(("tavily", _tavily()))
    if _contact_searxng_fallback_bases():
        ordered.append(("searxng", _searx()))

    for label, coro in ordered:
        try:
            rows = rank_contact_serp_rows(uq, await asyncio.wait_for(coro, timeout=per_try))
            if rows:
                _append_rows(rows, label)
                if label not in via_labels:
                    via_labels.append(label)
                if _names_from_merged():
                    return merged[: rn + 4], "+".join(via_labels), err_parts
        except Exception as e:
            err_parts.append(f"{label}: {_request_error_fragment(e)}"[:140])

    tasks: List[Tuple[str, Any]] = [("duckduckgo", duckduckgo_html_search(sq, max_results=rn))]

    outcomes = await asyncio.gather(
        *[
            asyncio.wait_for(coro, timeout=ddg_try if eng == "duckduckgo" else per_try)
            for eng, coro in tasks
        ],
        return_exceptions=True,
    )
    for (eng, _), outcome in zip(tasks, outcomes):
        if isinstance(outcome, BaseException):
            err_parts.append(f"{eng}: {_request_error_fragment(outcome)}"[:140])
            continue
        rows = rank_contact_serp_rows(uq, outcome or [])
        if rows:
            _append_rows(rows, eng)
            if eng not in via_labels:
                via_labels.append(eng)
            if _names_from_merged():
                return merged[: rn + 4], "+".join(via_labels), err_parts

    return merged[: rn + 4], "+".join(via_labels), err_parts


async def _contact_company_web_raw_results(
    query: str, *, max_results: int
) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """联系页联网：多搜索变体 + 百度优先（国内公司名）。"""
    return await _contact_company_web_fetch_one(query, user_query=query, max_results=max_results)


async def search_company_names_via_web(
    query: str, *, max_results: int = 8
) -> Tuple[List[str], Optional[str], str]:
    """联系页：用输入框原词联网搜索，仅从结果标题提取含「有限公司」等后缀的公司名。返回 (names, error, via)。"""
    if not contact_web_company_search_enabled():
        return [], None, ""
    q = (query or "").strip()
    if len(q) < 2:
        return [], None, ""
    err_parts: List[str] = []
    via = ""
    for sq in contact_company_web_search_queries(q):
        results, via, crawl_errors = await _contact_company_web_fetch_one(
            sq, user_query=q, max_results=max(12, max_results)
        )
        err_parts.extend(crawl_errors or [])
        if not results:
            continue
        names = web_search_result_titles(results, limit=max_results, query=q)
        if names:
            return names, None, via
    err = (" ; ".join(dict.fromkeys(err_parts)) if err_parts else "未从网页标题解析到公司全称")[
        :320
    ]
    return [], err or None, via


async def _web_search_free_tier(
    query: str, max_results: int
) -> Tuple[List[Dict[str, Any]], Optional[str], str]:
    """Tavily 之后：DDG HTML，再可选 SearXNG。返回 (results, error_summary_or_none, via_label)。"""
    err_parts: List[str] = []
    ddg_results: List[Dict[str, Any]] = []
    try:
        ddg_results = await duckduckgo_html_search(query, max_results=max_results)
    except Exception as e:
        err_parts.append(f"duckduckgo: {_request_error_fragment(e)}")
    if ddg_results:
        return ddg_results, None, "duckduckgo"
    if not err_parts:
        err_parts.append("duckduckgo: 无可用结果")

    if searxng_instance_url():
        try:
            sx = await searxng_search(query, max_results=max_results)
            if sx:
                return sx, None, "searxng"
            err_parts.append("searxng: 无结果")
        except Exception as e:
            err_parts.append(f"searxng: {_request_error_fragment(e)}")
    return [], ("；".join(err_parts))[:400], ""


async def github_repo_meta(owner: str, repo: str, token: str) -> Dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MODstore-Workbench/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}"
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    r = await client.get(url, headers=headers, timeout=20.0)
    if r.status_code != 200:
        return {}
    try:
        data = r.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def github_readme_raw(owner: str, repo: str, token: str) -> str:
    headers = {
        "Accept": "application/vnd.github.raw",
        "User-Agent": "MODstore-Workbench/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    r = await client.get(url, headers=headers, timeout=20.0)
    if r.status_code in (404, 409):
        return ""
    if r.status_code != 200:
        return ""
    raw = r.text or ""
    return raw.strip()


def consume_agent_tool_quota() -> bool:
    """每日限额（与 MODSTORE_AGENT_RESEARCH_TOOL_DAILY_CAP 相关），成功占用一格返回 True。"""
    allowed, _ = _today_allowed("bucket:agent_tool")
    return allowed


async def _web_results_for_llm(
    results: List[Dict[str, Any]], *, max_results: int
) -> List[Dict[str, Any]]:
    """SERP 结果 + 可选抓取链接正文（供 LLM）。"""
    from modstore_server.web_page_fetch import enrich_web_results_with_pages

    rows = results[:max_results]
    return await enrich_web_results_with_pages(rows)


async def fetch_web_search_context_pack(
    *,
    query: str,
    user_id: int,
    max_results: int = 8,
    max_chars: int = 8000,
    skip_rate_limit: bool = False,
    rate_limit_bucket: Optional[str] = None,
) -> Dict[str, Any]:
    """工作台直接对话：Bing/爬虫/Tavily 检索网页并拼成 LLM 上下文（不含 GitHub）。"""
    q = (query or "").strip()
    if len(q) < 2:
        return {
            "ok": False,
            "context_pack": "",
            "sources": [],
            "warnings": [],
            "via": "",
            "web_error": "query 过短",
            "error": "query 过短",
        }

    ck = _resolve_counter_key(
        skip_rate_limit=skip_rate_limit,
        rate_limit_bucket=rate_limit_bucket,
        user_id=user_id,
    )
    if ck is not None:
        allowed, _ = _today_allowed(ck)
        if not allowed:
            return {
                "ok": False,
                "context_pack": "",
                "sources": [],
                "warnings": ["今日联网检索次数已达上限，请明日再试。"],
                "via": "",
                "web_error": None,
                "error": "rate_limited",
            }

    rn = max(1, min(int(max_results), 12))
    results, via, web_err = await web_search_with_fallback(q, max_results=rn)
    warnings: List[str] = []
    if via and "+" in via:
        warnings.append(f"已并行检索：{via.replace('+', '、')}。")
    elif via == "bing":
        warnings.append("已使用 Bing 网页检索。")
    elif via == "tavily":
        warnings.append("已使用 Tavily API 检索。")
    elif via in ("duckduckgo", "searxng"):
        warnings.append(f"已使用 {via} 检索。")
    elif web_err:
        warnings.append(f"联网检索失败：{web_err}"[:220])

    enriched = await _web_results_for_llm(results, max_results=rn)
    body = format_web_results_combined(enriched, per_content_cap=420)
    pages_ok = sum(1 for it in enriched if isinstance(it, dict) and it.get("page_fetched"))
    if pages_ok:
        warnings.append(f"已抓取 {pages_ok} 条链接页正文。")

    sources: List[Dict[str, str]] = []
    for it in enriched:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        if url or title:
            sources.append({"url": url, "title": title or url, "kind": "web"})

    if not body.strip():
        return {
            "ok": False,
            "context_pack": "",
            "sources": sources,
            "warnings": warnings,
            "via": via or "",
            "web_error": web_err,
            "error": web_err or "无可用结果",
        }

    pack = "## 网页检索摘要\n\n" + truncate(body, max(500, int(max_chars)))
    return {
        "ok": True,
        "context_pack": pack,
        "sources": sources,
        "warnings": warnings,
        "via": via or "",
        "web_error": web_err,
        "error": None,
    }


async def internet_search_tool(query: str, *, max_results: int = 8) -> Dict[str, Any]:
    """Agent 工具：Bing 搜索 → 抓取前 N 条链接正文 → 拼上下文。"""
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "query 过短", "text": ""}
    if not consume_agent_tool_quota():
        return {"ok": False, "error": "今日 Agent 联网检索次数已达上限", "text": ""}
    results, via, err = await web_search_with_fallback(q, max_results=max_results)
    if not results:
        return {"ok": False, "error": err or "无结果", "text": "", "via": via}
    enriched = await _web_results_for_llm(results, max_results=max_results)
    text = format_web_results_combined(enriched, per_content_cap=380)
    pages_fetched = sum(1 for it in enriched if it.get("page_fetched"))
    return {
        "ok": True,
        "text": truncate(text, 12000),
        "result_count": len(enriched),
        "via": via,
        "pages_fetched": pages_fetched,
    }


async def github_repo_snapshot_tool(
    owner: str, repo: str, *, readme_max: int = 4500
) -> Dict[str, Any]:
    """Agent 工具：GitHub 仓库公开元数据 + README 摘录。"""
    o = (owner or "").strip().strip("/")
    rname = (repo or "").strip().strip("/")
    if not o or not rname:
        return {"ok": False, "error": "owner/repo 不能为空", "text": ""}
    if not consume_agent_tool_quota():
        return {"ok": False, "error": "今日 Agent 联网检索次数已达上限", "text": ""}
    if rname.endswith(".git"):
        rname = rname[:-4]
    tok = github_token()
    lines: List[str] = [f"### {o}/{rname}", f"URL: https://github.com/{o}/{rname}"]
    try:
        meta = await github_repo_meta(o, rname, tok)
        if meta:
            desc = str(meta.get("description") or "").strip()
            topics = meta.get("topics")
            if isinstance(topics, list) and topics:
                lines.append("Topics: " + ", ".join(str(t) for t in topics[:12]))
            if desc:
                lines.append("Description: " + truncate(desc, 500))
        readme = await github_readme_raw(o, rname, tok)
        if readme:
            lines.append("README（摘录）:")
            lines.append(truncate(readme, readme_max))
        body = "\n".join(lines)
        if len(lines) <= 2:
            return {
                "ok": False,
                "error": "无法读取元数据或 README（私有仓库或未授权）",
                "text": body,
            }
        return {"ok": True, "text": truncate(body, 16000)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "text": ""}


async def build_research_context(
    *,
    brief: str,
    intent: str,
    max_repos: int,
    max_chars: int,
    max_web: int,
    user_id: int,
    skip_rate_limit: bool = False,
    rate_limit_bucket: Optional[str] = None,
) -> Dict[str, Any]:
    warnings: List[str] = []
    sources: List[Dict[str, str]] = []

    brief = (brief or "").strip()
    if len(brief) < 3:
        return {
            "ok": False,
            "context_pack": "",
            "sources": [],
            "warnings": [],
            "error": "brief 过短",
        }

    ck = _resolve_counter_key(
        skip_rate_limit=skip_rate_limit,
        rate_limit_bucket=rate_limit_bucket,
        user_id=user_id,
    )
    if ck is not None:
        allowed, _ = _today_allowed(ck)
        if not allowed:
            return {
                "ok": False,
                "context_pack": "",
                "sources": [],
                "warnings": ["今日联网收集次数已达上限，请明日再试。"],
                "error": "rate_limited",
            }

    intent_hint = {
        "workflow": "Skill 组 画布编排 ESkill 自动化",
        "skill": "Skill 组 画布编排 ESkill 自动化",
        "mod": "后端模块 API",
        "employee": "AI 员工 Agent",
    }.get(intent, "")
    search_query = f"{brief[:400]} {intent_hint}".strip()
    max_repos = max(1, min(int(max_repos or 3), 5))
    max_web = max(1, min(int(max_web or 6), 12))
    max_chars = max(1000, min(int(max_chars or 8000), 20000))

    web_results, via, web_err = await web_search_with_fallback(search_query, max_results=12)
    tavily_results: List[Dict[str, Any]] = await _web_results_for_llm(
        web_results, max_results=max_web
    )
    pairs_ordered: List[Tuple[str, str]] = []
    if via and "+" in via:
        warnings.append(
            f"已并行爬取各引擎各 {web_crawl_per_engine_limit()} 条并综合：{via.replace('+', '、')}。"
        )
    elif via == "bing":
        warnings.append("已使用微软 Bing 网页爬虫检索结果。")
    pages_ok = sum(1 for it in tavily_results if it.get("page_fetched"))
    if pages_ok:
        warnings.append(f"已抓取 {pages_ok} 条结果链接页正文供 LLM 参考。")
    elif via == "tavily":
        warnings.append("Bing 爬虫无结果，已使用 Tavily API 兜底。")
    elif via in ("duckduckgo", "searxng"):
        warnings.append(f"已使用 {via} 检索结果（爬虫与 Tavily 均无结果）。")
    elif web_err:
        warnings.append(f"联网检索失败：{web_err}"[:220])

    blob: List[str] = []
    for it in tavily_results:
        if not isinstance(it, dict):
            continue
        blob.append(str(it.get("url") or ""))
        blob.append(str(it.get("title") or ""))
        blob.append(str(it.get("content") or ""))
        blob.append(str(it.get("page_content") or ""))
    text = "\n".join(blob) + "\n" + brief
    found = extract_github_pairs(text, limit=16)
    for pr in found:
        if pr not in pairs_ordered:
            pairs_ordered.append(pr)

    if not pairs_ordered:
        pairs_ordered = extract_github_pairs(brief, limit=8)

    token = github_token()

    sep_web = "\n\n---\n\n"
    header_web = "## 网页检索摘要\n\n"
    web_max_total = max(500, int(max_chars * 0.5))
    web_blocks: List[str] = []
    web_run_len = len(header_web)

    if tavily_results:
        for it in tavily_results[:max_web]:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            url = str(it.get("url") or "").strip()
            content = str(it.get("content") or "").strip()
            page_content = str(it.get("page_content") or "").strip()
            if not url and not content and not title and not page_content:
                continue
            item = format_web_result_item(
                title, url, content, per_content_cap=420, page_content=page_content
            )
            sep = sep_web if web_blocks else ""
            if web_run_len + len(sep) + len(item) > web_max_total:
                room = web_max_total - web_run_len - len(sep)
                if room < 60:
                    warnings.append("网页摘要已达字数上限，部分结果未写入。")
                    break
                item = truncate(item, room)
            web_blocks.append(item)
            web_run_len += len(sep) + len(item)
            sources.append(
                {
                    "url": url,
                    "title": title or url or "web",
                    "kind": "web",
                }
            )

    web_section = header_web + sep_web.join(web_blocks) if web_blocks else ""

    inter_section = "\n\n---\n\n"
    gh_head = "## GitHub 公开资料\n\n"
    gh_budget = max_chars - len(web_section) - (len(inter_section) if web_section else 0)
    gh_budget = max(0, gh_budget)

    parts: List[str] = []
    used = 0
    gh_consumed = 0
    sep_gh = "\n\n---\n\n"

    for owner, repo in pairs_ordered:
        if used >= max_repos:
            break
        url = f"https://github.com/{owner}/{repo}"
        block_lines: List[str] = [f"### {owner}/{repo}", f"URL: {url}"]
        try:
            meta = await github_repo_meta(owner, repo, token)
            if meta:
                desc = str(meta.get("description") or "").strip()
                topics = meta.get("topics")
                if isinstance(topics, list) and topics:
                    block_lines.append("Topics: " + ", ".join(str(t) for t in topics[:12]))
                if desc:
                    block_lines.append("Description: " + truncate(desc, 500))
            readme = await github_readme_raw(owner, repo, token)
            if readme:
                prefix_cost = (len(gh_head) if not parts else gh_consumed + len(sep_gh)) + len(
                    "\n".join(block_lines)
                )
                readme_cap = gh_budget - prefix_cost - len("README（摘录）:\n") - 8
                readme_cap = max(0, min(4500, readme_cap))
                if readme_cap > 80:
                    block_lines.append("README（摘录）:")
                    block_lines.append(truncate(readme, readme_cap))
            if len(block_lines) <= 2:
                warnings.append(
                    f"无法读取 {owner}/{repo} 的元数据或 README（可能为私有或 API 受限）。"
                )
                continue
            block = "\n".join(block_lines)
            if not parts:
                needed = len(gh_head) + len(block)
            else:
                needed = gh_consumed + len(sep_gh) + len(block)
            if needed > gh_budget:
                warnings.append("已达到总字数上限，后续仓库未写入。")
                break
            parts.append(block)
            sources.append({"url": url, "title": f"{owner}/{repo}", "kind": "github"})
            used += 1
            gh_consumed = needed
        except Exception as e:
            warnings.append(f"{owner}/{repo} 拉取失败：{e!s}"[:180])

    sections: List[str] = []
    if web_section.strip():
        sections.append(web_section.strip())
    if parts:
        sections.append(gh_head + sep_gh.join(parts))

    pack = "\n\n---\n\n".join(sections).strip() if sections else ""
    pack = truncate(pack, max_chars)
    return {
        "ok": True,
        "context_pack": pack,
        "sources": sources,
        "warnings": warnings,
    }
