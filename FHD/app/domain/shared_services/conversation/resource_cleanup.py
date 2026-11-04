"""HTTP resource cleanup for the process-wide conversation service."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


async def close_conversation_service_clients(service: Any) -> None:
    """Close each distinct cached client owned by ``service``."""
    clients = (
        getattr(service, "_deepseek_async_client", None),
        getattr(service, "llm_adapter", None),
        getattr(service, "modstore_adapter", None),
    )
    seen: set[int] = set()
    for client in clients:
        if client is None or id(client) in seen:
            continue
        seen.add(id(client))
        close = getattr(client, "close", None)
        aclose = getattr(client, "aclose", None)
        try:
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
            elif callable(aclose):
                await aclose()
        except RECOVERABLE_ERRORS:
            logger.debug("conversation HTTP client close failed", exc_info=True)
    service._deepseek_async_client = None
    service._deepseek_async_loop = None
