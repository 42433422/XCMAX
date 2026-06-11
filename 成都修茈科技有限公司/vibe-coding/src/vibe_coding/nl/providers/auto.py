"""Provider auto-detection + factory.

Lets users go from a model id (or a friendly alias) to a fully-wired
:class:`LLMClient` without remembering each vendor's class name:

    create_llm("qwen-max", api_key="sk-...")
    create_llm("glm-4-air")
    create_llm("kimi", model="moonshot-v1-128k")
    create_llm("claude-3-5-sonnet")
    create_llm("gpt-4o-mini")

Detection order:

1. **Explicit alias** — the head token of the input matches a key in
   :data:`PROVIDER_PRESETS` (``qwen``, ``glm``, ``kimi``, ``deepseek``,
   ``claude``, ``openai``).
2. **Model-id prefix** — common prefixes like ``qwen-``, ``glm-``,
   ``moonshot-``, ``deepseek-``, ``claude-``, ``gpt-`` map to the right
   provider.
3. **Custom registration** — users can call
   :func:`register_provider` to add their own preset for an internal
   gateway / fine-tuned model. The registry is global (process-scoped).

When no preset matches, the factory falls back to
:class:`OpenAICompatibleLLM` so users with an OpenAI-compatible
deployment behind ``base_url`` always have a path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..llm import LLMClient
from .anthropic import AnthropicLLM
from .deepseek import DeepSeekLLM
from .moonshot import MoonshotLLM
from .openai_compat import OpenAICompatibleLLM
from .qwen import QwenLLM
from .zhipu import ZhipuLLM


@dataclass(frozen=True)
class ProviderInfo:
    """One row in :data:`PROVIDER_PRESETS`."""

    name: str
    factory: Callable[..., LLMClient]
    aliases: tuple[str, ...] = ()
    model_prefixes: tuple[str, ...] = ()
    default_model: str = ""


def _openai_factory(**kwargs: Any) -> LLMClient:
    """Late-import to keep ``openai`` truly optional."""
    from ..llm import OpenAILLM

    return OpenAILLM(**kwargs)


PROVIDER_PRESETS: dict[str, ProviderInfo] = {
    "qwen": ProviderInfo(
        name="qwen",
        factory=QwenLLM,
        aliases=("qwen", "tongyi", "dashscope"),
        model_prefixes=("qwen-", "qwen2-", "qwen3-", "qwen2.5-"),
        default_model="qwen-plus",
    ),
    "zhipu": ProviderInfo(
        name="zhipu",
        factory=ZhipuLLM,
        aliases=("zhipu", "glm", "zhipuai", "bigmodel"),
        model_prefixes=("glm-", "chatglm-", "glm3-", "glm4-"),
        default_model="glm-4",
    ),
    "moonshot": ProviderInfo(
        name="moonshot",
        factory=MoonshotLLM,
        aliases=("moonshot", "kimi"),
        model_prefixes=("moonshot-", "kimi-"),
        default_model="moonshot-v1-32k",
    ),
    "deepseek": ProviderInfo(
        name="deepseek",
        factory=DeepSeekLLM,
        aliases=("deepseek",),
        model_prefixes=("deepseek-",),
        default_model="deepseek-chat",
    ),
    "anthropic": ProviderInfo(
        name="anthropic",
        factory=AnthropicLLM,
        aliases=("anthropic", "claude"),
        model_prefixes=("claude-",),
        default_model="claude-3-5-sonnet-latest",
    ),
    "openai": ProviderInfo(
        name="openai",
        factory=_openai_factory,
        aliases=("openai", "gpt"),
        model_prefixes=("gpt-", "o1-", "o3-", "o4-", "o5-"),
        default_model="gpt-4o-mini",
    ),
}


def register_provider(info: ProviderInfo) -> None:
    """Add a custom provider to the global registry.

    Useful for internal gateways (e.g. a corp-wide proxy that hosts
    fine-tuned models with their own prefix).
    """
    PROVIDER_PRESETS[info.name] = info


def detect_provider(model_or_alias: str) -> ProviderInfo | None:
    """Resolve ``model_or_alias`` to a registered provider.

    Matches in order: alias → model-id prefix. Returns ``None`` when
    nothing matches; the factory then falls back to
    :class:`OpenAICompatibleLLM`.
    """
    needle = model_or_alias.strip().lower()
    if not needle:
        return None
    for info in PROVIDER_PRESETS.values():
        if needle in info.aliases:
            return info
    for info in PROVIDER_PRESETS.values():
        for prefix in info.model_prefixes:
            if needle.startswith(prefix):
                return info
    return None


def create_llm(
    model_or_alias: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    **vendor_kwargs: Any,
) -> LLMClient:
    """Pick + construct an :class:`LLMClient` from a model id or alias.

    ``model_or_alias`` accepts:

    - a friendly alias (``"qwen"``, ``"kimi"``, ``"claude"``, …) — the
      provider's default model is used unless ``model=`` is passed via
      ``vendor_kwargs``;
    - a full model id (``"qwen-max"``, ``"glm-4-air"``, …) — used as the
      model name and the provider is inferred from the prefix.

    Unknown ids fall through to :class:`OpenAICompatibleLLM` so users
    pointing at a self-hosted vLLM / Ollama / LMStudio endpoint via
    ``base_url`` always get a working client.
    """
    info = detect_provider(model_or_alias)
    explicit_model = vendor_kwargs.pop("model", None)
    if info is None:
        # Fallback: OpenAI-compatible endpoint with the literal id as the
        # model name.
        return OpenAICompatibleLLM(
            api_key=api_key or "",
            model=explicit_model or model_or_alias,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **vendor_kwargs,
        )
    is_alias = model_or_alias.strip().lower() in info.aliases
    model = explicit_model or (info.default_model if is_alias else model_or_alias)
    kwargs: dict[str, Any] = dict(vendor_kwargs)
    if api_key is not None:
        kwargs["api_key"] = api_key
    if base_url is not None:
        kwargs["base_url"] = base_url
    kwargs.setdefault("temperature", temperature)
    if max_tokens is not None:
        kwargs.setdefault("max_tokens", max_tokens)
    kwargs["model"] = model
    return info.factory(**kwargs)


__all__ = [
    "PROVIDER_PRESETS",
    "ProviderInfo",
    "create_llm",
    "detect_provider",
    "register_provider",
]
