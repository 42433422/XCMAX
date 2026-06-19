"""包装 services.conversation.llm_adapter.OpenAICompatibleAdapter。"""

from __future__ import annotations

import time
from typing import Any, cast

from app.utils.metrics import record_ai_call
from app.utils.operational_errors import RECOVERABLE_ERRORS


class OpenAICompatibleProvider:
    provider_id = "openai_compatible"

    def __init__(self, adapter: Any | None = None):
        self._adapter = adapter

    @property
    def is_configured(self) -> bool:
        if self._adapter is not None:
            return bool(getattr(self._adapter, "is_configured", False))
        from app.infrastructure.llm.providers.credentials import resolve_openai_env_credentials

        key, _ = resolve_openai_env_credentials()
        return bool(key)

    def _ensure_adapter(self) -> Any | None:
        if self._adapter is not None:
            return self._adapter

        from app.infrastructure.llm.providers.credentials import (
            resolve_default_chat_model,
            resolve_default_openai_provider,
            resolve_openai_env_credentials,
        )
        from app.services.conversation.llm_adapter import OpenAICompatibleAdapter

        provider = resolve_default_openai_provider()
        api_key, base_url = resolve_openai_env_credentials()
        if not api_key:
            return None
        self._adapter = OpenAICompatibleAdapter(
            provider=provider,
            api_key=api_key,
            model=resolve_default_chat_model(),
            base_url=base_url,
        )
        return self._adapter

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        adapter = self._ensure_adapter()
        if adapter is None or not getattr(adapter, "is_configured", False):
            return None
        t0 = time.perf_counter()
        try:
            result = await adapter.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            record_ai_call(self.provider_id, "chat", "success", time.perf_counter() - t0)
            return cast("dict[str, Any] | None", result)
        except RECOVERABLE_ERRORS:
            record_ai_call(self.provider_id, "chat", "error", time.perf_counter() - t0)
            raise
