"""官方 MCP Python SDK 的同步封装。

外部工具调用频率低，采用「每次调用建连、结束即关」的短连接模型，避免长驻
事件循环与进程泄漏。所有异常收敛为中文错误，不向上抛第三方异常。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Coroutine, TypeVar

from app.infrastructure.mcp.config import McpServerConfig
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

T = TypeVar("T")

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mcp-client")
_LOCK = threading.Lock()
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}

RESOURCE_ACTIONS = (
    "mcp_list_resources",
    "mcp_read_resource",
    "mcp_list_prompts",
    "mcp_get_prompt",
)


@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class McpClientError(RuntimeError):
    """MCP 连接或调用失败；调用方按工具失败处理。"""


def _sync(coro_factory: Callable[[], Coroutine[Any, Any, T]], timeout: float) -> T:
    """在独立线程运行协程，避免与请求所在事件循环互相阻塞。"""

    def run() -> T:
        return asyncio.run(coro_factory())

    future = _EXECUTOR.submit(run)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        future.cancel()
        raise McpClientError("MCP 服务器响应超时") from exc


def _oauth_header(config: McpServerConfig) -> dict[str, str]:
    """client_credentials 令牌获取与缓存；配置缺失时返回空。"""
    auth = dict(config.auth or {})
    if not auth:
        return {}
    key = f"{auth.get('token_url')}|{auth.get('client_id')}"
    now = time.time()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached and cached[1] > now:
            return {"Authorization": f"Bearer {cached[0]}"}
    try:
        import httpx

        response = httpx.post(
            str(auth.get("token_url") or ""),
            data={
                "grant_type": "client_credentials",
                "client_id": str(auth.get("client_id") or ""),
                "client_secret": str(auth.get("client_secret") or ""),
                "scope": str(auth.get("scope") or ""),
            },
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except RECOVERABLE_ERRORS as exc:
        raise McpClientError("MCP 授权服务器不可用") from exc
    token = str((payload or {}).get("access_token") or "")
    if not token:
        raise McpClientError("MCP 授权服务器未返回 access_token")
    try:
        expires = float((payload or {}).get("expires_in") or 300)
    except (TypeError, ValueError):
        expires = 300.0
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, now + max(30.0, expires - 30.0))
    return {"Authorization": f"Bearer {token}"}


async def _with_session(
    config: McpServerConfig,
    action: Callable[[Any], Awaitable[T]],
) -> T:
    try:
        from mcp import ClientSession
    except ImportError as exc:
        raise McpClientError("MCP 客户端依赖未安装") from exc

    if config.transport == "http":
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        headers = {**dict(config.headers), **_oauth_header(config)}
        client = create_mcp_http_client(headers=headers or None)
        async with client:
            async with streamable_http_client(config.url, http_client=client) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await action(session)

    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env) or None,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await action(session)


def _read_only(tool: Any) -> bool:
    annotations = getattr(tool, "annotations", None)
    hint = getattr(annotations, "readOnlyHint", None)
    return hint is True


async def _list_all_tools(session: Any, *, max_pages: int = 10) -> list[Any]:
    from mcp import types

    collected: list[Any] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        result = await session.list_tools(params=params) if params else await session.list_tools()
        collected.extend(getattr(result, "tools", None) or [])
        cursor = getattr(result, "nextCursor", None)
        if not cursor:
            break
    return collected


def list_tools(config: McpServerConfig) -> list[McpToolInfo]:
    """列出一个 MCP 服务器暴露的工具（含分页）；失败时返回空列表。"""
    try:
        raw_tools = _sync(lambda: _with_session(config, _list_all_tools), config.timeout_seconds)
    except McpClientError as exc:
        logger.warning("MCP 服务器 %s 工具发现失败：%s", config.name, exc)
        return []
    except RECOVERABLE_ERRORS as exc:
        logger.warning("MCP 服务器 %s 工具发现异常：%s", config.name, exc)
        return []
    tools: list[McpToolInfo] = []
    for tool in raw_tools:
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        schema = getattr(tool, "inputSchema", None)
        tools.append(
            McpToolInfo(
                name=name,
                description=str(getattr(tool, "description", "") or "")[:240],
                input_schema=schema if isinstance(schema, dict) else {},
                read_only=_read_only(tool),
            )
        )
    return tools


def _serialize(value: Any) -> str:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return json.dumps(dump(mode="json"), ensure_ascii=False)
        except TypeError:
            return json.dumps(dump(), ensure_ascii=False, default=str)
    return json.dumps(value, ensure_ascii=False, default=str)


def _result_text(result: Any) -> str:
    for attribute in ("content", "contents", "messages"):
        raw = getattr(result, attribute, None)
        if isinstance(raw, str):
            return raw
        parts: list[str] = []
        for item in raw or []:
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                content = getattr(item, "content", None)
                text = getattr(content, "text", None) if content is not None else None
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
    structured = getattr(result, "structuredContent", None)
    return _serialize(structured) if structured is not None else ""


async def _run_synthetic(session: Any, action: str, arguments: dict[str, Any]) -> Any:
    if action == "mcp_list_resources":
        return await session.list_resources()
    if action == "mcp_read_resource":
        return await session.read_resource(str(arguments.get("uri") or ""))
    if action == "mcp_list_prompts":
        return await session.list_prompts()
    return await session.get_prompt(
        str(arguments.get("name") or ""),
        arguments.get("arguments") if isinstance(arguments.get("arguments"), dict) else None,
    )


def _run_with_reconnect(factory: Callable[[], Coroutine[Any, Any, T]], timeout: float) -> T:
    """短连接失败后重连一次，覆盖子进程启动抖动与瞬时断线。"""
    last: Exception | None = None
    for attempt in range(2):
        try:
            return _sync(factory, timeout)
        except (McpClientError, OSError, ConnectionError, TimeoutError) as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.2)
    raise last if last is not None else McpClientError("MCP 调用失败")


def call_tool(
    config: McpServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """调用外部 MCP 工具，返回统一工具结果。"""
    try:
        if tool_name in RESOURCE_ACTIONS:
            result = _run_with_reconnect(
                lambda: _with_session(
                    config, lambda session: _run_synthetic(session, tool_name, arguments or {})
                ),
                config.timeout_seconds,
            )
        else:
            result = _run_with_reconnect(
                lambda: _with_session(
                    config, lambda session: session.call_tool(tool_name, arguments or {})
                ),
                config.timeout_seconds,
            )
    except McpClientError as exc:
        return {"success": False, "error_code": "mcp_unavailable", "message": str(exc)}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("MCP 工具 %s.%s 调用失败：%s", config.name, tool_name, exc)
        return {"success": False, "error_code": "mcp_call_failed", "message": "MCP 工具调用失败"}
    text = _result_text(result)
    is_error = bool(getattr(result, "isError", False))
    return {
        "success": not is_error,
        "tool": tool_name,
        "server": config.name,
        "content": text,
        "message": text if is_error else "",
        **({"error_code": "mcp_tool_error"} if is_error else {}),
    }


__all__ = ["McpClientError", "McpToolInfo", "call_tool", "list_tools"]
