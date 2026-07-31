"""Owner-scoped access to the LLM configured in the XCAGI software account."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from typing import Any

_OWNER_USER_ID: ContextVar[int | None] = ContextVar("etl_llm_owner_user_id", default=None)


class SessionMarketProvider:
    """Tenant-safe provider backed by the current user's persisted market session."""

    provider_id = "modstore"

    def __init__(self, owner_user_id: int, token: str, *, timeout_seconds: float) -> None:
        self.owner_user_id = owner_user_id
        self._token = token
        self._timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    def with_timeout(self, timeout_seconds: float) -> SessionMarketProvider:
        return SessionMarketProvider(
            self.owner_user_id,
            self._token,
            timeout_seconds=timeout_seconds,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        import httpx

        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

        platform_url = (
            (
                os.environ.get("XCAGI_MARKET_BASE_URL")
                or os.environ.get("MODSTORE_PLATFORM_URL")
                or "http://127.0.0.1:8765"
            )
            .strip()
            .rstrip("/")
        )
        timeout = self._timeout_seconds
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            headers=headers,
        ) as client:
            response = await client.get(f"{platform_url}/api/llm/resolve-chat-default")
            response.raise_for_status()
            route = response.json()
        provider_name = str(route.get("provider") or "").strip()
        model_name = str(route.get("model") or "").strip()
        if not route.get("ok") or not provider_name or not model_name:
            raise ValueError("market default LLM route unavailable")
        adapter = ModstorePlatformAdapter(
            platform_url=platform_url,
            auth_token=self._token,
            user_id=self.owner_user_id,
            default_provider=provider_name,
            default_model=model_name,
            timeout=timeout,
        )
        try:
            return await adapter.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        finally:
            await adapter.close()


def bind_etl_llm_owner(owner_user_id: int) -> Token[int | None]:
    return _OWNER_USER_ID.set(int(owner_user_id))


def reset_etl_llm_owner(token: Token[int | None]) -> None:
    _OWNER_USER_ID.reset(token)


def current_etl_llm_owner() -> int | None:
    return _OWNER_USER_ID.get()


def current_owner_market_provider(*, timeout_seconds: float) -> SessionMarketProvider | None:
    owner_user_id = current_etl_llm_owner()
    if owner_user_id is None:
        return None
    from app.fastapi_routes.market_account import latest_session_market_token

    token = latest_session_market_token(user_id=owner_user_id)
    if not token:
        return None
    return SessionMarketProvider(
        owner_user_id,
        token,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "SessionMarketProvider",
    "bind_etl_llm_owner",
    "current_etl_llm_owner",
    "current_owner_market_provider",
    "reset_etl_llm_owner",
]
