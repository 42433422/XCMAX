from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, LLMCall
from app.infrastructure.billing.model_usage import estimate_llm_cost_units
from app.infrastructure.llm.invoke import chat_completion_openai_format
from app.infrastructure.llm.providers.credentials import (
    resolve_default_chat_model,
    resolve_default_openai_provider,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def is_llm_repair_enabled(
    run: AgentRun,
    runtime_context: dict[str, Any],
) -> bool:
    plan_metadata = _plan_metadata(run)
    for container in (plan_metadata, dict(runtime_context or {})):
        policy = container.get("repair_policy")
        policy = policy if isinstance(policy, dict) else {}
        if policy.get("llm_repair") is True or policy.get("llm_repair_enabled") is True:
            return True
        if str(policy.get("mode") or "").strip().lower() in {"llm", "hybrid", "auto"}:
            return True
        if container.get("llm_repair_enabled") is True:
            return True
    return False


def llm_repair_attempt_limit(
    run: AgentRun,
    step: AgentStep,
    runtime_context: dict[str, Any],
) -> int:
    for container in (dict(runtime_context or {}), _plan_metadata(run)):
        policy = container.get("repair_policy")
        policy = policy if isinstance(policy, dict) else {}
        node_policy = policy.get(step.node_id)
        node_policy = node_policy if isinstance(node_policy, dict) else {}
        for value in (
            node_policy.get("llm_max_attempts"),
            node_policy.get("max_attempts"),
            policy.get("llm_max_attempts"),
            policy.get("max_attempts"),
            container.get("llm_repair_max_attempts"),
        ):
            parsed = _coerce_positive_int(value)
            if parsed > 0:
                return parsed
    return step.max_repair_attempts or 1


def request_llm_repair(
    run: AgentRun,
    step: AgentStep,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    response = _run_async(
        chat_completion_openai_format(
            _repair_messages(run, step, runtime_context),
            temperature=0,
            max_tokens=600,
            profile="agent_repair",
            response_format={"type": "json_object"},
        )
    )
    latency_ms = (time.perf_counter() - started) * 1000
    if not isinstance(response, dict):
        return {
            "success": False,
            "message": "LLM repair returned no response",
            "llm_call": _llm_call_from_response(
                {}, latency_ms, status="failed", error="empty response"
            ),
        }

    content = _extract_content(response)
    parsed = _extract_json_object(content)
    llm_call = _llm_call_from_response(response, latency_ms)
    if not isinstance(parsed, dict):
        llm_call.status = "failed"
        llm_call.error = "LLM repair response is not valid JSON"
        return {
            "success": False,
            "message": llm_call.error,
            "raw": content[:1000],
            "llm_call": llm_call,
        }

    params_patch = _extract_params_patch(parsed)
    if not params_patch:
        return {
            "success": False,
            "message": "LLM repair returned no params_patch",
            "raw": content[:1000],
            "llm_call": llm_call,
        }
    return {
        "success": True,
        "params_patch": params_patch,
        "reason": str(parsed.get("reason") or parsed.get("message") or ""),
        "confidence": _coerce_float(parsed.get("confidence")),
        "raw": content[:1000],
        "llm_call": llm_call,
    }


def _plan_metadata(run: AgentRun) -> dict[str, Any]:
    plan = run.metadata.get("plan")
    if not isinstance(plan, dict):
        return {}
    metadata = plan.get("metadata")
    return dict(metadata or {}) if isinstance(metadata, dict) else {}


def _repair_messages(
    run: AgentRun,
    step: AgentStep,
    runtime_context: dict[str, Any],
) -> list[dict[str, str]]:
    spec = {}
    try:
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        action_spec = get_tool_action_spec(step.tool_id, step.action)
        spec = action_spec.to_dict() if action_spec is not None else {}
    except RECOVERABLE_ERRORS:
        spec = {}
    observation = step.observations[-1] if step.observations else {}
    payload = {
        "run_id": run.run_id,
        "user_message": run.message,
        "step": {
            "node_id": step.node_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "risk": step.risk,
            "idempotent": step.idempotent,
            "current_params": step.params,
            "attempt_count": step.attempt_count,
            "error": step.error,
            "latest_observation": observation,
        },
        "tool_spec": spec,
        "runtime_hint": {
            key: value
            for key, value in dict(runtime_context or {}).items()
            if key in {"source", "task_id", "dataset_id", "workspace", "tenant_id"}
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are an Agent tool-call repair advisor. Return JSON only. "
                "You may only propose a params_patch for the same low-risk idempotent tool call. "
                "Do not change tool_id or action. Do not produce raw SQL."
            ),
        },
        {
            "role": "user",
            "content": (
                "Repair this failed tool call. Return exactly: "
                '{"params_patch": {...}, "reason": "...", "confidence": 0.0}. '
                f"Context:\n{json.dumps(payload, ensure_ascii=False, default=str)[:6000]}"
            ),
        },
    ]


def _run_async(awaitable: Awaitable[Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(awaitable)).result()


def _extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                return str(message.get("content") or "")
            return str(first.get("text") or "")
    return str(response.get("content") or response.get("text") or "")


def _extract_json_object(content: str) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _extract_params_patch(parsed: dict[str, Any]) -> dict[str, Any]:
    for key in ("params_patch", "patch_params", "set_params", "params"):
        candidate = parsed.get(key)
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _llm_call_from_response(
    response: dict[str, Any],
    latency_ms: float,
    *,
    status: str = "completed",
    error: str = "",
) -> LLMCall:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    prompt_tokens = _coerce_int(usage.get("prompt_tokens"))
    completion_tokens = _coerce_int(usage.get("completion_tokens"))
    total_tokens = _coerce_int(usage.get("total_tokens")) or prompt_tokens + completion_tokens
    cost_units = estimate_llm_cost_units(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
    provider = str(response.get("provider") or resolve_default_openai_provider() or "")
    provider_id = str(response.get("provider_id") or "")
    if not provider_id:
        provider_id = (
            "openai_compatible"
            if provider in {"xcauto", "xiuci", "openai", "deepseek"}
            else provider
        )
    return LLMCall(
        provider_id=provider_id,
        provider=provider,
        model=str(response.get("model") or resolve_default_chat_model() or ""),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        cost_units=cost_units,
        billing_status="metered" if cost_units else "unmetered",
        billing_source="estimated_token_units",
        status=status if status in {"completed", "failed"} else "completed",
        error=error,
        metadata={"source": "agent_orchestrator.llm_repair"},
    )


def _coerce_positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
