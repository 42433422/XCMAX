# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.research_tools")


def clean_web_company_candidate(title: str, query: str = "") -> str:
    """SERP 标题 → 联系页展示用公司全称（去来源后缀、去多余空格）。"""
    raw = _facade().re.sub("\\s+", " ", _facade().unescape((title or "").strip()))
    if len(raw) < 2:
        return ""
    if _facade().re.search("在.{0,6}市搜索", raw) or "百度地图" in raw:
        return ""
    head = raw
    for sep in (" - ", "－", " — ", " | ", "｜", "_", "＿"):
        if sep in head:
            head = head.split(sep, 1)[0].strip()
    head_compact = _facade().re.sub("\\s+", "", head)
    for marker in _facade()._TITLE_SOURCE_MARKERS:
        if head.endswith(marker):
            head = head[: -len(marker)].rstrip(" -_｜|").strip()
            head_compact = _facade().re.sub("\\s+", "", head)
    names = _facade().extract_company_names_from_text(head_compact or head, query, limit=1)
    if names and _facade().is_plausible_company_name(names[0]):
        return names[0]
    return ""


def web_search_result_titles(
    results: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    limit: int = 10,
    query: str = "",
) -> _facade().List[str]:
    """联网检索标题 → 清洗后的公司名列表（无「爱企查」等来源后缀）。"""
    out: _facade().List[str] = []
    seen: _facade().Set[str] = set()
    for it in results:
        name = _facade().clean_web_company_candidate(str(it.get("title") or ""), query)
        if not _facade().is_plausible_company_name(name):
            continue
        nk = _facade()._company_name_key(name)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(name)
        if len(out) >= max(1, limit):
            break
    return out


def contact_company_web_search_queries(query: str) -> _facade().List[str]:
    from modstore_server.contact_company_web_search import (
        contact_company_web_search_queries as impl,
    )

    return impl(query)


def contact_web_search_budget_sec() -> float:
    from modstore_server.contact_company_web_search import (
        contact_web_search_budget_sec as impl,
    )

    return impl()


def rank_contact_serp_rows(
    query: str, rows: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    from modstore_server.contact_company_web_search import (
        rank_contact_serp_rows as impl,
    )

    return impl(query, rows)


async def contact_known_site_company_lookup(
    query: str, *, max_results: int = 5
) -> _facade().List[str]:
    from modstore_server.contact_company_web_search import (
        contact_known_site_company_lookup as impl,
    )

    return await impl(query, max_results=max_results)


async def _contact_company_web_fetch_one(
    search_query: str,
    *,
    user_query: str,
    max_results: int,
    timeout_sec: float | None = None,
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], str, _facade().List[str]]:
    from modstore_server.contact_company_web_search import (
        _contact_company_web_fetch_one as impl,
    )

    return await impl(
        search_query,
        user_query=user_query,
        max_results=max_results,
        timeout_sec=timeout_sec,
    )


async def _contact_company_web_raw_results(
    query: str, *, max_results: int
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], str, _facade().List[str]]:
    from modstore_server.contact_company_web_search import (
        _contact_company_web_raw_results as impl,
    )

    return await impl(query, max_results=max_results)


async def search_company_names_via_web(
    query: str, *, max_results: int = 8
) -> _facade().Tuple[_facade().List[str], _facade().Optional[str], str]:
    from modstore_server.contact_company_web_search import (
        search_company_names_via_web as impl,
    )

    return await impl(query, max_results=max_results)


async def _web_search_free_tier(
    query: str, max_results: int
) -> _facade().Tuple[
    _facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str], str
]:
    """Tavily 之后：DDG HTML，再可选 SearXNG。返回 (results, error_summary_or_none, via_label)。"""
    err_parts: _facade().List[str] = []
    ddg_results: _facade().List[_facade().Dict[str, _facade().Any]] = []
    try:
        ddg_results = await _facade().duckduckgo_html_search(query, max_results=max_results)
    except RECOVERABLE_ERRORS as e:
        err_parts.append(f"duckduckgo: {_facade()._request_error_fragment(e)}")
    if ddg_results:
        return (ddg_results, None, "duckduckgo")
    if not err_parts:
        err_parts.append("duckduckgo: 无可用结果")
    if _facade().searxng_instance_url():
        try:
            sx = await _facade().searxng_search(query, max_results=max_results)
            if sx:
                return (sx, None, "searxng")
            err_parts.append("searxng: 无结果")
        except RECOVERABLE_ERRORS as e:
            err_parts.append(f"searxng: {_facade()._request_error_fragment(e)}")
    return ([], "；".join(err_parts)[:400], "")


async def github_repo_meta(owner: str, repo: str, token: str) -> _facade().Dict[str, _facade().Any]:
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
    except RECOVERABLE_ERRORS:
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
    allowed, _ = _facade()._today_allowed("bucket:agent_tool")
    return allowed


async def _web_results_for_llm(
    results: _facade().List[_facade().Dict[str, _facade().Any]], *, max_results: int
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
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
    rate_limit_bucket: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
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
    ck = _facade()._resolve_counter_key(
        skip_rate_limit=skip_rate_limit,
        rate_limit_bucket=rate_limit_bucket,
        user_id=user_id,
    )
    if ck is not None:
        allowed, _ = _facade()._today_allowed(ck)
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
    results, via, web_err = await _facade().web_search_with_fallback(q, max_results=rn)
    warnings: _facade().List[str] = []
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
    enriched = await _facade()._web_results_for_llm(results, max_results=rn)
    body = _facade().format_web_results_combined(enriched, per_content_cap=420)
    pages_ok = sum((1 for it in enriched if isinstance(it, dict) and it.get("page_fetched")))
    if pages_ok:
        warnings.append(f"已抓取 {pages_ok} 条链接页正文。")
    sources: _facade().List[_facade().Dict[str, str]] = []
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
    pack = "## 网页检索摘要\n\n" + _facade().truncate(body, max(500, int(max_chars)))
    return {
        "ok": True,
        "context_pack": pack,
        "sources": sources,
        "warnings": warnings,
        "via": via or "",
        "web_error": web_err,
        "error": None,
    }


async def internet_search_tool(
    query: str, *, max_results: int = 8
) -> _facade().Dict[str, _facade().Any]:
    """Agent 工具：Bing 搜索 → 抓取前 N 条链接正文 → 拼上下文。"""
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "query 过短", "text": ""}
    if not _facade().consume_agent_tool_quota():
        return {"ok": False, "error": "今日 Agent 联网检索次数已达上限", "text": ""}
    results, via, err = await _facade().web_search_with_fallback(q, max_results=max_results)
    if not results:
        return {"ok": False, "error": err or "无结果", "text": "", "via": via}
    enriched = await _facade()._web_results_for_llm(results, max_results=max_results)
    text = _facade().format_web_results_combined(enriched, per_content_cap=380)
    pages_fetched = sum((1 for it in enriched if it.get("page_fetched")))
    return {
        "ok": True,
        "text": _facade().truncate(text, 12000),
        "result_count": len(enriched),
        "via": via,
        "pages_fetched": pages_fetched,
    }


async def github_repo_snapshot_tool(
    owner: str, repo: str, *, readme_max: int = 4500
) -> _facade().Dict[str, _facade().Any]:
    """Agent 工具：GitHub 仓库公开元数据 + README 摘录。"""
    o = (owner or "").strip().strip("/")
    rname = (repo or "").strip().strip("/")
    if not o or not rname:
        return {"ok": False, "error": "owner/repo 不能为空", "text": ""}
    if not _facade().consume_agent_tool_quota():
        return {"ok": False, "error": "今日 Agent 联网检索次数已达上限", "text": ""}
    if rname.endswith(".git"):
        rname = rname[:-4]
    tok = _facade().github_token()
    lines: _facade().List[str] = [
        f"### {o}/{rname}",
        f"URL: https://github.com/{o}/{rname}",
    ]
    try:
        meta = await _facade().github_repo_meta(o, rname, tok)
        if meta:
            desc = str(meta.get("description") or "").strip()
            topics = meta.get("topics")
            if isinstance(topics, list) and topics:
                lines.append("Topics: " + ", ".join((str(t) for t in topics[:12])))
            if desc:
                lines.append("Description: " + _facade().truncate(desc, 500))
        readme = await _facade().github_readme_raw(o, rname, tok)
        if readme:
            lines.append("README（摘录）:")
            lines.append(_facade().truncate(readme, readme_max))
        body = "\n".join(lines)
        if len(lines) <= 2:
            return {
                "ok": False,
                "error": "无法读取元数据或 README（私有仓库或未授权）",
                "text": body,
            }
        return {"ok": True, "text": _facade().truncate(body, 16000)}
    except RECOVERABLE_ERRORS as e:
        return {"ok": False, "error": str(e)[:300], "text": ""}
