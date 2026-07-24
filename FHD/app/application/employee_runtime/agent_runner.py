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


def _resolve_employee_llm_fallback_config(
    primary_provider: str,
) -> dict[str, str | None] | None:
    provider = (os.environ.get("FHD_EMPLOYEE_LLM_FALLBACK_PROVIDER") or "").strip()
    if not provider or provider.lower() == primary_provider.lower():
        return None
    return {
        "provider": provider,
        "model": (os.environ.get("FHD_EMPLOYEE_LLM_FALLBACK_MODEL") or "").strip() or None,
        "api_key": None,
        "base_url": (os.environ.get("FHD_EMPLOYEE_LLM_FALLBACK_BASE_URL") or "").strip() or None,
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
    from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

    primary_error = ""
    primary_model = str(model) if model else None
    try:
        adapter = OpenAICompatibleAdapter(
            provider=provider,
            model=primary_model,
            api_key=cfg.get("api_key"),
            base_url=cfg.get("base_url"),
        )
        if not adapter.is_configured:
            primary_error = "未配置 LLM API Key，请在设置中配置模型服务后再使用 agent 员工。"
            primary_model = adapter.model_name
        else:
            return await adapter.chat_completion(messages, max_tokens=max_tokens)
    except RECOVERABLE_ERRORS as exc:
        primary_error = str(exc)[:800]
        logger.warning("employee primary LLM failed; trying configured fallback")

    fallback_cfg = _resolve_employee_llm_fallback_config(provider)
    if fallback_cfg:
        fallback_provider = str(fallback_cfg.get("provider") or "").strip()
        fallback_model = fallback_cfg.get("model")
        try:
            fallback = OpenAICompatibleAdapter(
                provider=fallback_provider,
                model=str(fallback_model) if fallback_model else None,
                api_key=fallback_cfg.get("api_key"),
                base_url=fallback_cfg.get("base_url"),
            )
            if fallback.is_configured:
                result = await fallback.chat_completion(messages, max_tokens=max_tokens)
                result["_fallback_used"] = True
                result["_primary_provider"] = provider
                result["_primary_error"] = primary_error
                result["_fallback_provider"] = fallback_provider
                result["_fallback_model"] = fallback.model_name
                return result
        except RECOVERABLE_ERRORS as exc:
            logger.exception("employee fallback LLM failed")
            return {"error": f"{primary_error}; fallback failed: {str(exc)[:400]}"[:800]}

    if primary_error:
        logger.error("employee agent LLM failed")
        return {
            "error": primary_error,
            "provider": provider,
            "model": primary_model,
        }
    return {
        "error": "employee LLM unavailable",
        "provider": provider,
        "model": primary_model,
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
