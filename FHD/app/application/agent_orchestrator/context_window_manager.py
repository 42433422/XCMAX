"""上下文窗口管理器（ContextWindowManager）——按 token 预算裁剪 + 自动摘要旧轮次。

接入点：``app.services.conversation.api.call_llm_api`` 在调用 ``provider.chat_completion``
之前调用 ``ContextWindowManager.compress``，对 ``messages`` 做"按预算裁剪 + 必要时摘要"。

设计目标
--------

1. **统一裁剪入口**：消除 ``api.py`` 中 ``[-10:]`` 硬编码切片与 ``manager.py`` 中 ``[-20:]``
   滚动历史的三层不一致（内存 20 / 喂 LLM 10 / persona 看全量 20）。
2. **预算预检**：调用 LLM 前估算 prompt token，超预算时主动压缩，避免 422/413。
3. **可观测性零侵入**：压缩元数据通过 ``_xcagi_trace`` dict 注入，``chat_trace.py``
   的 ``_iter_llm_trace_payloads`` 会自动衔接，不需要改 chat_trace。
4. **摘要独立记账**：摘要 LLM 调用作为独立 ``LLMCall`` 记录，
   ``metadata.source="context_window_manager.summarize"``，与主调用分离。

策略
----

- ``noop``：messages 数 ≤ ``summarize_threshold`` 且估算 token ≤ ``token_budget`` → 原样返回。
- ``summarize``：超阈值 → 调 LLM 摘要前 N 条，拼接 ``[system..., summary, recent_keep 条]``。
- ``truncate``：摘要 LLM 失败时退化 → 保留 ``[system..., recent_keep 条]``。

约束
----

- system 消息（``role=="system"``）永不裁剪。
- ``recent_keep`` 条最近消息永不裁剪（保近期上下文完整）。
- 摘要 prompt 限制输出 ≤ 200 字，控制成本。
- 所有 LLM 异常捕获 ``RECOVERABLE_ERRORS``，失败退化为 ``truncate``，不阻断主对话。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.application.agent_orchestrator.run_models import LLMCall
from app.infrastructure.llm.token_estimator import estimate_messages_tokens
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
CONTEXT_WINDOW_MANAGER_VERSION = "1.0.0"

_SUMMARY_SYSTEM_PROMPT = "你是对话历史压缩器。请用 200 字以内总结以下对话历史的关键信息，保留用户意图、关键实体和未完成的事项，不要添加新的信息。"
_SUMMARY_CONTENT_PREFIX = "对话历史摘要："


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class ContextCompressionResult:
    """上下文压缩结果。

    Attributes:
        messages: 压缩后的 messages 列表（可能等于输入）。
        strategy: 实际生效的策略：``"noop"`` / ``"summarize"`` / ``"truncate"``。
        pre_message_count: 压缩前 messages 数。
        post_message_count: 压缩后 messages 数。
        pre_estimated_tokens: 压缩前估算 token 数。
        post_estimated_tokens: 压缩后估算 token 数。
        tokens_saved: 节省的 token 数（``pre - post``，≥ 0）。
        summary_llm_call: 若触发摘要，记录独立 ``LLMCall``；未触发或失败时为 ``None``。
        compression_latency_ms: 压缩耗时（毫秒）。
    """

    messages: list[dict[str, str]] = field(default_factory=list)
    strategy: str = "noop"
    pre_message_count: int = 0
    post_message_count: int = 0
    pre_estimated_tokens: int = 0
    post_estimated_tokens: int = 0
    tokens_saved: int = 0
    summary_llm_call: LLMCall | None = None
    compression_latency_ms: float = 0.0


class ContextWindowManager:
    """上下文窗口管理器：按 token 预算裁剪 messages，必要时调 LLM 摘要旧轮次。

    Args:
        token_budget: 单次 LLM 调用 prompt token 预算（超则触发压缩）。
        recent_keep: 永不裁剪的最近消息数（保近期上下文完整）。
        summarize_threshold: 非系统消息数超过此值时触发摘要。
        summarize_max_tokens: 摘要 LLM 调用的 ``max_tokens`` 上限。
        enabled: 总开关；``False`` 时 ``compress`` 直接返回 noop。
    """

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
    ) -> ContextCompressionResult:
        """压缩 ``messages``，返回压缩后的 messages + 元数据。

        Args:
            messages: OpenAI 格式消息列表。``None`` 或空列表返回 noop 空结果。
            user_id: 当前用户 ID（用于摘要调用记账）。
            trace_id: 当前 trace_id（写入 ``LLMCall.metadata``）。
            provider: 可选的已解析 LLM provider；``None`` 时由 manager 自行调用
                ``get_active_provider`` 解析。传入已解析的 provider 可避免重复解析。

        Returns:
            :class:`ContextCompressionResult`。
        """
        t0 = time.perf_counter()

        # 边界：None / 空
        if not messages:
            return ContextCompressionResult(
                messages=[],
                strategy="noop",
                compression_latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        pre_count = len(messages)
        pre_tokens = estimate_messages_tokens(messages)

        # 总开关关闭 → noop 原样返回
        if not self._enabled:
            return ContextCompressionResult(
                messages=list(messages),
                strategy="noop",
                pre_message_count=pre_count,
                post_message_count=pre_count,
                pre_estimated_tokens=pre_tokens,
                post_estimated_tokens=pre_tokens,
                tokens_saved=0,
                compression_latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 分离 system 与非 system 消息（system 永不裁剪）
        system_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        non_system = [
            m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")
        ]

        # noop 判定：消息数 ≤ 阈值 且 token ≤ 预算
        if len(non_system) <= self._summarize_threshold and pre_tokens <= self._token_budget:
            return ContextCompressionResult(
                messages=list(messages),
                strategy="noop",
                pre_message_count=pre_count,
                post_message_count=pre_count,
                pre_estimated_tokens=pre_tokens,
                post_estimated_tokens=pre_tokens,
                tokens_saved=0,
                compression_latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 非系统消息数 ≤ recent_keep → 无可摘要部分，noop
        if len(non_system) <= self._recent_keep:
            return ContextCompressionResult(
                messages=list(messages),
                strategy="noop",
                pre_message_count=pre_count,
                post_message_count=pre_count,
                pre_estimated_tokens=pre_tokens,
                post_estimated_tokens=pre_tokens,
                tokens_saved=0,
                compression_latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # 触发压缩：尝试 summarize，失败退化为 truncate
        recent = non_system[-self._recent_keep :] if self._recent_keep > 0 else []
        to_summarize = non_system[: len(non_system) - self._recent_keep]

        summary_text, summary_call = await self._summarize_messages(
            to_summarize=to_summarize,
            user_id=user_id,
            trace_id=trace_id,
            provider=provider,
        )

        if summary_text:
            summary_msg = {
                "role": "system",
                "content": f"{_SUMMARY_CONTENT_PREFIX}{summary_text}",
            }
            compressed = [*system_msgs, summary_msg, *recent]
            strategy = "summarize"
        else:
            # 摘要失败 → truncate
            compressed = [*system_msgs, *recent]
            strategy = "truncate"

        post_tokens = estimate_messages_tokens(compressed)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return ContextCompressionResult(
            messages=compressed,
            strategy=strategy,
            pre_message_count=pre_count,
            post_message_count=len(compressed),
            pre_estimated_tokens=pre_tokens,
            post_estimated_tokens=post_tokens,
            tokens_saved=max(0, pre_tokens - post_tokens),
            summary_llm_call=summary_call,
            compression_latency_ms=latency_ms,
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
                max_tokens=self._summarize_max_tokens,
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
    """获取全局 :class:`ContextWindowManager` 单例。

    首次调用时从环境变量读取配置：

    - ``FHD_CONTEXT_WINDOW_TOKEN_BUDGET``：token 预算（默认 8000）
    - ``FHD_CONTEXT_WINDOW_RECENT_KEEP``：保留最近消息数（默认 6）
    - ``FHD_CONTEXT_WINDOW_SUMMARIZE_THRESHOLD``：触发摘要阈值（默认 12）
    - ``FHD_CONTEXT_WINDOW_MANAGER_ENABLED``：总开关（默认 1）
    """
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
