"""Employee Codex delegation and shared single-call cognition helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextvars import copy_context
from typing import TYPE_CHECKING, Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.infrastructure.codex.policy import RuntimeSettings


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(copy_context().run, asyncio.run, coro).result()


async def _chat_completion(
    messages: list[dict[str, Any]], max_tokens: int = 4000
) -> dict[str, Any]:
    """Non-agent cognition uses the owner-bound model route."""
    from app.infrastructure.llm.providers.registry import get_active_provider

    try:
        provider = get_active_provider()
        if provider is not None:
            result = await provider.chat_completion(messages, max_tokens=max_tokens)
            if isinstance(result, dict):
                return result
    except RECOVERABLE_ERRORS:
        logger.warning("employee model request failed")
    return {
        "error": "当前会话的模型服务不可用，请检查模型配置或重新登录。",
        "error_code": "employee_llm_not_configured",
        "retryable": False,
    }


def run_agent_handler(
    actions_cfg: dict[str, Any],
    reasoning: dict[str, Any],
    task: str,
    employee_id: str,
    *,
    workspace_root: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    gate: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    runtime_context: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    settings: RuntimeSettings | None = None,
) -> dict[str, Any]:
    """委托固定 Codex Runtime 执行 agent handler。

    ``reasoning`` 来自认知层：携带 system_prompt（已含记忆段落）与 input/prior reasoning。
    ``tools`` / ``gate`` 由 EmployeeAgent 注入（P1 接入作用域工具 + WorkspaceGuard/risk_gate）。
    """
    from app.application.employee_runtime.agent_loop import run_employee_agent_loop

    agent_cfg = reasoning if isinstance(reasoning, dict) else {}
    system_prompt = str(agent_cfg.get("system_prompt") or "你是智能员工助手。")
    input_data = dict(agent_cfg.get("input") or {})
    prior = str(agent_cfg.get("reasoning") or "").strip()
    if prior:
        input_data.setdefault("_prior_reasoning", prior[:2000])

    try:
        wall_time_limit_sec = float((actions_cfg or {}).get("wall_time_limit_sec") or 300.0)
    except (TypeError, ValueError):
        wall_time_limit_sec = 300.0
    history = agent_cfg.get("history") if isinstance(agent_cfg.get("history"), list) else None
    return run_employee_agent_loop(
        employee_id=employee_id,
        system_prompt=system_prompt,
        task=task,
        input_data=input_data,
        tools=tools,
        workspace_root=workspace_root,
        gate=gate,
        wall_time_limit_sec=max(1.0, wall_time_limit_sec),
        history=history,
        runtime_context=runtime_context,
        on_event=on_event,
        settings=settings,
    )


__all__ = ["run_agent_handler"]
