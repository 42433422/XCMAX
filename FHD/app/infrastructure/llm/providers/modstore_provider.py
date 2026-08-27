"""包装 ModstorePlatformAdapter。"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from app.utils.metrics import record_ai_call
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ModstoreProvider:
    provider_id = "modstore"

    def __init__(
        self,
        adapter: Any | None = None,
        *,
        session_id: str | None = None,
        credential_scope: str = "request",
    ):
        self._adapter = adapter
        self._session_id = str(session_id or "").strip()
        self.credential_scope = credential_scope

    @property
    def is_configured(self) -> bool:
        return self._adapter is not None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if self._adapter is None:
            return None
        t0 = time.perf_counter()
        try:
            try:
                result = await self._adapter.chat_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except RECOVERABLE_ERRORS as exc:
                if not self._session_id or not self._is_auth_error(exc):
                    raise
                refreshed = await self._refresh_session_token()
                if not refreshed:
                    raise
                logger.info("market LLM credential refreshed for background session")
                result = await self._adapter.chat_completion(
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
        finally:
            await self._close_background_client()

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 401:
            return True
        text = str(exc).lower()
        return any(
            marker in text
            for marker in ("平台错误(401)", "status code 401", "401 unauthorized")
        )

    async def _refresh_session_token(self) -> bool:
        try:
            from app.fastapi_routes.market_account import resolve_valid_market_access_token

            old_token = str(getattr(self._adapter, "auth_token", "") or "").strip()
            token = str(await resolve_valid_market_access_token(self._session_id) or "").strip()
            if not token or token == old_token:
                return False

            old_client = getattr(self._adapter, "_client", None)
            self._adapter.auth_token = token
            self._adapter._client = None
            if old_client is not None and not getattr(old_client, "is_closed", False):
                await old_client.aclose()
            return True
        except RECOVERABLE_ERRORS:
            logger.warning("market LLM credential refresh failed", exc_info=True)
            return False

    async def _close_background_client(self) -> None:
        """Transient background providers must not leak one client per event."""
        if self.credential_scope not in {"desktop_session", "session"}:
            return
        try:
            client = getattr(self._adapter, "_client", None)
            self._adapter._client = None
            if client is not None and not getattr(client, "is_closed", False):
                await client.aclose()
        except RECOVERABLE_ERRORS:
            logger.debug("background market client close failed", exc_info=True)
