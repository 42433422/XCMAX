from __future__ import annotations

import json
import logging
import os
from collections import Counter
from types import SimpleNamespace
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_ENV_MAX_TOKENS = "XCAGI_PLANNER_MAX_TOKENS"
# 推理模型（如 MiMo / MiniMax M3）会先消耗 reasoning token，1200 的旧默认
# 会让正文为空（finish_reason=length）。默认放宽到 4096，仍可用环境变量收紧。
_DEFAULT_MAX_TOKENS = 4096


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


async def _prepare_model_messages(provider, context, messages, max_tokens, extra):
    """One final budget boundary for sync, stream, repairs and native tools."""
    from app.application.agent_orchestrator.context_window_manager import (
        estimate_messages_tokens,
        get_context_window_manager,
        summary_fingerprint,
    )
    from app.application.ai_chat.dialogue_memory import (
        _turns_fingerprint,
        conversation_summary,
        save_conversation_summary,
    )
    from app.infrastructure.llm.model_context_windows import model_for_budget

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
    schemas = {key: extra[key] for key in ("tools", "functions", "response_format") if key in extra}
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
    result = await get_context_window_manager().compress(
        outbound,
        provider=provider,
        context=state,
        user_id=str((context or {}).get("local_user_id") or ""),
        reserved_tokens=max_tokens + schema_tokens,
        model=await model_for_budget(provider, extra.get("model"), extra.get("provider")),
    )
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

    provider = get_active_provider(conversation_service=ai_service)
    stream = getattr(provider, "stream_chat_completion", None) if provider is not None else None
    if stream is None:
        return None
    output_limit = max_tokens or planner_max_tokens()

    async def generate():
        with model_rate_limit_scope(context):
            outbound = await _prepare_model_messages(
                provider, context, messages, output_limit, extra
            )
            async for chunk in stream(
                messages=outbound, temperature=temperature, max_tokens=output_limit, **extra
            ):
                yield chunk

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
) -> dict[str, Any] | None:
    """Use the same request-scoped provider and model as nested Agent tools."""
    from app.application.employee_runtime.agent_runner import _run_async
    from app.infrastructure.llm.providers.registry import get_active_provider

    try:
        provider = get_active_provider(conversation_service=ai_service)
        if provider is None:
            return None
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        with model_rate_limit_scope(context):
            output_limit = max_tokens or planner_max_tokens()
            outbound = _run_async(
                _prepare_model_messages(provider, context, messages, output_limit, extra)
            )
            result = _run_async(
                provider.chat_completion(
                    messages=outbound,
                    temperature=temperature,
                    max_tokens=output_limit,
                    **extra,
                )
            )
    except RECOVERABLE_ERRORS as exc:
        from app.application.agent_orchestrator.context_window_manager import ContextWindowExceeded
        from app.domain.shared_services.conversation_service import ConversationRevisionError

        if isinstance(exc, (ContextWindowExceeded, ConversationRevisionError)):
            raise
        from .retry_policy import retry_manages_transport_error
        from .tool_calling import unsupported_tool_parameter

        if retry_manages_transport_error(exc) or (
            extra and isinstance(exc, TypeError) and unsupported_tool_parameter(exc)
        ):
            raise
        from app.infrastructure.llm.model_admission import (
            ModelCircuitOpenError,
            ModelConcurrencyLimitError,
            ModelRateLimitError,
        )
        from app.infrastructure.modstore_transport import MarketModelError
        from app.utils.resilience.rate_limiter import RateLimitBackendError

        if isinstance(
            exc,
            (
                MarketModelError,
                ModelCircuitOpenError,
                ModelConcurrencyLimitError,
                ModelRateLimitError,
                RateLimitBackendError,
            ),
        ):
            raise
        logger.warning("planner model request failed", exc_info=True)
        return None
    if not isinstance(result, dict):
        return None
    _meter_planner_completion(result, model=str(result.get("model") or ""))
    return result
