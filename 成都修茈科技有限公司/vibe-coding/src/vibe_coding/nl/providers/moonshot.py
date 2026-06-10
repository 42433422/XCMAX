"""Moonshot AI (月之暗面 Kimi) adapter.

Moonshot uses an OpenAI-compatible endpoint at
``https://api.moonshot.cn/v1``. Long-context models like
``moonshot-v1-128k`` are supported transparently.

API key resolution order: explicit ``api_key`` → ``MOONSHOT_API_KEY``
→ ``KIMI_API_KEY``.
"""

from __future__ import annotations

import os

from .openai_compat import OpenAICompatibleLLM


class MoonshotLLM(OpenAICompatibleLLM):
    """Moonshot Kimi LLM client."""

    default_base_url = "https://api.moonshot.cn/v1"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "moonshot-v1-32k",
        *,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        verify_ssl: bool = True,
    ) -> None:
        resolved = (
            api_key
            or os.environ.get("MOONSHOT_API_KEY")
            or os.environ.get("KIMI_API_KEY")
            or ""
        )
        super().__init__(
            api_key=resolved,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
        )


__all__ = ["MoonshotLLM"]
