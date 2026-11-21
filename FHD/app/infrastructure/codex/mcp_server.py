"""Private run-authenticated MCP endpoint backed by the official MCP SDK."""

from __future__ import annotations

import json
from typing import Any

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from app.infrastructure.codex.tools import CodexToolBridge, mcp_tool_definitions

MCP_PATH = "/api/agent-runtime/codex/mcp"
router = APIRouter(tags=["codex-runtime"])


class _McpResponse(Response):
    def __init__(self, *, token: str, store: CodexBindingStore, bridge: CodexToolBridge) -> None:
        super().__init__(content=None)
        self.token, self.store, self.bridge = token, store, bridge

    async def __call__(self, scope, receive, send) -> None:
        from mcp.server.context import ServerRequestContext
        from mcp.server.lowlevel import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.types import (
            CallToolRequestParams,
            CallToolResult,
            ListToolsResult,
            PaginatedRequestParams,
            TextContent,
        )

        definitions = mcp_tool_definitions()

        async def list_tools(
            _ctx: ServerRequestContext[Any], _params: PaginatedRequestParams | None
        ) -> ListToolsResult:
            await anyio.to_thread.run_sync(self.store.authenticate, self.token, "mcp")
            return ListToolsResult(tools=definitions)

        async def call_tool(
            _ctx: ServerRequestContext[Any], params: CallToolRequestParams
        ) -> CallToolResult:
            try:
                result = await anyio.to_thread.run_sync(
                    self.bridge.invoke, self.token, params.name, params.arguments or {}
                )
            except CodexBindingError as exc:
                result = {
                    "success": False,
                    "verified": False,
                    "error_code": exc.code,
                    "message": str(exc),
                }
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
                is_error=result.get("success") is False,
            )

        # Each request owns its SDK session. No connection-local identity or
        # tool-result cache can survive into another account's HTTP request.
        schemas = {tool.name: tool.input_schema for tool in definitions}
        server = Server(
            "xcmax-controlled-business-tools",
            version="1",
            on_list_tools=list_tools,
            on_call_tool=call_tool,
            get_tool_input_schema=schemas.get,
        )
        manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)
        async with manager.run():
            await manager.handle_request(scope, receive, send)


@router.api_route(MCP_PATH, methods=["GET", "POST", "DELETE"])
async def codex_mcp(request: Request):
    header = request.headers.get("authorization", "")
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return JSONResponse({"success": False, "error_code": "token_required"}, status_code=401)
    store = getattr(request.app.state, "codex_binding_store", None)
    bridge = getattr(request.app.state, "codex_tool_bridge", None)
    run_id = getattr(request.app.state, "codex_run_id", None)
    if (
        not store
        or not bridge
        or not isinstance(run_id, str)
        or not run_id
        or bridge.run_id != run_id
    ):
        return JSONResponse(
            {"success": False, "error_code": "runtime_scope_missing"}, status_code=503
        )
    try:
        binding = await anyio.to_thread.run_sync(store.authenticate, token, "mcp")
        if binding.run_id != run_id:
            raise CodexBindingError("scope_conflict", "运行凭据不属于此工具入口")
    except CodexBindingError as exc:
        return JSONResponse({"success": False, "error_code": exc.code}, status_code=403)
    return _McpResponse(token=token, store=store, bridge=bridge)
