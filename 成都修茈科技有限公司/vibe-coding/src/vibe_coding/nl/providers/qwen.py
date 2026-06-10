"""Alibaba Qwen / DashScope adapter.

Two endpoint flavours are supported:

1. **OpenAI-compatible** (default): DashScope's
   ``https://dashscope.aliyuncs.com/compatible-mode/v1`` accepts the
   standard ``/chat/completions`` request shape — this is what we use.
2. **Native DashScope** ``services/aigc/text-generation/generation``:
   not implemented in tree (falls back to compatible mode); subclass
   and override :meth:`_post` if you need native streaming.

API key resolution order: explicit ``api_key`` argument →
``DASHSCOPE_API_KEY`` env var → ``QWEN_API_KEY`` env var.
"""

from __future__ import annotations

import os
from typing import Any

from .openai_compat import OpenAICompatibleLLM


class QwenLLM(OpenAICompatibleLLM):
    """通义千问 / DashScope LLM client."""

    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "qwen-plus",
        *,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        enable_search: bool = False,
        verify_ssl: bool = True,
    ) -> None:
        resolved = api_key or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or ""
        super().__init__(
            api_key=resolved,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
        )
        self.enable_search = bool(enable_search)

    def transform_request(
        self,
        body: dict[str, Any],
        *,
        system: str,
        user: str,
        json_mode: bool,
    ) -> dict[str, Any]:
        # DashScope adds an ``enable_search`` extra param for grounded queries.
        if self.enable_search:
            body.setdefault("extra_body", {})["enable_search"] = True
        return body


__all__ = ["QwenLLM"]
