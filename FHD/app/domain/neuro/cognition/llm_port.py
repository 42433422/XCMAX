"""LLM 端口适配器——将现有 LLMProviderRegistry 适配为 Conscious 处理器可用的统一接口。

设计原则：
- 不重新发明 LLM 抽象（``app/infrastructure/llm/providers/base.py`` 已有 ``LLMProvider`` Protocol）。
- 不锁定到任何 LLM 提供方（Registry 支持 20+ provider：DeepSeek/OpenAI/Xiaomi/SiliconFlow…）。
- best-effort：LLM 不可用时返回 ``None``，不阻断 Conscious 处理。

Phase 2 的核心目标之一是"不限制 LLM"——本端口通过 ``get_active_provider()``
按路由顺序（modstore → openai_compatible → deepseek_legacy → openai_sdk）自动选型，
也可通过 ``LLM_PROVIDER`` / ``LLM_ROUTING_ORDER`` 环境变量或 ``X-LLM-Provider`` 请求头覆盖。
"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class LLMPort:
    """Conscious 处理器使用的 LLM 端口。

    封装 ``LLMProviderRegistry``，提供简化的 ``chat`` 接口。
    所有调用 best-effort：失败返回 ``None``，不抛异常。
    """

    def __init__(self, default_provider: str | None = None) -> None:
        self._default_provider = default_provider

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        """调用 LLM 生成回复。

        Args:
            messages: OpenAI 格式的消息列表 ``[{"role": "system", "content": "..."}]``。
            temperature: 采样温度。
            max_tokens: 最大生成 token 数。
            provider: 指定 provider ID（覆盖默认）。``None`` 则按路由顺序自动选型。

        Returns:
            LLM 生成的文本内容，或 ``None``（无可用 provider / 调用失败）。
        """
        try:
            from app.infrastructure.llm.providers.registry import (
                get_active_provider,
                get_llm_registry,
            )

            registry = get_llm_registry()
            target = provider or self._default_provider
            p = None

            if target:
                p = registry.get(target)
                if p is not None and not p.is_configured:
                    p = None

            if p is None:
                p = get_active_provider()

            if p is None or not p.is_configured:
                logger.debug("LLMPort: no provider configured")
                return None

            result = await p.chat_completion(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            if not isinstance(result, dict):
                return None

            choices = result.get("choices") or []
            if not choices:
                return None
            msg = choices[0].get("message") or {}
            content = str(msg.get("content") or "").strip()
            return content or None

        except RECOVERABLE_ERRORS:
            logger.debug("LLMPort.chat failed", exc_info=True)
            return None

    @property
    def is_available(self) -> bool:
        """是否有可用的 LLM provider（不发起请求，仅检查配置）。"""
        try:
            from app.infrastructure.llm.providers.registry import get_active_provider

            p = get_active_provider()
            return p is not None and p.is_configured
        except RECOVERABLE_ERRORS:
            return False


_port: LLMPort | None = None


def get_llm_port() -> LLMPort:
    """获取全局 ``LLMPort`` 单例。"""
    global _port
    if _port is None:
        _port = LLMPort()
    return _port


def reset_llm_port() -> None:
    """重置单例（测试用）。"""
    global _port
    _port = None
