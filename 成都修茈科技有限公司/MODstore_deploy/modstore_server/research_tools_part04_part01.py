# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.research_tools")


from modstore_server.research_tools_part04_part01_part01 import (
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
)
from modstore_server.research_tools_part04_part01_part02 import (
    build_research_context as build_research_context,
)
