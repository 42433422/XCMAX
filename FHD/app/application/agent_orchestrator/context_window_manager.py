"""Token-budgeted conversation history with per-context incremental summaries.

System instructions and the newest user/tool turn are indivisible. If they
cannot fit, reject before provider I/O; recent_keep is a preference, not an
exemption from the budget. Message count alone never triggers a paid summary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.application.agent_orchestrator.run_models import LLMCall
from app.infrastructure.llm.token_estimator import (
    estimate_messages_tokens as _estimate_messages_tokens,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

__all__ = [
    "CONTEXT_WINDOW_MANAGER_VERSION",
    "ContextCompressionResult",
    "ContextWindowManager",
    "get_context_window_manager",
    "reset_context_window_manager",
]

# 默认参数（可由环境变量覆盖）
_DEFAULT_TOKEN_BUDGET = 8000
_DEFAULT_RECENT_KEEP = 6
_DEFAULT_SUMMARIZE_THRESHOLD = 12
_DEFAULT_SUMMARIZE_MAX_TOKENS = 300  # 摘要输出上限（约 200 汉字）
CONTEXT_WINDOW_MANAGER_VERSION = "1.1.0"

_SUMMARY_SYSTEM_PROMPT = "你是对话历史压缩器。请用 200 字以内总结以下对话历史的关键信息，保留用户意图、关键实体和未完成的事项，不要添加新的信息。"
_SUMMARY_CONTENT_PREFIX = "对话历史摘要："


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def estimate_messages_tokens(messages) -> int:
    """Include message framing and non-content fields in the conservative estimate."""
    if not messages:
        return 0
    encoded = json.dumps(messages, ensure_ascii=False, default=str).encode()
    return max(_estimate_messages_tokens(messages), (len(encoded) + 3) // 4) + 4 * len(messages) + 3


@dataclass
class ContextCompressionResult:
    messages: list[dict[str, str]] = field(default_factory=list)
    strategy: str = "noop"
    pre_message_count: int = 0
    post_message_count: int = 0
    pre_estimated_tokens: int = 0
    post_estimated_tokens: int = 0
    tokens_saved: int = 0
    summary_llm_call: LLMCall | None = None
    compression_latency_ms: float = 0.0


class ContextWindowExceeded(ValueError):
    """The system instructions/newest turn cannot fit without changing intent."""


def summary_fingerprint(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(
        json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _turns(messages):
    groups = []
    for message in messages:
        if not groups or message.get("role") == "user":
            groups.append([])
        groups[-1].append(message)
    return groups


class ContextWindowManager:
    """Bound input plus reserved output/tool tokens; cache only on its owning context."""

    def __init__(
        self,
        *,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        recent_keep: int = _DEFAULT_RECENT_KEEP,
        summarize_threshold: int = _DEFAULT_SUMMARIZE_THRESHOLD,
        summarize_max_tokens: int = _DEFAULT_SUMMARIZE_MAX_TOKENS,
        enabled: bool | None = None,
    ) -> None:
        self._token_budget = max(1, int(token_budget))
        self._recent_keep = max(0, int(recent_keep))
        self._summarize_threshold = max(1, int(summarize_threshold))
        self._summarize_max_tokens = max(1, int(summarize_max_tokens))
        if enabled is None:
            enabled = os.environ.get("FHD_CONTEXT_WINDOW_MANAGER_ENABLED", "1") != "0"
        self._enabled = bool(enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def token_budget(self) -> int:
        return self._token_budget

    async def compress(
        self,
        messages: list[dict[str, str]] | None,
        *,
        user_id: str = "",
        trace_id: str | None = None,
        provider: Any | None = None,
        context: Any | None = None,
        reserved_tokens: int = 0,
    ) -> ContextCompressionResult:
        if context is not None:
            lock = getattr(context, "_compression_lock", None)
            if lock is None:
                lock = asyncio.Lock()
                context._compression_lock = lock
            async with lock:
                return await self._compress(
                    messages or [], user_id, trace_id, provider, context, reserved_tokens
                )
        return await self._compress(
            messages or [], user_id, trace_id, provider, None, reserved_tokens
        )

    async def _compress(
        self, messages, user_id, trace_id, provider, context, reserved_tokens
    ) -> ContextCompressionResult:
        started = time.perf_counter()
        pre_tokens = estimate_messages_tokens(messages)
        budget = self._token_budget - max(0, int(reserved_tokens))
        compressed, strategy, summary_call = list(messages), "noop", None
        if self._enabled and messages:
            system = [m for m in messages if m.get("role") == "system"]
            history = [m for m in messages if m.get("role") != "system"]
            groups = _turns(history)
            required = [*system, *(groups[-1] if groups else [])]
            if estimate_messages_tokens(required) > budget:
                raise ContextWindowExceeded(
                    "系统指令或最新一轮输入超过上下文预算，请缩短输入或分批提交。"
                )
            covered, cached = 0, []
            cache_valid = (
                context is not None
                and history[: len(context.conversation_history)] == context.conversation_history
            )
            if cache_valid and context.summary:
                covered = min(len(context.conversation_history), context.summary_covered_until + 1)
                if context.summary_fingerprint == summary_fingerprint(history[:covered]):
                    cached = [
                        {"role": "system", "content": _SUMMARY_CONTENT_PREFIX + context.summary}
                    ]
                else:
                    covered = 0
            tail = history[covered:]
            compressed = [*system, *cached, *tail]
            strategy = "summarize" if cached else "noop"
            if estimate_messages_tokens(compressed) > budget:
                groups = _turns(tail)
                recent: list[dict[str, str]] = []
                # Keep complete user/tool turns, aiming for recent_keep messages.
                while groups and len(recent) < max(1, self._recent_keep):
                    recent = groups.pop() + recent
                while (
                    len(_turns(recent)) > 1
                    and estimate_messages_tokens([*system, *recent]) > budget
                ):
                    recent = [m for group in _turns(recent)[1:] for m in group]
                old = tail[: len(tail) - len(recent)]
                summary_text, summary_call = (
                    await self._summarize_messages(
                        to_summarize=[*cached, *old],
                        user_id=user_id,
                        trace_id=trace_id,
                        provider=provider,
                    )
                    if old
                    else ("", None)
                )
                summary = (
                    [{"role": "system", "content": _SUMMARY_CONTENT_PREFIX + summary_text}]
                    if summary_text
                    else []
                )
                compressed, strategy = (
                    [*system, *summary, *recent],
                    "summarize" if summary else "truncate",
                )
                # The provider may ignore max_tokens. Never forward an oversized
                # summary; discard it before trimming complete older turns.
                if estimate_messages_tokens(compressed) > budget:
                    summary = []
                    compressed, strategy = [*system, *recent], "truncate"
                while estimate_messages_tokens(compressed) > budget and len(_turns(recent)) > 1:
                    recent = [m for group in _turns(recent)[1:] for m in group]
                    compressed = [*system, *recent]
                new_covered = covered + len(old)
                if (
                    summary
                    and cache_valid
                    and history[:new_covered] == context.conversation_history[:new_covered]
                ):
                    context.summary = summary_text
                    context.summary_covered_until = new_covered - 1
                    context.summary_fingerprint = summary_fingerprint(history[:new_covered])
            if estimate_messages_tokens(compressed) > budget:
                raise ContextWindowExceeded("上下文无法在预算内完整保留最新输入，请缩短输入。")
        post_tokens = estimate_messages_tokens(compressed)
        return ContextCompressionResult(
            messages=compressed,
            strategy=strategy,
            pre_message_count=len(messages),
            post_message_count=len(compressed),
            pre_estimated_tokens=pre_tokens,
            post_estimated_tokens=post_tokens,
            tokens_saved=max(0, pre_tokens - post_tokens),
            summary_llm_call=summary_call,
            compression_latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def _summarize_messages(
        self,
        *,
        to_summarize: list[dict[str, str]],
        user_id: str,
        trace_id: str | None,
        provider: Any | None,
    ) -> tuple[str, LLMCall | None]:
        """调 LLM 摘要 ``to_summarize`` 消息列表。

        Returns:
            ``(summary_text, llm_call)``。失败时 ``summary_text=""``，
            ``llm_call`` 仍记录失败信息（``status="failed"``）。
        """
        if not to_summarize:
            return "", None

        # 构造摘要请求 messages：[system_prompt, user(待摘要历史)]
        history_text = self._format_history_for_summary(to_summarize)
        summary_messages = [
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": f"请总结以下对话历史：\n\n{history_text}"},
        ]

        summary_room = self._token_budget - estimate_messages_tokens(summary_messages)
        if summary_room <= 0:
            return "", None
        t0 = time.perf_counter()
        call = LLMCall(
            metadata={
                "source": "context_window_manager.summarize",
                "trace_id": trace_id or "",
                "user_id": user_id,
                "input_message_count": len(to_summarize),
            },
        )

        try:
            resolved_provider = provider
            if resolved_provider is None:
                from app.infrastructure.llm.providers.registry import get_active_provider

                resolved_provider = get_active_provider()

            if resolved_provider is None:
                call.status = "failed"
                call.error = "no_active_provider"
                logger.warning(
                    "ContextWindowManager.summarize: no active provider, fall back to truncate"
                )
                return "", call

            provider_id = str(getattr(resolved_provider, "provider_id", "") or "")
            adapter = getattr(resolved_provider, "_adapter", None)
            provider_name = str(
                getattr(adapter, "provider_name", "")
                or getattr(resolved_provider, "provider_name", "")
                or provider_id
            )

            result = await resolved_provider.chat_completion(
                messages=summary_messages,
                temperature=0.3,  # 摘要用低温度
                max_tokens=min(self._summarize_max_tokens, summary_room),
            )

            latency_ms = (time.perf_counter() - t0) * 1000.0
            call.provider_id = provider_id
            call.provider = provider_name
            call.latency_ms = latency_ms

            if not result or not isinstance(result, dict):
                call.status = "failed"
                call.error = "empty_result"
                call.model = str(getattr(adapter, "model_name", "") or "")
                self._record_summary_usage(call)
                logger.warning(
                    "ContextWindowManager.summarize: empty result, fall back to truncate"
                )
                return "", call

            # 提取摘要文本
            choices = result.get("choices") or []
            if not choices:
                call.status = "failed"
                call.error = "no_choices"
                self._record_summary_usage(call)
                return "", call

            msg = choices[0].get("message") or {}
            summary_text = str(msg.get("content") or "").strip()
            if not summary_text:
                call.status = "failed"
                call.error = "empty_content"
                self._record_summary_usage(call)
                return "", call

            # 成功：填充 token 用量与计费
            raw_usage = result.get("usage")
            usage = raw_usage if isinstance(raw_usage, dict) else {}
            prompt_tokens = _coerce_int(usage.get("prompt_tokens"))
            completion_tokens = _coerce_int(usage.get("completion_tokens"))
            total_tokens = _coerce_int(usage.get("total_tokens"))
            model = str(
                result.get("model")
                or getattr(adapter, "model_name", "")
                or getattr(resolved_provider, "model_name", "")
                or ""
            )

            call.model = model
            call.prompt_tokens = prompt_tokens
            call.completion_tokens = completion_tokens
            call.total_tokens = total_tokens
            call.status = "completed"

            self._record_summary_usage(call)

            logger.info(
                "ContextWindowManager.summarize: ok provider=%s model=%s tokens=%d latency=%.1fms",
                provider_id,
                model,
                total_tokens,
                latency_ms,
            )
            return summary_text, call

        except RECOVERABLE_ERRORS as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            call.status = "failed"
            call.error = f"{type(exc).__name__}: {exc}"
            call.latency_ms = latency_ms
            self._record_summary_usage(call)
            logger.warning(
                "ContextWindowManager.summarize: %s, fall back to truncate",
                exc,
                exc_info=True,
            )
            return "", call

    @staticmethod
    def _format_history_for_summary(messages: list[dict[str, str]]) -> str:
        """把 messages 列表格式化为摘要 prompt 的输入文本。"""
        lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "unknown")
            content = str(msg.get("content") or "")
            if not content:
                continue
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _record_summary_usage(call: LLMCall) -> None:
        """把摘要调用记账到 ``model_usage_ledger``（失败也记）。"""
        try:
            from app.infrastructure.billing.model_usage import (
                estimate_llm_cost_units,
                record_model_usage,
            )

            cost_units = estimate_llm_cost_units(
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                total_tokens=call.total_tokens,
            )
            call.cost_units = cost_units
            call.billing_status = "metered" if cost_units else "unmetered"
            call.billing_source = "estimated_token_units"

            record_model_usage(
                provider_id=call.provider_id,
                provider=call.provider,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                total_tokens=call.total_tokens,
                cost_units=cost_units,
                billing_status=call.billing_status,
                billing_source=call.billing_source,
                source="context_window_manager.summarize",
                user_id=call.metadata.get("user_id", ""),
                metadata=dict(call.metadata),
            )
        except RECOVERABLE_ERRORS:
            logger.debug("ContextWindowManager: record_model_usage failed", exc_info=True)


# ========== 单例 ==========

_cwm_singleton: ContextWindowManager | None = None


def get_context_window_manager() -> ContextWindowManager:
    """Return the environment-configured shared stateless manager."""
    global _cwm_singleton
    if _cwm_singleton is None:
        _cwm_singleton = ContextWindowManager(
            token_budget=_coerce_int(os.environ.get("FHD_CONTEXT_WINDOW_TOKEN_BUDGET"))
            or _DEFAULT_TOKEN_BUDGET,
            recent_keep=_coerce_int(os.environ.get("FHD_CONTEXT_WINDOW_RECENT_KEEP"))
            or _DEFAULT_RECENT_KEEP,
            summarize_threshold=_coerce_int(
                os.environ.get("FHD_CONTEXT_WINDOW_SUMMARIZE_THRESHOLD")
            )
            or _DEFAULT_SUMMARIZE_THRESHOLD,
        )
    return _cwm_singleton


def reset_context_window_manager() -> None:
    """重置单例（测试用）。"""
    global _cwm_singleton
    _cwm_singleton = None
