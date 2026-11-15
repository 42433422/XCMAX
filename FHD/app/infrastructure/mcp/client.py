"""官方 MCP Python SDK 的同步封装。

外部工具调用频率低，采用「每次调用建连、结束即关」的短连接模型，避免长驻
事件循环与进程泄漏。所有异常收敛为中文错误，不向上抛第三方异常。
"""

from __future__ import annotations

import asyncio
import logging
import threading
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


async def _with_session(
    config: McpServerConfig,
    action: Callable[[Any], Awaitable[T]],
) -> T:
    try:
        from mcp import ClientSession
    except ImportError as exc:
        raise McpClientError("MCP 客户端依赖未安装") from exc

    if config.transport == "http":
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(config.url) as streams:
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


def list_tools(config: McpServerConfig) -> list[McpToolInfo]:
    """列出一个 MCP 服务器暴露的工具；失败时返回空列表。"""
    try:
        result = _sync(
            lambda: _with_session(config, lambda session: session.list_tools()),
            config.timeout_seconds,
        )
    except McpClientError as exc:
        logger.warning("MCP 服务器 %s 工具发现失败：%s", config.name, exc)
        return []
    except RECOVERABLE_ERRORS as exc:
        logger.warning("MCP 服务器 %s 工具发现异常：%s", config.name, exc)
        return []
    tools: list[McpToolInfo] = []
    for tool in getattr(result, "tools", None) or []:
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


def _result_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def call_tool(
    config: McpServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """调用外部 MCP 工具，返回统一工具结果。"""
    try:
        result = _sync(
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
