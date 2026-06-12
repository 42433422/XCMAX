# -*- coding: utf-8 -*-
"""员工 agent handler：FHD LLM 补全 + 可选工具循环（精简版）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _chat_completion(messages: list[dict[str, Any]], max_tokens: int = 4000) -> dict[str, Any]:
    provider = (os.environ.get("FHD_EMPLOYEE_LLM_PROVIDER") or "deepseek").strip()
    model = (os.environ.get("FHD_EMPLOYEE_LLM_MODEL") or "deepseek-chat").strip()
    try:
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        adapter = OpenAICompatibleAdapter(provider=provider, model=model)
        if not adapter.is_configured:
            return {
                "error": "未配置 LLM API Key，请在设置中配置模型服务后再使用 agent 员工。",
                "provider": provider,
                "model": model,
            }
        return await adapter.chat_completion(messages, max_tokens=max_tokens)
    except OPERATIONAL_ERRORS as exc:
        logger.exception("employee agent LLM failed: %s", exc)
        return {"error": str(exc)[:800]}


def run_agent_handler(
    actions_cfg: dict[str, Any],
    reasoning: dict[str, Any],
    task: str,
    employee_id: str,
) -> dict[str, Any]:
    _ = actions_cfg
    agent_cfg = reasoning if isinstance(reasoning, dict) else {}
    system_prompt = str(agent_cfg.get("system_prompt") or "你是智能员工助手。")
    user_content = json.dumps(
        {
            "task": task,
            "input": agent_cfg.get("input") or {},
            "prior_reasoning": agent_cfg.get("reasoning") or "",
        },
        ensure_ascii=False,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content[:12000]},
    ]
    raw = _run_async(_chat_completion(messages))
    if raw.get("error"):
        return {"handler": "agent", "ok": False, "error": raw["error"]}
    choices = raw.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        text = str(msg.get("content") or "")
    return {
        "handler": "agent",
        "ok": True,
        "output": text,
        "llm_raw": raw,
    }


__all__ = ["run_agent_handler"]
