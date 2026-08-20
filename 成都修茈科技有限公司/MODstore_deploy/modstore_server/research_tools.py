# isort: skip_file
# ruff: noqa: E402, F401
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

# ── rate limits（内存计数，进程重启清零）──────────────────────────────────────
_DEFAULT_USER_CAP = 40
_counters: Dict[str, Tuple[date, int]] = {}


from modstore_server.research_tools_part01 import (
    _cap_for_key as _cap_for_key,
    _today_allowed as _today_allowed,
    _resolve_counter_key as _resolve_counter_key,
)

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


from modstore_server.research_tools_part02 import (
    _request_error_fragment as _request_error_fragment,
    searxng_instance_url as searxng_instance_url,
    _searxng_search_at_base as _searxng_search_at_base,
    _contact_searxng_fallback_bases as _contact_searxng_fallback_bases,
    searxng_search as searxng_search,
    contact_searxng_search as contact_searxng_search,
    extract_github_pairs as extract_github_pairs,
    web_search_use_tavily as web_search_use_tavily,
    tavily_api_key as tavily_api_key,
    github_token as github_token,
    truncate as truncate,
    format_web_result_item as format_web_result_item,
    tavily_search as tavily_search,
    strip_html as strip_html,
    ddg_result_url as ddg_result_url,
    duckduckgo_html_search as duckduckgo_html_search,
    web_crawl_engines_from_env as web_crawl_engines_from_env,
    web_crawl_per_engine_limit as web_crawl_per_engine_limit,
    merge_crawl_results as merge_crawl_results,
    format_web_results_combined as format_web_results_combined,
    _crawl_one_engine as _crawl_one_engine,
    web_search_crawl_parallel as web_search_crawl_parallel,
    web_search_with_fallback as web_search_with_fallback,
)

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


from modstore_server.research_tools_part03 import (
    _company_name_key as _company_name_key,
    _normalize_company_key as _normalize_company_key,
    _query_matches_company_name as _query_matches_company_name,
    sanitize_contact_company_web_error as sanitize_contact_company_web_error,
    is_plausible_company_name as is_plausible_company_name,
    extract_company_names_from_text as extract_company_names_from_text,
    _extract_companies_for_query as _extract_companies_for_query,
    contact_web_company_search_enabled as contact_web_company_search_enabled,
)

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


from modstore_server.research_tools_part04 import (
    clean_web_company_candidate as clean_web_company_candidate,
    web_search_result_titles as web_search_result_titles,
    contact_company_web_search_queries as contact_company_web_search_queries,
    contact_web_search_budget_sec as contact_web_search_budget_sec,
    rank_contact_serp_rows as rank_contact_serp_rows,
    contact_known_site_company_lookup as contact_known_site_company_lookup,
    _contact_company_web_fetch_one as _contact_company_web_fetch_one,
    _contact_company_web_raw_results as _contact_company_web_raw_results,
    search_company_names_via_web as search_company_names_via_web,
    _web_search_free_tier as _web_search_free_tier,
    github_repo_meta as github_repo_meta,
    github_readme_raw as github_readme_raw,
    consume_agent_tool_quota as consume_agent_tool_quota,
    _web_results_for_llm as _web_results_for_llm,
    fetch_web_search_context_pack as fetch_web_search_context_pack,
    internet_search_tool as internet_search_tool,
    github_repo_snapshot_tool as github_repo_snapshot_tool,
    build_research_context as build_research_context,
)
