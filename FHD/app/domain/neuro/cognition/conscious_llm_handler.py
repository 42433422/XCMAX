"""Conscious LLM 处理器——ConsciousProcessor 的默认 LLM 处理器。

整合 ``LLMPort`` + ``WorkingMemory`` + ``AttentionSelector``，
为 ``ConsciousProcessor`` 提供 LLM 驱动的处理能力。

注册方式：
    processor = get_conscious_processor()
    processor.register_handler("intent.process", ConsciousLLMHandler())

处理流程：
1. 从事件 payload 提取 query / session_id / user_id
2. ``WorkingMemory.recall(query)`` 召回工作记忆
3. ``AttentionSelector.select(query, snapshot)`` 选取相关上下文
4. 构建 system prompt + 上下文 + query → ``LLMPort.chat()``
5. 返回 ``ProcessingResult``（成功/失败 + LLM 回复）

SLA 感知：
- Conscious 目标 <200ms，但 LLM 调用通常 1-5s。
- SLA 控制器会记录违规但不杀请求（System 2 慎思允许慢）。
- LLM 不可用时返回失败，由上层降级到 Reflex 或返回默认回复。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.domain.neuro.cognition.attention_selector import AttentionSelector, get_attention_selector
from app.domain.neuro.cognition.llm_port import LLMPort, get_llm_port
from app.domain.neuro.cognition.working_memory import WorkingMemory, get_working_memory
from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """你是一个智能助手，正在通过 XCMAS Neuro-DDD 的显意识处理器（ConsciousProcessor）处理用户请求。
请根据上下文和用户输入，给出准确、简洁、有帮助的回复。"""

_DEFAULT_MAX_TOKENS = 1000
_DEFAULT_TEMPERATURE = 0.7


class ConsciousLLMHandler:
    """Conscious 处理器的默认 LLM 处理器。

    可注册到 ``ConsciousProcessor.register_handler(event_type, handler)``。

    Args:
        llm_port: LLM 端口（默认使用全局单例）。
        working_memory: 工作记忆（默认使用全局单例，按 session/user 初始化）。
        attention_selector: 注意力选择器（默认使用全局单例）。
        system_prompt: 系统提示词（默认使用内置模板）。
    """

    def __init__(
        self,
        llm_port: LLMPort | None = None,
        working_memory: WorkingMemory | None = None,
        attention_selector: AttentionSelector | None = None,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self._llm_port = llm_port or get_llm_port()
        self._working_memory = working_memory
        self._attention_selector = attention_selector or get_attention_selector()
        self._system_prompt = system_prompt

    async def handle(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 ``intent.process`` 事件。

        事件 payload 期望字段：
        - ``text`` / ``query``: 用户查询文本（必需）
        - ``session_id``: 会话 ID（可选，用于工作记忆）
        - ``user_id``: 用户 ID（可选，用于长期记忆）
        - ``context``: 附加上下文字典（可选）
        - ``system_prompt``: 覆盖系统提示词（可选）

        Returns:
            ``{"success": bool, "response": str, "error": str | None, "tokens_used": int}``
        """
        start = time.perf_counter()
        payload = event.payload or {}
        query = str(payload.get("text") or payload.get("query") or "").strip()
        session_id = str(payload.get("session_id") or "")
        user_id = str(payload.get("user_id") or "")
        context_data = payload.get("context") or {}
        system_prompt = str(payload.get("system_prompt") or self._system_prompt)

        if not query:
            return {
                "success": False,
                "response": "",
                "error": "empty_query",
                "tokens_used": 0,
            }

        # 1. 召回工作记忆
        memory = self._working_memory or get_working_memory(
            session_id=session_id,
            user_id=user_id,
        )
        snapshot = memory.recall(query)

        # 2. 注意力选择
        attention = self._attention_selector.select(query, snapshot)

        # 3. 构建 LLM 消息
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        # 注入工作记忆上下文
        if not attention.is_empty:
            context_block = self._format_context(attention)
            if context_block:
                messages.append({"role": "system", "content": context_block})

        # 注入附加上下文
        if context_data:
            extra_block = self._format_extra_context(context_data)
            if extra_block:
                messages.append({"role": "system", "content": extra_block})

        # 用户查询
        messages.append({"role": "user", "content": query})

        # 4. 调用 LLM
        response = await self._llm_port.chat(
            messages,
            temperature=_DEFAULT_TEMPERATURE,
            max_tokens=_DEFAULT_MAX_TOKENS,
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        if response is None:
            logger.debug(
                "ConsciousLLMHandler: LLM returned None (query=%r, %.1fms)",
                query[:50],
                elapsed_ms,
            )
            return {
                "success": False,
                "response": "",
                "error": "llm_unavailable",
                "tokens_used": 0,
                "latency_ms": elapsed_ms,
            }

        # 5. 写入工作记忆（best-effort）
        try:
            memory.remember("user", query)
            memory.remember("assistant", response)
        except RECOVERABLE_ERRORS:
            logger.debug("WorkingMemory.remember skipped", exc_info=True)

        return {
            "success": True,
            "response": response,
            "error": None,
            "tokens_used": 0,
            "latency_ms": elapsed_ms,
            "memory_items_used": len(attention.selected),
        }

    def _format_context(self, attention: Any) -> str:
        """将注意力选择结果格式化为上下文段落。"""
        try:
            lines = []
            for item in attention.selected:
                role_label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(
                    item.role, item.role
                )
                content_preview = item.content[:300]
                lines.append(f"[{role_label}] {content_preview}")
            if not lines:
                return ""
            return "【相关上下文】\n" + "\n".join(lines)
        except RECOVERABLE_ERRORS:
            return ""

    def _format_extra_context(self, context_data: dict[str, Any]) -> str:
        """格式化附加上下文。"""
        try:
            lines = []
            for key, value in context_data.items():
                if value is None:
                    continue
                lines.append(f"- {key}: {str(value)[:200]}")
            if not lines:
                return ""
            return "【附加上下文】\n" + "\n".join(lines)
        except RECOVERABLE_ERRORS:
            return ""


_handler: ConsciousLLMHandler | None = None


def get_conscious_llm_handler() -> ConsciousLLMHandler:
    """获取全局 ``ConsciousLLMHandler`` 单例。"""
    global _handler
    if _handler is None:
        _handler = ConsciousLLMHandler()
    return _handler


def reset_conscious_llm_handler() -> None:
    """重置单例（测试用）。"""
    global _handler
    _handler = None
