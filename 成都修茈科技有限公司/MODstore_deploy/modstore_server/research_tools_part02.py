# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.research_tools")


def _request_error_fragment(exc: BaseException) -> str:
    """httpx 等异常在部分环境下 ``str(e)`` 为空，避免日志里出现 ``host: ;``。"""
    msg = str(exc).strip()
    if msg:
        return msg
    return type(exc).__name__


def searxng_instance_url() -> str:
    """自建 SearXNG 基址（无尾斜杠）；国内或受限网络可在未配 Tavily 时代替 DDG HTML 抓取。"""
    return (_facade().os.environ.get("MODSTORE_SEARXNG_URL") or "").strip().rstrip("/")


async def _searxng_search_at_base(
    base: str, query: str, max_results: int
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    from modstore_server.infrastructure.http_clients import get_external_client

    client = get_external_client()
    params = {"q": query[:500], "format": "json", "language": "zh-CN"}
    r = await client.get(
        f"{base.rstrip('/')}/search", params=params, timeout=22.0, follow_redirects=True
    )
    r.raise_for_status()
    try:
        data = r.json()
    except RECOVERABLE_ERRORS:
        return []
    raw = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        content_raw = it.get("content")
        if isinstance(content_raw, list):
            content = ", ".join((str(x) for x in content_raw[:6]))
        else:
            content = str(content_raw or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        out.append({"title": title or url, "url": url, "content": content})
        if len(out) >= max(1, min(max_results, 15)):
            break
    return out


def _contact_searxng_fallback_bases() -> _facade().List[str]:
    raw = (_facade().os.environ.get("MODSTORE_CONTACT_SEARXNG_FALLBACKS") or "").strip()
    bases: _facade().List[str] = []
    if raw:
        bases.extend((part.strip().rstrip("/") for part in raw.split(",") if part.strip()))
    primary = _facade().searxng_instance_url()
    if primary:
        bases.insert(0, primary)
    return bases


async def searxng_search(
    query: str, max_results: int = 10
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    base = _facade().searxng_instance_url()
    if not base:
        return []
    return await _facade()._searxng_search_at_base(base, query, max_results)


async def contact_searxng_search(
    query: str, max_results: int = 10
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """联系页：依次尝试自建与备用 SearXNG 实例。"""
    errors: _facade().List[str] = []
    for base in _facade()._contact_searxng_fallback_bases():
        try:
            rows = await _facade()._searxng_search_at_base(base, query, max_results)
            if rows:
                return rows
            errors.append(f"{base}: 无结果")
        except RECOVERABLE_ERRORS as e:
            errors.append(f"{base}: {_facade()._request_error_fragment(e)}"[:100])
    if errors:
        raise RuntimeError(" ; ".join(errors)[:280])
    return []


def extract_github_pairs(text: str, limit: int = 24) -> _facade().List[_facade().Tuple[str, str]]:
    seen: _facade().Set[_facade().Tuple[str, str]] = set()
    out: _facade().List[_facade().Tuple[str, str]] = []
    for m in _facade()._GH_URL_RE.finditer(text or ""):
        owner_l, repo_l = (m.group(1).lower(), m.group(2).lower())
        if owner_l in _facade()._SKIP_FIRST_SEG:
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
    raw = (_facade().os.environ.get("MODSTORE_WEB_SEARCH_USE_TAVILY") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def tavily_api_key() -> str:
    if not _facade().web_search_use_tavily():
        return ""
    for env_name in _facade()._TAVILY_API_KEY_ENV_NAMES:
        key = (_facade().os.environ.get(env_name) or "").strip()
        if key:
            return key
    return ""


def github_token() -> str:
    return (
        _facade().os.environ.get("GITHUB_TOKEN")
        or _facade().os.environ.get("MODSTORE_GITHUB_TOKEN")
        or ""
    ).strip()


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
    c = _facade().truncate((content or "").strip(), per_content_cap)
    p = _facade().truncate((page_content or "").strip(), per_page_cap)
    lines = [f"### {t}"]
    if u:
        lines.append(f"URL: {u}")
    if c:
        lines.append(f"摘要: {c}")
    if p:
        lines.append(f"正文: {p}")
    return "\n".join(lines)


async def tavily_search(
    query: str, max_results: int = 10
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    key = _facade().tavily_api_key()
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
    text = _facade().re.sub("<[^>]+>", " ", value or "")
    text = _facade().unescape(text)
    return _facade().re.sub("\\s+", " ", text).strip()


def is_duckduckgo_host(hostname: str | None) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == "duckduckgo.com" or host.endswith(".duckduckgo.com")


def ddg_result_url(raw: str) -> str:
    url = _facade().unescape(raw or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = _facade().urlparse(url)
    if is_duckduckgo_host(parsed.hostname) and parsed.path.startswith("/l/"):
        q = _facade().parse_qs(parsed.query)
        uddg = q.get("uddg", [""])[0]
        if uddg:
            return _facade().unquote(uddg)
    return url


async def duckduckgo_html_search(
    query: str, max_results: int = 10
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MODstore-Workbench/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    from modstore_server.infrastructure.http_clients import get_external_client

    def _append_result(
        out: _facade().List[_facade().Dict[str, _facade().Any]],
        seen: _facade().Set[str],
        *,
        href: str,
        title_html: str,
        content_html: str = "",
    ) -> None:
        result_url = _facade().ddg_result_url(href)
        if not result_url or result_url in seen:
            return
        parsed = _facade().urlparse(result_url)
        if parsed.scheme not in ("http", "https"):
            return
        if is_duckduckgo_host(parsed.hostname):
            return
        title = _facade().strip_html(title_html)
        content = _facade().strip_html(content_html)
        if not title and (not content):
            return
        seen.add(result_url)
        out.append({"title": title or result_url, "url": result_url, "content": content})

    def _parse_ddg_html(
        html: str,
    ) -> _facade().List[_facade().Dict[str, _facade().Any]]:
        out: _facade().List[_facade().Dict[str, _facade().Any]] = []
        seen: _facade().Set[str] = set()
        for m in _facade().re.finditer(
            '<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=_facade().re.IGNORECASE,
        ):
            href, title_html = (m.group(1), m.group(2))
            tail = html[m.end() : m.end() + 1800]
            snippet = _facade().re.search(
                '<(?:a|div)[^>]+class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
                tail,
                flags=_facade().re.IGNORECASE | _facade().re.DOTALL,
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
        for href, title_html in _facade().re.findall(
            '<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=_facade().re.IGNORECASE
        ):
            _append_result(out, seen, href=href, title_html=title_html)
            if len(out) >= max_results:
                break
        return out

    client = get_external_client()
    encoded_query = _facade().quote_plus(query[:500])
    errors: _facade().List[str] = []
    for endpoint_tpl in _facade()._DDG_HTML_ENDPOINTS:
        url = endpoint_tpl.format(query=encoded_query)
        try:
            r = await client.get(url, headers=headers, timeout=20.0, follow_redirects=True)
            r.raise_for_status()
            parsed_results = _parse_ddg_html(r.text or "")
            if parsed_results:
                return parsed_results
            errors.append(f"{_facade().urlparse(url).netloc} 无可解析结果")
        except RECOVERABLE_ERRORS as e:
            errors.append(
                f"{_facade().urlparse(url).netloc}: {_facade()._request_error_fragment(e)}"[:160]
            )
    if errors:
        raise RuntimeError(" ; ".join(errors)[:320])
    return []


def web_crawl_engines_from_env() -> _facade().List[str]:
    """启用的 HTML 爬虫引擎（默认仅 bing）。MODSTORE_WEB_CRAWL_ENGINES=bing"""
    raw = (_facade().os.environ.get("MODSTORE_WEB_CRAWL_ENGINES") or "bing").strip().lower()
    allowed = {"bing", "microsoft", "msedge"}
    out: _facade().List[str] = []
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
        n = int((_facade().os.environ.get("MODSTORE_WEB_CRAWL_PER_ENGINE") or "5").strip())
    except ValueError:
        n = 5
    return max(3, min(n, 5))


def merge_crawl_results(
    chunks: _facade().List[
        _facade().Tuple[str, _facade().List[_facade().Dict[str, _facade().Any]]]
    ],
    *,
    total_cap: int,
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], str]:
    """合并多引擎并行爬取结果，按 URL 去重并保留来源标签。"""
    merged: _facade().List[_facade().Dict[str, _facade().Any]] = []
    seen: _facade().Set[str] = set()
    via_parts: _facade().List[str] = []
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
    return (merged, "+".join(via_parts))


def format_web_results_combined(
    results: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    per_content_cap: int = 380,
) -> str:
    """将并行爬取的网页结果按引擎分组，拼成综合摘要文本。"""
    if not results:
        return "（无结果）"
    by_engine: _facade().Dict[str, _facade().List[_facade().Dict[str, _facade().Any]]] = {}
    for it in results:
        eng = str(it.get("crawl_engine") or "web")
        by_engine.setdefault(eng, []).append(it)
    sections: _facade().List[str] = []
    for eng, items in by_engine.items():
        label = {"bing": "微软 Bing", "tavily": "Tavily"}.get(eng, eng)
        blocks: _facade().List[str] = []
        for it in items:
            blocks.append(
                _facade().format_web_result_item(
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
) -> _facade().Tuple[
    str, _facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str]
]:
    try:
        if engine != "bing":
            return (engine, [], None)
        from modstore_server.bing_web_search import bing_html_search

        rows = await bing_html_search(query, max_results=per_engine, browser="http")
        return (engine, rows or [], None)
    except RECOVERABLE_ERRORS as e:
        return (engine, [], _facade()._request_error_fragment(e)[:140])


async def web_search_crawl_parallel(
    query: str, *, max_results: int = 10
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], str, _facade().List[str]]:
    """并行爬取各搜索引擎（每引擎 3–5 条），合并去重。返回 (results, via, errors)。"""
    q = (query or "").strip()
    if len(q) < 2:
        return ([], "", ["query 过短"])
    per_engine = _facade().web_crawl_per_engine_limit()
    total_cap = max(1, min(int(max_results), 50))
    engines = _facade().web_crawl_engines_from_env()
    if not engines:
        return ([], "", [])
    outcomes = await _facade().asyncio.gather(
        *[_facade()._crawl_one_engine(eng, q, per_engine=per_engine) for eng in engines]
    )
    err_parts: _facade().List[str] = []
    chunks: _facade().List[
        _facade().Tuple[str, _facade().List[_facade().Dict[str, _facade().Any]]]
    ] = []
    for engine, rows, err in outcomes:
        if err:
            err_parts.append(f"{engine}: {err}")
        if rows:
            chunks.append((engine, rows))
    if not chunks:
        return ([], "", err_parts)
    merged, via = _facade().merge_crawl_results(chunks, total_cap=total_cap)
    return (merged, via, err_parts)


async def web_search_with_fallback(
    query: str, max_results: int = 10
) -> _facade().Tuple[
    _facade().List[_facade().Dict[str, _facade().Any]], str, _facade().Optional[str]
]:
    """网页检索：多引擎并行爬虫（各 3–5 条合并）→ Tavily → DDG/SearXNG。"""
    q = (query or "").strip()
    if len(q) < 2:
        return ([], "", "query 过短")
    rn = max(1, min(int(max_results), 50))
    err_parts: _facade().List[str] = []
    crawled, via, crawl_errors = await _facade().web_search_crawl_parallel(q, max_results=rn)
    err_parts.extend(crawl_errors)
    if crawled:
        return (crawled, via, None)
    per_engine = _facade().web_crawl_per_engine_limit()
    if _facade().tavily_api_key():
        try:
            tv = await _facade().tavily_search(q, max_results=per_engine)
            if tv:
                for it in tv:
                    if isinstance(it, dict):
                        it["crawl_engine"] = "tavily"
                return (tv, "tavily", None)
        except RECOVERABLE_ERRORS as e:
            err_parts.append(f"tavily: {_facade()._request_error_fragment(e)}"[:140])
    free_results, free_err, free_via = await _facade()._web_search_free_tier(q, per_engine)
    if free_results:
        for it in free_results:
            if isinstance(it, dict):
                it["crawl_engine"] = free_via or "duckduckgo"
        return (free_results, free_via or "duckduckgo", None)
    if free_err:
        err_parts.append(free_err[:200])
    return ([], "", (" ; ".join(err_parts) if err_parts else "无可用结果")[:320])
