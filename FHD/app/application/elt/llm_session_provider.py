"""Owner-scoped access to the LLM configured in the XCAGI software account."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, cast

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

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        import httpx

        from app.application.elt_login_authorization import _platform_url
        from app.application.reviewed_excel_audit import ModelRequestNotSent
        from app.domain.shared_services.conversation.modstore_adapter import ModstorePlatformAdapter

        platform_url = _platform_url()
        timeout = self._timeout_seconds
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
                headers=headers,
            ) as client:
                response = await client.get(f"{platform_url}/api/llm/resolve-chat-default")
                response.raise_for_status()
                route = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelRequestNotSent("账户模型路由不可用，未调用模型") from exc
        if not isinstance(route, dict):
            raise ModelRequestNotSent("账户模型路由无效，未调用模型")
        provider_name, model_name = route.get("provider"), route.get("model")
        if (
            not route.get("ok")
            or not isinstance(provider_name, str)
            or not isinstance(model_name, str)
            or not provider_name.strip()
            or not model_name.strip()
        ):
            raise ModelRequestNotSent("账户尚未配置可用模型，未调用模型")
        provider_name, model_name = provider_name.strip().lower(), model_name.strip()
        adapter = ModstorePlatformAdapter(
            platform_url=platform_url,
            auth_token=self._token,
            user_id=self.owner_user_id,
            default_provider=provider_name,
            default_model=model_name,
            timeout=timeout,
        )
        for key in ("route_token", "key_source", "config_revision"):
            kwargs.pop(key, None)
            value = route.get(key)
            if isinstance(value, str) and value:
                kwargs[key] = value
        kwargs.update(provider=provider_name, model=model_name, allow_failover=False)
        from app.infrastructure.modstore_transport import MarketModelError

        try:
            try:
                return cast(
                    "dict[str, Any] | None",
                    await adapter.chat_completion(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    ),
                )
            except MarketModelError as exc:
                # Audited template calls must keep the recorded body; callers map 404.
                if kwargs.get("_reviewed_excel_audit_response") is not None:
                    raise
                if getattr(exc, "status_code", None) not in {404, 400, 403}:
                    raise
                for attr in ("_route_snapshots", "_route_aliases"):
                    cache = getattr(adapter, attr, None)
                    if isinstance(cache, dict):
                        cache.clear()
                if hasattr(adapter, "_account_default"):
                    adapter._account_default = None
                retry = {
                    key: value
                    for key, value in kwargs.items()
                    if key not in {"route_token", "key_source", "config_revision"}
                }
                retry.update(allow_failover=True)
                return cast(
                    "dict[str, Any] | None",
                    await adapter.chat_completion(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **retry,
                    ),
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
    from app.application.elt_login_authorization import current_model_session_id
    from app.fastapi_routes.market_account import latest_session_market_token, session_market_token

    session_id = current_model_session_id(owner_user_id)
    if session_id is not None:
        token = session_market_token(session_id) if session_id else ""
    else:
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
