"""L3 LLM 推断器的客户端适配器。

``LlmInferencer`` 期望注入一个具备 ``async chat_completion(messages) -> dict``
（OpenAI 原始 JSON 形态）的客户端，而本仓库现有的 LLM 客户端
（``app.infrastructure.llm.client.get_openai_compatible_client``）是同步的
``openai.OpenAI`` 单例。这里做一层薄适配：

- 复用主对话已配置的云端凭证（OPENAI_API_KEY/BASE_URL/MODEL 或 MIMO_*），无需新增 key。
- 用 ``asyncio.to_thread`` 把同步调用挪到线程池，避免阻塞事件循环。
- offline 模式或未配置凭证时 ``get_openai_compatible_client`` 抛错，由 ``LlmInferencer``
  的容错分支降级为中性值——L3 自然待命，不影响对话。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PersonaLlmClient:
    """同步 OpenAI 兼容客户端 → 异步 ``chat_completion`` 适配器。"""

    def __init__(self, temperature: float = 0.0, max_tokens: int = 300):
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def chat_completion(self, messages: list[dict]) -> dict[str, Any]:
        """调用主对话的 LLM 做一次风格校准补全。

        Returns:
            OpenAI 原始形态 dict：``{"choices": [{"message": {"content": "..."}}]}``
        """
        return await asyncio.to_thread(self._call_sync, messages)

    def _call_sync(self, messages: list[dict]) -> dict[str, Any]:
        from app.infrastructure.llm.client import (
            get_openai_compatible_client,
            resolve_chat_model,
        )

        client = get_openai_compatible_client()
        model = resolve_chat_model()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        content = resp.choices[0].message.content
        return {"choices": [{"message": {"content": content}}]}
