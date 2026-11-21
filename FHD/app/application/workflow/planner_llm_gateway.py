from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections import Counter
from contextlib import aclosing, asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any

from app.domain.model_admission_errors import (
    ModelCircuitOpenError,
    ModelConcurrencyLimitError,
    ModelRateLimitError,
)
from app.infrastructure.modstore_transport import MarketModelError
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
from app.utils.resilience.rate_limiter import RateLimitBackendError

MODEL_REQUEST_ERRORS = (
    MarketModelError,
    ModelCircuitOpenError,
    ModelConcurrencyLimitError,
    ModelRateLimitError,
    RateLimitBackendError,
)

logger = logging.getLogger(__name__)

_ENV_MAX_TOKENS = "XCAGI_PLANNER_MAX_TOKENS"
# 推理模型（如 MiMo / MiniMax M3）会先消耗 reasoning token，1200 的旧默认
# 会让正文为空（finish_reason=length）。默认放宽到 4096，仍可用环境变量收紧。
_DEFAULT_MAX_TOKENS = 4096


@contextmanager
def planner_model_budget(context: dict[str, Any] | None):
    """Share the existing trusted I/O deadline across classification, repair and review."""
    from app.application.tool_execution_deadline import InvocationBudget, invocation_deadline

    budget = (context or {}).get("_planner_model_budget")
    if not isinstance(budget, InvocationBudget):
        try:
            seconds = float(os.environ.get("XCAGI_PLANNER_TIMEOUT_SECONDS", "90"))
        except ValueError:
            seconds = 90.0
        seconds = max(1.0, min(300.0, seconds)) if math.isfinite(seconds) else 90.0
        budget = InvocationBudget(time.monotonic() + seconds)
    with invocation_deadline(budget.deadline) as active:
        if context is not None:
            # A JSON client cannot supply this object. It is not model evidence
            # or a durable task budget and must be discarded before execution.
            context["_planner_model_budget"] = active
        yield active


def _provider_failure(error: Exception) -> MarketModelError | None:
    """Normalize SDK/HTTP failures without copying provider text or request data."""
    import httpx
    from openai import APIConnectionError, APIError, APITimeoutError

    from app.infrastructure.llm.model_context_windows import ModelOutputLimitExceeded

    if isinstance(error, MarketModelError):
        return error
    status = getattr(error, "status_code", None) or getattr(
        getattr(error, "response", None), "status_code", None
    )
    if isinstance(status, int) and 400 <= status <= 599:
        return MarketModelError({"status": status})
    if isinstance(error, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
        return MarketModelError({"status": 504})
    if isinstance(error, (OSError, httpx.TransportError, APIConnectionError)):
        return MarketModelError({"status": 503}, code="model_connection_failed")
    if isinstance(error, ModelOutputLimitExceeded):
        return MarketModelError({"status": 400}, code="model_output_budget_exceeded")
    if isinstance(error, ValueError):
        return MarketModelError({"status": 502}, code="model_response_invalid")
    if isinstance(error, (RuntimeError, APIError)):
        return MarketModelError({"status": 502})
    return None


def record_planning_failure(context: dict[str, Any], error: Exception, *, stage="planning"):
    """Preserve a safe machine-readable failure; never turn outages into missing user input."""
    from app.application.agent_orchestrator.context_window_manager import ContextWindowExceeded
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    if isinstance(error, ContextWindowExceeded):
        context.update(
            planning_failure_reason=str(error),
            planning_failure_kind="planner_error",
            planning_failure_retryable=False,
            planning_failure_status=413,
            planning_failure_stage=stage,
            _planning_failure_code="context_window_exceeded",
        )
        context.pop("goal_coverage_rejected", None)
        return
    if isinstance(error, ConversationRevisionError):
        context.update(
            planning_failure_reason="会话已更新或删除，请重新发送本次请求。",
            planning_failure_kind="conversation_changed",
            planning_failure_retryable=False,
            planning_failure_status=409,
            planning_failure_stage=stage,
            _planning_failure_code="conversation_changed",
        )
        context.pop("goal_coverage_rejected", None)
        return

    failure: (
        MarketModelError
        | ModelCircuitOpenError
        | ModelConcurrencyLimitError
        | ModelRateLimitError
        | None
    )
    if isinstance(error, (ModelCircuitOpenError, ModelConcurrencyLimitError, ModelRateLimitError)):
        failure, status, retryable = (
            error,
            503 if isinstance(error, ModelCircuitOpenError) else 429,
            True,
        )
    elif isinstance(error, RateLimitBackendError):
        failure, status, retryable = MarketModelError({"status": 503}), 503, True
    else:
        failure = _provider_failure(error)
        if failure is None:
            raise error
        status, retryable = failure.status_code, failure.retryable
    context.update(
        planning_failure_reason=str(failure),
        planning_failure_kind=failure.code,
        planning_failure_retryable=retryable,
        planning_failure_status=status,
        planning_failure_stage=stage,
        _planning_failure_code=failure.code,
    )
    context.pop("goal_coverage_rejected", None)


def _validate_completion(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise MarketModelError({"status": 502}, code="model_response_invalid")
    choices = result.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(first, dict):
        raise MarketModelError({"status": 502}, code="model_response_invalid")
    message = first.get("message")
    code = "model_response_invalid"
    if first.get("finish_reason") == "length":
        code = "model_output_truncated"
    elif isinstance(message, dict) and (
        message.get("refusal") or first.get("finish_reason") == "content_filter"
    ):
        code = "model_response_blocked"
    elif isinstance(message, dict) and (
        (isinstance(message.get("content"), str) and message["content"].strip())
        or message.get("tool_calls")
        or message.get("function_call")
    ):
        return result
    raise MarketModelError({"status": 502}, code=code)


@contextmanager
def _provider_errors():
    from app.application.agent_orchestrator.context_window_manager import ContextWindowExceeded
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    from .retry_policy import retry_manages_transport_error

    try:
        yield
    except BOUNDARY_ERRORS as exc:
        if isinstance(
            exc,
            (
                ContextWindowExceeded,
                ConversationRevisionError,
                MarketModelError,
                ModelCircuitOpenError,
                ModelConcurrencyLimitError,
                ModelRateLimitError,
                RateLimitBackendError,
            ),
        ) or retry_manages_transport_error(exc):
            raise
        failure = _provider_failure(exc)
        if failure is None:
            raise
        logger.warning("planner model request failed: %s", type(exc).__name__)
        raise failure from exc


@asynccontextmanager
async def _model_request_deadline(context):
    from app.application.tool_execution_deadline import (
        check_invocation_deadline,
        remaining_invocation_seconds,
    )

    with planner_model_budget(context):
        timeout = asyncio.timeout(remaining_invocation_seconds(math.inf))
        try:
            async with timeout:
                check_invocation_deadline()
                yield
                check_invocation_deadline()
        except TimeoutError as exc:
            if timeout.expired() or remaining_invocation_seconds(math.inf) <= 0:
                raise MarketModelError({"status": 504}, code="model_deadline_exceeded") from exc
            raise


def _compact_tool_registry(prompt: dict[str, Any]) -> None:
    """Pool identical whole schemas without changing their local reference scope."""
    registry = prompt.get("tool_registry")
    if not isinstance(registry, list) or "tool_schemas" in prompt:
        return
    actions = [
        (tool, action)
        for tool in registry
        if isinstance(tool, dict) and isinstance(tool.get("actions"), list)
        for action in tool["actions"]
        if isinstance(action, dict)
    ]
    schemas = [
        (
            action,
            key,
            json.dumps(action[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        for _, action in actions
        for key in ("input_schema", "output_schema")
        if isinstance(action.get(key), dict)
    ]
    references: dict[str, str] = {}
    definitions: dict[str, dict[str, Any]] = {}
    for encoded, count in Counter(schema for _, _, schema in schemas).items():
        name = f"s{len(definitions)}"
        name_size = len(json.dumps(name))
        # Include the new _ref suffix and definition entry when deciding whether
        # pooling saves space; small or unique schemas keep their original form.
        if count * (len(encoded) - name_size - 4) > len(encoded) + name_size + 2:
            references[encoded] = name
            definitions[name] = json.loads(encoded)
    for action, key, encoded in schemas:
        if encoded in references:
            del action[key]
            action[f"{key}_ref"] = references[encoded]
    inherited = False
    for tool, action in actions:
        if "description" in action and action["description"] == tool.get("description"):
            del action["description"]
            inherited = True
    if definitions or inherited:
        prompt["tool_schemas"] = definitions
        prompt["tool_registry_format"] = (
            "action 未写 description 时继承 tool.description；input_schema_ref/output_schema_ref "
            "指向 tool_schemas 中的完整独立 Schema，其内部 $ref 仍相对于该 Schema。"
        )


def planner_max_tokens() -> int:
    raw = (os.environ.get(_ENV_MAX_TOKENS) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_TOKENS
    return max(256, min(16000, value))


def _meter_planner_completion(payload: dict[str, Any] | None, *, model: str) -> None:
    """统一 Agent Runtime 计量接缝：planner LLM 用量入账（best-effort，不受 hooks 开关限制）。"""
    if not isinstance(payload, dict):
        return
    try:
        from app.application.agent_runtime.pipeline import completion_usage, meter_llm_call

        usage = completion_usage(payload)
        if not usage.get("total_tokens"):
            return
        meta = payload.get("_xcagi_billing")
        provider = ""
        provider_id = ""
        if isinstance(meta, dict):
            provider = str(meta.get("provider") or "")
            provider_id = str(meta.get("provider_id") or "")
        meter_llm_call(
            source="agent_planner",
            model=str(payload.get("model") or model),
            usage=usage,
            provider=provider,
            provider_id=provider_id,
            metadata={"channel": "planner_llm_gateway"},
        )
    except RECOVERABLE_ERRORS:
        logger.debug("planner LLM metering skipped", exc_info=True)


async def _prepare_model_messages(
    provider, context, messages, max_tokens, extra, *, model_limits=None
):
    """One final budget boundary for sync, stream, repairs and native tools."""
    from app.application.agent_orchestrator.context_window_manager import (
        ContextWindowExceeded,
        estimate_messages_tokens,
        get_context_window_manager,
        summary_fingerprint,
    )
    from app.application.ai_chat.dialogue_memory import (
        _turns_fingerprint,
        conversation_summary,
        save_conversation_summary,
    )
    from app.infrastructure.llm.model_context_windows import resolve_model_limits

    history, state = [], None
    outbound = list(messages)
    # The planner's typed JSON input keeps history separate until this boundary.
    # Expand it to native messages so history can be compacted without clipping
    # the current user JSON, tool schemas, or a tool call/result group.
    if outbound and outbound[-1].get("role") == "user":
        try:
            prompt = json.loads(outbound[-1]["content"])
        except (TypeError, ValueError):
            prompt = None
        if isinstance(prompt, dict):
            _compact_tool_registry(prompt)
        if isinstance(prompt, dict) and isinstance(prompt.get("conversation_history"), list):
            history = prompt.pop("conversation_history")
            prompt.pop("recent_messages", None)
            prompt_context = prompt.get("context")
            if isinstance(prompt_context, dict):
                for key in ("recent_messages", "chat_owned_history", "chat_history_summary"):
                    prompt_context.pop(key, None)
            outbound = [*outbound[:-1], *history, outbound[-1]]
            if context is not None:
                saved = conversation_summary(context)
                state = context.get("_planner_compression_context")
                if state is None or state.conversation_history != history:
                    state = SimpleNamespace(
                        conversation_history=history,
                        summary=None,
                        summary_covered_until=-1,
                        summary_fingerprint="",
                    )
                    if saved and saved.get("source") != "sql":
                        count = int(saved.get("count") or 0)
                        if 0 < count <= len(history) and saved.get(
                            "fingerprint"
                        ) == _turns_fingerprint(history[:count]):
                            state.summary, state.summary_covered_until = saved["text"], count - 1
                            state.summary_fingerprint = summary_fingerprint(history[:count])
                    context["_planner_compression_context"] = state
        if isinstance(prompt, dict):
            outbound[-1] = {
                **outbound[-1],
                "content": json.dumps(prompt, ensure_ascii=False, separators=(",", ":")),
            }
    schemas = {
        key: extra[key]
        for key in ("tools", "functions", "response_format", "tool_choice", "function_call")
        if key in extra
    }
    schema_tokens = (
        estimate_messages_tokens(
            [{"role": "system", "content": json.dumps(schemas, ensure_ascii=False)}]
        )
        if schemas
        else 0
    )
    if context is not None:
        if state is None:
            state = SimpleNamespace(
                conversation_history=[],
                summary=None,
                summary_covered_until=-1,
                summary_fingerprint="",
            )
        # Only local ownership/revision fields reach the compaction guard; the
        # snapshot is never part of model messages or the persisted summary.
        state.metadata = {
            "request_context": {
                key: context[key]
                for key in (
                    "local_user_id",
                    "actor_id",
                    "tenant_id",
                    "mod_id",
                    "conversation_id",
                    "session_id",
                    "_conversation_revision",
                    "_chat_history_source",
                    "_chat_history_revision",
                )
                if key in context
            }
        }
    limits = model_limits or await resolve_model_limits(
        provider, extra.get("model"), extra.get("provider"), messages=messages
    )
    diagnostics = {
        "model": limits.model,
        "capability_source": limits.source,
        "context_window": limits.context_window,
        "max_input_tokens": limits.max_input_tokens,
        "max_output_tokens": limits.max_output_tokens,
        "requested_output_tokens": max_tokens,
        "external_schema_tokens": schema_tokens,
        "message_tokens": estimate_messages_tokens(outbound),
    }
    if context is not None:
        context["_context_budget"] = diagnostics
    try:
        result = await get_context_window_manager().compress(
            outbound,
            provider=provider,
            context=state,
            user_id=str((context or {}).get("local_user_id") or ""),
            model=limits.model,
            model_limits=limits,
            output_tokens=max_tokens,
            external_tokens=schema_tokens,
        )
    except ContextWindowExceeded as exc:
        diagnostics.update(exc.diagnostics)
        diagnostics["reason"] = exc.reason
        logger.warning("planner context budget rejected: %s", diagnostics)
        raise
    diagnostics["post_message_tokens"] = result.post_estimated_tokens
    diagnostics["compression_strategy"] = result.strategy
    limits.assert_current()
    if context is not None and result.summary_llm_call is not None:
        save_conversation_summary(
            context, history, result.summary_covered_count, result.summary_text
        )
    if context is not None:
        conversation_summary(context)  # Revalidate after routing/compression awaits, before IO.
    return result.messages


def stream_planner_completion(
    *,
    ai_service: Any,
    context: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    temperature: float = 0.1,
    max_tokens: int | None = None,
    **extra: Any,
) -> Any:
    """Stream through the same context/output/schema budget as normal completion."""
    from app.infrastructure.llm.model_admission import model_rate_limit_scope
    from app.infrastructure.llm.providers.registry import get_active_provider

    with planner_model_budget(context), _provider_errors():
        provider = get_active_provider(conversation_service=ai_service)
        if provider is None:
            raise MarketModelError({"status": 503}, code="model_not_configured")
    stream = getattr(provider, "stream_chat_completion", None)
    if stream is None:
        return None

    async def generate():
        from app.infrastructure.llm.model_context_windows import resolve_model_limits

        with _provider_errors(), model_rate_limit_scope(context):
            async with _model_request_deadline(context):
                limits = await resolve_model_limits(
                    provider, extra.get("model"), extra.get("provider"), messages=messages
                )
                output_limit = (
                    max_tokens
                    if max_tokens is not None
                    else limits.default_output_tokens(planner_max_tokens())
                )
                outbound = await _prepare_model_messages(
                    provider, context, messages, output_limit, extra, model_limits=limits
                )
                limits.assert_current()
                emitted = False
                async with aclosing(
                    stream(
                        messages=outbound,
                        temperature=temperature,
                        max_tokens=output_limit,
                        **{**extra, **limits.request_options},
                    )
                ) as chunks:
                    async for chunk in chunks:
                        limits.assert_current()
                        emitted = emitted or bool(chunk)
                        yield chunk
                if not emitted:
                    raise MarketModelError({"status": 502}, code="model_response_invalid")

    return generate()


def request_planner_completion(
    *,
    ai_service: Any,
    context: dict[str, Any] | None,
    messages: list[dict[str, str]],
    http_client_factory: Any = None,  # call-site compat; unused
    temperature: float = 0.1,
    max_tokens: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Use the same request-scoped provider and model as nested Agent tools."""
    from app.application.employee_runtime.agent_runner import _run_async
    from app.infrastructure.llm.providers.registry import get_active_provider

    with planner_model_budget(context), _provider_errors():
        provider = get_active_provider(conversation_service=ai_service)
        if provider is None:
            raise MarketModelError({"status": 503}, code="model_not_configured")
        from app.infrastructure.llm.model_admission import model_rate_limit_scope
        from app.infrastructure.llm.model_context_windows import resolve_model_limits

        with model_rate_limit_scope(context):

            async def complete() -> dict[str, Any]:
                async with _model_request_deadline(context):
                    limits = await resolve_model_limits(
                        provider, extra.get("model"), extra.get("provider"), messages=messages
                    )
                    output_limit = (
                        max_tokens
                        if max_tokens is not None
                        else limits.default_output_tokens(planner_max_tokens())
                    )
                    outbound = await _prepare_model_messages(
                        provider, context, messages, output_limit, extra, model_limits=limits
                    )
                    limits.assert_current()
                    result = await provider.chat_completion(
                        messages=outbound,
                        temperature=temperature,
                        max_tokens=output_limit,
                        **{**extra, **limits.request_options},
                    )
                    limits.assert_current()
                    return _validate_completion(result)

            result: dict[str, Any] = _run_async(complete())
    _meter_planner_completion(result, model=str(result.get("model") or ""))
    return result
