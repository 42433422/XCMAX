# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.research_tools")


async def build_research_context(
    *,
    brief: str,
    intent: str,
    max_repos: int,
    max_chars: int,
    max_web: int,
    user_id: int,
    skip_rate_limit: bool = False,
    rate_limit_bucket: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    warnings: _facade().List[str] = []
    sources: _facade().List[_facade().Dict[str, str]] = []
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {
            "ok": False,
            "context_pack": "",
            "sources": [],
            "warnings": [],
            "error": "brief 过短",
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
    web_results, via, web_err = await _facade().web_search_with_fallback(
        search_query, max_results=12
    )
    tavily_results: _facade().List[_facade().Dict[str, _facade().Any]] = (
        await _facade()._web_results_for_llm(web_results, max_results=max_web)
    )
    pairs_ordered: _facade().List[_facade().Tuple[str, str]] = []
    if via and "+" in via:
        warnings.append(
            f"已并行爬取各引擎各 {_facade().web_crawl_per_engine_limit()} 条并综合：{via.replace('+', '、')}。"
        )
    elif via == "bing":
        warnings.append("已使用微软 Bing 网页爬虫检索结果。")
    pages_ok = sum((1 for it in tavily_results if it.get("page_fetched")))
    if pages_ok:
        warnings.append(f"已抓取 {pages_ok} 条结果链接页正文供 LLM 参考。")
    elif via == "tavily":
        warnings.append("Bing 爬虫无结果，已使用 Tavily API 兜底。")
    elif via in ("duckduckgo", "searxng"):
        warnings.append(f"已使用 {via} 检索结果（爬虫与 Tavily 均无结果）。")
    elif web_err:
        warnings.append(f"联网检索失败：{web_err}"[:220])
    blob: _facade().List[str] = []
    for it in tavily_results:
        if not isinstance(it, dict):
            continue
        blob.append(str(it.get("url") or ""))
        blob.append(str(it.get("title") or ""))
        blob.append(str(it.get("content") or ""))
        blob.append(str(it.get("page_content") or ""))
    text = "\n".join(blob) + "\n" + brief
    found = _facade().extract_github_pairs(text, limit=16)
    for pr in found:
        if pr not in pairs_ordered:
            pairs_ordered.append(pr)
    if not pairs_ordered:
        pairs_ordered = _facade().extract_github_pairs(brief, limit=8)
    token = _facade().github_token()
    sep_web = "\n\n---\n\n"
    header_web = "## 网页检索摘要\n\n"
    web_max_total = max(500, int(max_chars * 0.5))
    web_blocks: _facade().List[str] = []
    web_run_len = len(header_web)
    if tavily_results:
        for it in tavily_results[:max_web]:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            url = str(it.get("url") or "").strip()
            content = str(it.get("content") or "").strip()
            page_content = str(it.get("page_content") or "").strip()
            if not url and (not content) and (not title) and (not page_content):
                continue
            item = _facade().format_web_result_item(
                title, url, content, per_content_cap=420, page_content=page_content
            )
            sep = sep_web if web_blocks else ""
            if web_run_len + len(sep) + len(item) > web_max_total:
                room = web_max_total - web_run_len - len(sep)
                if room < 60:
                    warnings.append("网页摘要已达字数上限，部分结果未写入。")
                    break
                item = _facade().truncate(item, room)
            web_blocks.append(item)
            web_run_len += len(sep) + len(item)
            sources.append({"url": url, "title": title or url or "web", "kind": "web"})
    web_section = header_web + sep_web.join(web_blocks) if web_blocks else ""
    inter_section = "\n\n---\n\n"
    gh_head = "## GitHub 公开资料\n\n"
    gh_budget = max_chars - len(web_section) - (len(inter_section) if web_section else 0)
    gh_budget = max(0, gh_budget)
    parts: _facade().List[str] = []
    used = 0
    gh_consumed = 0
    sep_gh = "\n\n---\n\n"
    for owner, repo in pairs_ordered:
        if used >= max_repos:
            break
        url = f"https://github.com/{owner}/{repo}"
        block_lines: _facade().List[str] = [f"### {owner}/{repo}", f"URL: {url}"]
        try:
            meta = await _facade().github_repo_meta(owner, repo, token)
            if meta:
                desc = str(meta.get("description") or "").strip()
                topics = meta.get("topics")
                if isinstance(topics, list) and topics:
                    block_lines.append("Topics: " + ", ".join((str(t) for t in topics[:12])))
                if desc:
                    block_lines.append("Description: " + _facade().truncate(desc, 500))
            readme = await _facade().github_readme_raw(owner, repo, token)
            if readme:
                prefix_cost = (len(gh_head) if not parts else gh_consumed + len(sep_gh)) + len(
                    "\n".join(block_lines)
                )
                readme_cap = gh_budget - prefix_cost - len("README（摘录）:\n") - 8
                readme_cap = max(0, min(4500, readme_cap))
                if readme_cap > 80:
                    block_lines.append("README（摘录）:")
                    block_lines.append(_facade().truncate(readme, readme_cap))
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
        except RECOVERABLE_ERRORS as e:
            warnings.append(f"{owner}/{repo} 拉取失败：{e!s}"[:180])
    sections: _facade().List[str] = []
    if web_section.strip():
        sections.append(web_section.strip())
    if parts:
        sections.append(gh_head + sep_gh.join(parts))
    pack = "\n\n---\n\n".join(sections).strip() if sections else ""
    pack = _facade().truncate(pack, max_chars)
    return {"ok": True, "context_pack": pack, "sources": sources, "warnings": warnings}
