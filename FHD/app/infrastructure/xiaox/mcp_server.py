"""Private run-authenticated MCP endpoint backed by the official MCP SDK."""

from __future__ import annotations

import json

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.infrastructure.xiaox.binding import XiaoxBindingError
from app.infrastructure.xiaox.tool_schemas import schema_violations
from app.infrastructure.xiaox.tools import XiaoxToolBridge, mcp_tool_definitions

MCP_PATH = "/api/agent-runtime/xiaox/mcp"
router = APIRouter(tags=["xiaox-runtime"])


class _McpResponse(Response):
    def __init__(self, *, token: str, bridge: XiaoxToolBridge) -> None:
        super().__init__(content=None)
        self.token, self.bridge = token, bridge

    async def __call__(self, scope, receive, send) -> None:
        from jsonschema import Draft202012Validator
        from mcp.server import ServerRequestContext
        from mcp.server.lowlevel import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.types import (
            CallToolRequestParams,
            CallToolResult,
            ListToolsResult,
            PaginatedRequestParams,
            TextContent,
        )

        # The per-request catalog improves selection. Calls still resolve the exact
        # pair against live authority rather than a snapshot sent to the model.
        definitions = mcp_tool_definitions()
        input_validators = {
            tool.name: Draft202012Validator(tool.input_schema) for tool in definitions
        }

        async def list_tools(
            _ctx: ServerRequestContext, _params: PaginatedRequestParams | None
        ) -> ListToolsResult:
            tools = await anyio.to_thread.run_sync(self.bridge.list_tool_definitions, self.token)
            return ListToolsResult(tools=tools)

        async def call_tool(
            _ctx: ServerRequestContext, params: CallToolRequestParams
        ) -> CallToolResult:
            try:
                arguments = params.arguments or {}
                validator = input_validators.get(params.name)
                violations = (
                    schema_violations(validator.iter_errors(arguments)) if validator else []
                )
                if violations:
                    result = await anyio.to_thread.run_sync(
                        self.bridge.reject_invalid_arguments,
                        self.token,
                        params.name,
                        arguments,
                        violations,
                    )
                else:
                    result = await anyio.to_thread.run_sync(
                        self.bridge.invoke, self.token, params.name, arguments
                    )
            except XiaoxBindingError as exc:
                result = {
                    "success": False,
                    "verified": False,
                    "error_code": exc.code,
                    "message": str(exc),
                }
                if params.name == "capability_describe" and exc.code == "permission_denied":
                    result["next_call"] = {"name": "capability_search", "arguments": {}}
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structured_content=result,
                is_error=result.get("success") is False,
            )

        # MCP SDK 2.x registers lowlevel handlers at construction, not via decorators.
        server = Server(
            "xcmax-controlled-business-tools",
            version="1",
            on_list_tools=list_tools,
            on_call_tool=call_tool,
        )

        # Each request owns its SDK session. No connection-local identity or
        # tool-result cache can survive into another account's HTTP request.
        manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)
        async with manager.run():
            await manager.handle_request(scope, receive, send)


@router.api_route(MCP_PATH, methods=["GET", "POST", "DELETE"])
async def xiaox_mcp(request: Request):
    header = request.headers.get("authorization", "")
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return JSONResponse({"success": False, "error_code": "token_required"}, status_code=401)
    store = getattr(request.app.state, "xiaox_binding_store", None)
    bridge = getattr(request.app.state, "xiaox_tool_bridge", None)
    run_id = getattr(request.app.state, "xiaox_run_id", None)
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
            raise XiaoxBindingError("scope_conflict", "运行凭据不属于此工具入口")
    except XiaoxBindingError as exc:
        return JSONResponse({"success": False, "error_code": exc.code}, status_code=403)
    return _McpResponse(token=token, bridge=bridge)
