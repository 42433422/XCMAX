"""官方 MCP Python SDK 的同步封装。

外部工具调用频率低，采用「每次调用建连、结束即关」的短连接模型，避免长驻
事件循环与进程泄漏。所有异常收敛为中文错误，不向上抛第三方异常。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextvars import copy_context
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Coroutine, TypeVar

from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    stop_before_delay,
    wait_random_exponential,
)

from app.application.tool_execution_deadline import remaining_invocation_seconds
from app.infrastructure.mcp.config import McpServerConfig
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

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

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _sdk_field(value: Any, name: str, alias: str, default: Any = None) -> Any:
    """MCP 2 uses Python snake_case fields; older clients expose wire aliases."""
    return getattr(value, name, getattr(value, alias, default))


def _sync(coro_factory: Callable[[], Coroutine[Any, Any, T]], timeout: float) -> T:
    """在独立线程运行协程，避免与请求所在事件循环互相阻塞。"""
    timeout = remaining_invocation_seconds(timeout)
    if timeout <= 0 or not math.isfinite(timeout):
        raise McpClientError("MCP 调用预算已耗尽", retryable=False)

    async def bounded() -> T:
        # The pool may have queued this call. Do not grant a fresh full timeout
        # when the worker eventually starts under the captured caller scope.
        remaining = remaining_invocation_seconds(timeout)
        if remaining <= 0:
            raise McpClientError("MCP 调用预算已耗尽", retryable=False)
        async with asyncio.timeout(remaining):
            return await coro_factory()

    def run() -> T:
        return asyncio.run(bounded())

    context = copy_context()
    future = _EXECUTOR.submit(context.run, run)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        future.cancel()
        raise McpClientError("MCP 服务器响应超时") from exc


async def _oauth_header(config: McpServerConfig) -> dict[str, str]:
    """可取消的 client_credentials 请求与隔离缓存；配置缺失时返回空。"""
    auth = dict(config.auth or {})
    if not auth:
        return {}
    key = hashlib.sha256(json.dumps(auth, sort_keys=True).encode()).hexdigest()
    now = time.time()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached and cached[1] > now:
            return {"Authorization": f"Bearer {cached[0]}"}
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
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
        from app.application.workflow.retry_policy import is_transport_error

        raise McpClientError(
            "MCP 授权服务器不可用",
            retryable=is_transport_error(exc) and not isinstance(exc, PermissionError),
        ) from exc
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise McpClientError("MCP 授权服务器未返回 access_token", retryable=False)
    try:
        expires = float(payload.get("expires_in", 300))
    except (TypeError, ValueError):
        expires = 300.0
    if math.isfinite(expires) and expires > 0:
        with _TOKEN_LOCK:
            _TOKEN_CACHE[key] = (token, now + max(0.0, expires - min(30.0, expires / 10)))
    return {"Authorization": f"Bearer {token}"}


async def _with_session(
    config: McpServerConfig,
    action: Callable[[Any], Awaitable[T]],
) -> T:
    try:
        from mcp import ClientSession
    except ImportError as exc:
        raise McpClientError("MCP 客户端依赖未安装", retryable=False) from exc

    if config.transport == "http":
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        headers = {**dict(config.headers), **(await _oauth_header(config))}
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
    hint = _sdk_field(annotations, "read_only_hint", "readOnlyHint")
    return hint is True


async def _list_all_tools(session: Any, *, max_pages: int = 10) -> list[Any]:
    from mcp import types

    collected: list[Any] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        result = await session.list_tools(params=params) if params else await session.list_tools()
        collected.extend(getattr(result, "tools", None) or [])
        cursor = _sdk_field(result, "next_cursor", "nextCursor")
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
        schema = _sdk_field(tool, "input_schema", "inputSchema")
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
        params = inspect.signature(dump).parameters
        return json.dumps(
            dump(mode="json") if "mode" in params else dump(), ensure_ascii=False, default=str
        )
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
    structured = _sdk_field(result, "structured_content", "structuredContent")
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


def _run_with_reconnect(
    factory: Callable[[], Coroutine[Any, Any, T]], timeout: float, *, retry_safe: bool = False
) -> T:
    """Use the existing Tenacity dependency; all attempts share one invocation budget."""
    budget = remaining_invocation_seconds(timeout)
    if budget <= 0 or not math.isfinite(budget):
        raise McpClientError("MCP 调用预算已耗尽", retryable=False)
    deadline = time.monotonic() + budget

    def attempt() -> T:
        remaining = remaining_invocation_seconds(deadline - time.monotonic())
        if remaining <= 0:
            raise McpClientError("MCP 调用预算已耗尽", retryable=False)
        return _sync(factory, remaining)

    return Retrying(
        stop=stop_after_attempt(2 if retry_safe else 1) | stop_before_delay(budget),
        wait=wait_random_exponential(multiplier=0.2, max=1.0),
        retry=retry_if_exception(_retryable_transport_error),
        sleep=time.sleep,
        reraise=True,
    )(attempt)


def _retryable_transport_error(error: BaseException) -> bool:
    from app.application.workflow.retry_policy import is_transport_error

    if isinstance(error, McpClientError):
        return error.retryable
    return not isinstance(
        error, (PermissionError, FileNotFoundError, IsADirectoryError, NotADirectoryError)
    ) and is_transport_error(error)


def call_tool(
    config: McpServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    retry_safe: bool = False,
) -> dict[str, Any]:
    """调用外部 MCP 工具，返回统一工具结果。"""
    frozen_arguments = copy.deepcopy(arguments or {})
    safe_read = retry_safe or tool_name in RESOURCE_ACTIONS
    uncertain = (
        {}
        if safe_read
        else {
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
        }
    )
    try:
        if tool_name in RESOURCE_ACTIONS:
            result = _run_with_reconnect(
                lambda: _with_session(
                    config,
                    lambda session: _run_synthetic(
                        session, tool_name, copy.deepcopy(frozen_arguments)
                    ),
                ),
                config.timeout_seconds,
                retry_safe=safe_read,
            )
        else:
            result = _run_with_reconnect(
                lambda: _with_session(
                    config,
                    lambda session: session.call_tool(tool_name, copy.deepcopy(frozen_arguments)),
                ),
                config.timeout_seconds,
                retry_safe=safe_read,
            )
        text = _result_text(result)
        is_error = bool(_sdk_field(result, "is_error", "isError", False))
        structured = _sdk_field(result, "structured_content", "structuredContent")
        invalid = (
            isinstance(structured, dict)
            and "success" in structured
            and type(structured["success"]) is not bool
        )
        business_error = isinstance(structured, dict) and structured.get("success") is False
        result_type = _sdk_field(result, "result_type", "resultType", "complete")
    except BOUNDARY_ERRORS as exc:  # The external SDK is an isolated plugin boundary.
        logger.warning("MCP 工具 %s.%s 调用失败：%s", config.name, tool_name, type(exc).__name__)
        return {
            "success": False,
            "error_code": "mcp_call_failed",
            "message": "MCP 工具调用失败",
            "retryable": safe_read and _retryable_transport_error(exc),
            **uncertain,
        }
    error_code = (
        "mcp_result_invalid"
        if invalid
        else "mcp_result_incomplete"
        if result_type != "complete"
        else "mcp_business_error"
        if business_error
        else "mcp_tool_error"
        if is_error
        else ""
    )
    return {
        "success": not bool(error_code),
        "tool": tool_name,
        "server": config.name,
        "content": text,
        "message": text if error_code else "",
        **({"structuredContent": deepcopy(structured)} if structured is not None else {}),
        **({"resultType": result_type} if result_type != "complete" else {}),
        **({"error_code": error_code, **uncertain} if error_code else {}),
    }


__all__ = ["McpClientError", "McpToolInfo", "call_tool", "list_tools"]
