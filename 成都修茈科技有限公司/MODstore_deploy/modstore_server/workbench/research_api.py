"""Research api for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Depends, HTTPException

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.workbench.schemas import (
    WorkbenchResearchBody,
    WorkbenchWebSearchBody,
)

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class ResearchPorts:
    web_search: Callable[..., Awaitable[dict[str, Any]]]
    research: Callable[..., Awaitable[dict[str, Any]]]


async def workbench_web_search(
    body: WorkbenchWebSearchBody,
    user: User = Depends(_get_current_user),
    *,
    ports: ResearchPorts,
):
    """与 Agent `internet_search` 同源：Bing 爬虫 → Tavily → DDG/SearXNG，并抓取结果页正文。"""
    out = await ports.web_search(
        query=body.query,
        user_id=int(cast(int, user.id)),
        max_results=body.max_results,
        max_chars=body.max_chars,
    )
    if out.get("error") == "rate_limited":
        raise HTTPException(
            429, (out.get("warnings") or ["今日联网检索次数已达上限"])[0]
        )
    return out


async def workbench_research_context(
    body: WorkbenchResearchBody,
    user: User = Depends(_get_current_user),
    *,
    ports: ResearchPorts,
):
    """
    优先 Bing HTML 爬虫检索网页摘要，失败时用 Tavily 兜底（不抓取任意第三方 URL），
    并从结果与用户 brief 中解析 github.com 仓库，仅通过 api.github.com 拉取公开元数据与 README，
    拼成有上限的 context_pack。
    """
    out = await ports.research(
        brief=body.brief,
        intent=body.intent,
        max_repos=body.max_repos,
        max_chars=body.max_chars,
        max_web=body.max_web,
        user_id=cast(int, user.id),
    )
    if out.get("ok") is False and out.get("error") == "rate_limited":
        raise HTTPException(429, out.get("warnings", ["请求过于频繁"])[0])
    return out
