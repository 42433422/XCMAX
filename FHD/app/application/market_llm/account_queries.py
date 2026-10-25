"""Read provider and credential metadata using the caller's credential snapshot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from logging import Logger
from typing import cast

import httpx

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import Connection, Payload
from .responses import _response_status_code


async def available_providers(
    connection: Connection, get_client: Callable[[], Awaitable[httpx.AsyncClient]], logger: Logger
) -> list[Payload]:
    try:
        client = await get_client()
        response = await client.get(
            f"{connection.platform_url}/api/llm/providers", headers=connection.headers()
        )
        status = _response_status_code(response)
        if status == 200:
            return cast(list[Payload], response.json().get("providers", []))
        logger.warning("[Modstore] 获取供应商列表失败: %s", status)
    except RECOVERABLE_ERRORS as exc:
        logger.error("[Modstore] 查询供应商异常: %s", exc)
    return []


async def credential_status(
    connection: Connection, provider: str, get_client: Callable[[], Awaitable[httpx.AsyncClient]]
) -> Payload:
    try:
        client = await get_client()
        response = await client.get(
            f"{connection.platform_url}/api/llm/credential-status/{provider}",
            headers=connection.headers(),
        )
        status = _response_status_code(response)
        if status == 200:
            return cast(Payload, response.json())
        return {"error": f"HTTP {status}"}
    except RECOVERABLE_ERRORS as exc:
        return {"error": str(exc)}
