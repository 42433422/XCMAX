"""员工 agent handler：多轮工具调用循环（委托 agent_loop）。

历史上这里是单轮 ``_chat_completion``；现在 ``run_agent_handler`` 委托
``agent_loop.run_employee_agent_loop`` 做真正的多轮 function-calling。
``_chat_completion`` / ``_run_async`` 仍保留，供 executor 的认知层（cognition）单轮补全复用。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextvars import copy_context
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
    """Cognition uses the same owner-bound route as Planner and the Agent loop."""
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
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """委托多轮 function-calling 循环执行 agent handler。

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

    max_iters = max_iterations
    if max_iters is None:
        try:
            max_iters = int((actions_cfg or {}).get("max_iterations") or 0) or None
        except (TypeError, ValueError):
            max_iters = None
    try:
        wall_time_limit_sec = float((actions_cfg or {}).get("wall_time_limit_sec") or 300.0)
    except (TypeError, ValueError):
        wall_time_limit_sec = 300.0
    try:
        repeat_limit = int((actions_cfg or {}).get("repeat_limit") or 3)
    except (TypeError, ValueError):
        repeat_limit = 3

    return run_employee_agent_loop(
        employee_id=employee_id,
        system_prompt=system_prompt,
        task=task,
        input_data=input_data,
        tools=tools,
        workspace_root=workspace_root,
        gate=gate,
        max_iterations=max_iters or 6,
        wall_time_limit_sec=max(1.0, wall_time_limit_sec),
        repeat_limit=max(2, repeat_limit),
    )


__all__ = ["run_agent_handler"]
