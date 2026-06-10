"""Zhipu GLM (智谱清言) adapter.

Zhipu's BigModel platform exposes an OpenAI-compatible endpoint at
``https://open.bigmodel.cn/api/paas/v4`` so we can reuse the base.

API key resolution order: explicit ``api_key`` → ``ZHIPUAI_API_KEY`` →
``ZHIPU_API_KEY``.

Notes:

- ``response_format`` is honoured on ``glm-4`` and newer; the base class
  passes it through automatically when ``json_mode=True``.
- Older models (``glm-3-turbo``) ignore the response_format flag — the
  prompt should already say "return JSON" for those.
"""

from __future__ import annotations

import os

from .openai_compat import OpenAICompatibleLLM


class ZhipuLLM(OpenAICompatibleLLM):
    """智谱 GLM LLM client."""

    default_base_url = "https://open.bigmodel.cn/api/paas/v4"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "glm-4",
        *,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        verify_ssl: bool = True,
    ) -> None:
        resolved = (
            api_key
            or os.environ.get("ZHIPUAI_API_KEY")
            or os.environ.get("ZHIPU_API_KEY")
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


__all__ = ["ZhipuLLM"]
