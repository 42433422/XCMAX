"""LLM Provider 协议与统一返回结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.infrastructure.modstore_transport import MarketModelError


def raise_for_stream_failure(chunk: Any) -> None:
    """Preserve explicit failures before SDK/market streams become text-only."""

    def field(value: Any, name: str) -> Any:
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    choices = field(chunk, "choices")
    choice = choices[0] if isinstance(choices, (list, tuple)) and choices else chunk
    finishes = (field(choice, "finish_reason"), field(chunk, "finish_reason"))
    refusal = any(
        field(value, "refusal")
        for value in (chunk, choice, field(choice, "delta"), field(choice, "message"))
    )
    if "length" in finishes:
        raise MarketModelError({"status": 502}, code="model_output_truncated")
    if "content_filter" in finishes or refusal:
        raise MarketModelError({"status": 502}, code="model_response_blocked")


@dataclass(frozen=True)
class ChatResult:
    """OpenAI chat/completions 兼容的精简结果。"""

    raw: dict[str, Any]
    provider_id: str
    model: str
    token_count: int = 0

    @property
    def content(self) -> str:
        choices = self.raw.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        return str(msg.get("content") or "")


@runtime_checkable
class LLMProvider(Protocol):
    """可插拔 LLM 提供方。"""

    @property
    def provider_id(self) -> str: ...

    @property
    def is_configured(self) -> bool: ...

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...
