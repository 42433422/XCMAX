"""Owner-scoped access to the LLM configured in the XCAGI software account."""

from __future__ import annotations

import asyncio
import os
from contextvars import ContextVar, Token
from typing import Any, cast

_OWNER_USER_ID: ContextVar[int | None] = ContextVar("elt_llm_owner_user_id", default=None)


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

    async def lookup_call(self, call_id: str) -> dict[str, Any] | None:
        """What the market knows about one idempotency key; None when that is unknown.

        A market without the lookup route answers 404/405: recovery is unsupported
        and the caller stays fail-closed.
        """
        import re

        import httpx

        from app.application.elt_login_authorization import _platform_url

        if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", call_id or ""):
            return None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=10.0),
                headers={"Authorization": f"Bearer {self._token}"},
                trust_env=not bool((os.environ.get("XCAGI_MARKET_PROXY") or "").strip()),
                proxy=(os.environ.get("XCAGI_MARKET_PROXY") or "").strip() or None,
            ) as client:
                response = await client.get(f"{_platform_url()}/api/llm/chat/requests/{call_id}")
        except httpx.HTTPError:
            return None
        if response.status_code in {404, 405}:
            return {"supported": False}
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        state = body.get("state") if isinstance(body, dict) else None
        if state not in {"not_found", "processing", "completed", "failed"}:
            return None
        return {"supported": True, "state": state}

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
        from app.application.reviewed_excel_audit import ModelRequestNotSent, current_call_id
        from app.domain.shared_services.conversation.modstore_adapter import ModstorePlatformAdapter

        platform_url = _platform_url()
        call_id = current_call_id()
        if call_id:
            kwargs.setdefault("client_request_id", call_id)
        timeout = self._timeout_seconds
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
                    headers=headers,
                    trust_env=not bool((os.environ.get("XCAGI_MARKET_PROXY") or "").strip()),
                    proxy=(os.environ.get("XCAGI_MARKET_PROXY") or "").strip() or None,
                ) as client:
                    response = await client.get(f"{platform_url}/api/llm/resolve-chat-default")
                    response.raise_for_status()
                    route = response.json()
                break
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise ModelRequestNotSent("账户模型路由连接失败，未调用模型") from exc
                await asyncio.sleep(0.25 * (attempt + 1))
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
        # First shot keeps allow_failover=False (login/chat pin contract). On
        # config 404/400/403, strip the pin and retry with explicit failover so
        # analyzed/preview audited calls can use the intelligent-chat chain.
        kwargs.update(
            provider=provider_name,
            model=model_name,
            allow_failover=False,
            _pending_client_failover=True,
        )
        from app.application.elt.errors import provider_http_status
        from app.infrastructure.modstore_transport import MarketModelError

        def _clear_pin() -> None:
            for attr in ("_route_snapshots", "_route_aliases"):
                cache = getattr(adapter, attr, None)
                if isinstance(cache, dict):
                    cache.clear()
            if hasattr(adapter, "_account_default"):
                adapter._account_default = None

        async def _chat(options: dict[str, Any]) -> dict[str, Any] | None:
            import asyncio

            from app.application.elt.errors import never_connected
            from app.infrastructure.llm.model_admission import (
                admit_model_call,
                model_call_slot,
                model_rate_limit_scope,
            )

            for attempt in range(3):
                try:
                    with (
                        model_rate_limit_scope({"local_user_id": self.owner_user_id}),
                        model_call_slot(self, profile="elt_session"),
                    ):
                        admit_model_call(self, profile="elt_session")
                        return cast(
                            "dict[str, Any] | None",
                            await adapter.chat_completion(
                                messages=messages,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                **options,
                            ),
                        )
                except httpx.TransportError as exc:
                    # The pinned route has exactly one stream. Only connection
                    # establishment failure proves no model request was sent.
                    if (
                        options.get("allow_failover") is not False
                        or not never_connected(exc)
                        or attempt == 2
                    ):
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
            raise RuntimeError("unreachable model connection retry")

        try:
            try:
                return await _chat(kwargs)
            except (MarketModelError, ValueError) as exc:
                status = provider_http_status(exc)
                if status not in {404, 400, 403}:
                    raise
                _clear_pin()
                retry = {
                    key: value
                    for key, value in kwargs.items()
                    if key
                    not in {
                        "route_token",
                        "key_source",
                        "config_revision",
                        "_pending_client_failover",
                    }
                }
                retry.update(allow_failover=True)
                if retry.get("client_request_id"):
                    # The refused first shot owns its key on an idempotent market.
                    retry["client_request_id"] = f"{retry['client_request_id']}-r"
                return await _chat(retry)
        finally:
            await adapter.close()


def bind_elt_llm_owner(owner_user_id: int) -> Token[int | None]:
    return _OWNER_USER_ID.set(int(owner_user_id))


def reset_elt_llm_owner(token: Token[int | None]) -> None:
    _OWNER_USER_ID.reset(token)


def current_elt_llm_owner() -> int | None:
    return _OWNER_USER_ID.get()


def current_owner_market_provider(*, timeout_seconds: float) -> SessionMarketProvider | None:
    owner_user_id = current_elt_llm_owner()
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
    "bind_elt_llm_owner",
    "current_elt_llm_owner",
    "current_owner_market_provider",
    "reset_elt_llm_owner",
]
