# mypy: disable-error-code="arg-type, attr-defined, no-any-return, valid-type"
"""联系页公司名联网检索（总墙钟预算 + 多引擎 SERP）。

从 research_tools 拆出，避免 oversized 文件继续膨胀。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.research_tools import (
    _company_name_key,
    _contact_searxng_fallback_bases,
    _query_matches_company_name,
    _request_error_fragment,
    contact_searxng_search,
    contact_web_company_search_enabled,
    duckduckgo_html_search,
    extract_company_names_from_text,
    is_plausible_company_name,
    tavily_api_key,
    tavily_search,
    web_search_result_titles,
)


def _contact_web_search_timeout_sec() -> float:
    try:
        default = "28" if _contact_bing_uses_edge() else "18"
        raw = (os.environ.get("MODSTORE_CONTACT_WEB_SEARCH_TIMEOUT") or default).strip()
        return max(8.0, min(float(raw), 45.0))
    except ValueError:
        return 28.0 if _contact_bing_uses_edge() else 18.0


def contact_web_search_budget_sec() -> float:
    """联系页联网检索总墙钟预算（公网 UX：超时后立即退回本地库）。"""
    try:
        raw = (os.environ.get("MODSTORE_CONTACT_WEB_SEARCH_BUDGET") or "5").strip()
        return max(2.0, min(float(raw), 20.0))
    except ValueError:
        return 5.0


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
            except RECOVERABLE_ERRORS:
                continue
    return found


async def _contact_company_web_fetch_one(
    search_query: str,
    *,
    user_query: str,
    max_results: int,
    timeout_sec: float | None = None,
) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """单条搜索词：百度 → Bing → Tavily/SearXNG/DDG（企查查式 SERP，不走官网捷径）。"""
    sq = (search_query or "").strip()
    uq = (user_query or sq).strip()
    rn = max(8, min(int(max_results), 20))
    deadline = (
        max(1.0, float(timeout_sec))
        if timeout_sec is not None
        else _contact_web_search_timeout_sec()
    )
    edge_bing = _contact_bing_uses_edge()
    per_try = min(32.0, deadline * 0.92) if edge_bing else min(11.0, deadline * 0.55)
    # 公网短预算下压低单引擎等待，避免 Edge Playwright 拖死整次请求
    if timeout_sec is not None:
        per_try = min(per_try, max(1.2, deadline * 0.55))
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
        except RECOVERABLE_ERRORS as e:
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
    budget = contact_web_search_budget_sec()
    deadline = time.monotonic() + budget
    for sq in contact_company_web_search_queries(q):
        remaining = deadline - time.monotonic()
        if remaining <= 0.25:
            err_parts.append("budget_exhausted")
            break
        try:
            results, via, crawl_errors = await asyncio.wait_for(
                _contact_company_web_fetch_one(
                    sq,
                    user_query=q,
                    max_results=max(12, max_results),
                    timeout_sec=remaining,
                ),
                timeout=remaining,
            )
        except TimeoutError:
            err_parts.append("timeout")
            break
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
