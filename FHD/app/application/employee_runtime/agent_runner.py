"""员工 agent handler：多轮工具调用循环（委托 agent_loop）。

历史上这里是单轮 ``_chat_completion``；现在 ``run_agent_handler`` 委托
``agent_loop.run_employee_agent_loop`` 做真正的多轮 function-calling。
``_chat_completion`` / ``_run_async`` 仍保留，供 executor 的认知层（cognition）单轮补全复用。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
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
        return pool.submit(asyncio.run, coro).result()


def _resolve_employee_llm_config() -> dict[str, str | None]:
    provider_override = (os.environ.get("FHD_EMPLOYEE_LLM_PROVIDER") or "").strip()
    model_override = (os.environ.get("FHD_EMPLOYEE_LLM_MODEL") or "").strip()
    if provider_override:
        return {
            "provider": provider_override,
            "model": model_override or None,
            "api_key": None,
            "base_url": None,
        }

    from app.infrastructure.llm.providers.credentials import (
        resolve_default_chat_model,
        resolve_default_openai_provider,
        resolve_openai_env_credentials,
    )

    api_key, base_url = resolve_openai_env_credentials()
    return {
        "provider": resolve_default_openai_provider(),
        "model": model_override or resolve_default_chat_model(),
        "api_key": api_key or None,
        "base_url": base_url,
    }


async def _chat_completion(
    messages: list[dict[str, Any]], max_tokens: int = 4000
) -> dict[str, Any]:
    """认知层单轮补全（内部 API）。

    .. deprecated::
        agent handler 已迁移至 ``agent_loop.run_employee_agent_loop`` 多轮循环；
        本函数仅供 ``executor._cognition_fhd`` 认知阶段使用，勿在新代码中直接调用。
    """
    cfg = _resolve_employee_llm_config()
    provider = str(cfg.get("provider") or "").strip() or "xcauto"
    model = cfg.get("model")
    try:
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        adapter = OpenAICompatibleAdapter(
            provider=provider,
            model=str(model) if model else None,
            api_key=cfg.get("api_key"),
            base_url=cfg.get("base_url"),
        )
        if not adapter.is_configured:
            return {
                "error": "未配置 LLM API Key，请在设置中配置模型服务后再使用 agent 员工。",
                "provider": provider,
                "model": adapter.model_name,
            }
        return await adapter.chat_completion(messages, max_tokens=max_tokens)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("employee agent LLM failed: %s", exc)
        return {"error": str(exc)[:800]}


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

    return run_employee_agent_loop(
        employee_id=employee_id,
        system_prompt=system_prompt,
        task=task,
        input_data=input_data,
        tools=tools,
        workspace_root=workspace_root,
        gate=gate,
        max_iterations=max_iters or 6,
    )


__all__ = ["run_agent_handler"]
