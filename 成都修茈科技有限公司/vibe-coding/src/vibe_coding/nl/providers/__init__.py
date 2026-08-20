"""LLM provider adapters.

vibe-coding's :class:`LLMClient` Protocol is the only mandatory contract;
this subpackage ships ready-made adapters for the providers most users
reach for first:

- :class:`OpenAICompatibleLLM` — works against any "OpenAI-compatible"
  HTTP API (the de-facto standard now). The base class for the Chinese
  vendors below since most expose an OpenAI-compatible endpoint
  (``/v1/chat/completions``).
- :class:`QwenLLM` — Alibaba 通义千问 / DashScope.
- :class:`ZhipuLLM` — 智谱 GLM.
- :class:`MoonshotLLM` — Moonshot Kimi.
- :class:`DeepSeekLLM` — DeepSeek (open-source friendly).
- :class:`AnthropicLLM` — Claude (Anthropic).

A factory :func:`create_llm` picks the right adapter from a model id
plus optional credentials. Everything is **opt-in** — vibe-coding's
core does not depend on any vendor SDK; the adapters use plain
``urllib`` so installing ``vibe-coding[llm]`` only pulls in ``openai``
when you explicitly want it.

Usage::

    from vibe_coding.nl.providers import create_llm

    llm = create_llm("qwen-max", api_key="...")
    print(llm.chat("system", "user", json_mode=False))

    # or pin a base_url for an enterprise gateway
    llm = create_llm("glm-4", api_key="...", base_url="https://gw.example/v1")
"""

from __future__ import annotations

from .anthropic import AnthropicLLM
from .auto import (
    PROVIDER_PRESETS,
    ProviderInfo,
    create_llm,
    detect_provider,
    register_provider,
)
from .deepseek import DeepSeekLLM
from .moonshot import MoonshotLLM
from .openai_compat import OpenAICompatibleLLM
from .qwen import QwenLLM
from .zhipu import ZhipuLLM

__all__ = [
    "PROVIDER_PRESETS",
    "AnthropicLLM",
    "DeepSeekLLM",
    "MoonshotLLM",
    "OpenAICompatibleLLM",
    "ProviderInfo",
    "QwenLLM",
    "ZhipuLLM",
    "create_llm",
    "detect_provider",
    "register_provider",
]
