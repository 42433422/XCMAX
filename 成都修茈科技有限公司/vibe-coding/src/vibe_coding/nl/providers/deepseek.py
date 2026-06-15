"""DeepSeek adapter (https://platform.deepseek.com).

DeepSeek's hosted endpoint is OpenAI-compatible at
``https://api.deepseek.com``. Local self-hosted DeepSeek-Coder /
DeepSeek-V2 instances served via ``vllm`` / ``ollama`` also speak the
same protocol — just pass ``base_url=``.
"""

from __future__ import annotations

import os

from .openai_compat import OpenAICompatibleLLM


class DeepSeekLLM(OpenAICompatibleLLM):
    """DeepSeek hosted / self-hosted LLM client."""

    default_base_url = "https://api.deepseek.com"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "deepseek-chat",
        *,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        verify_ssl: bool = True,
    ) -> None:
        resolved = api_key or os.environ.get("DEEPSEEK_API_KEY") or ""
        super().__init__(
            api_key=resolved,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
        )


__all__ = ["DeepSeekLLM"]
