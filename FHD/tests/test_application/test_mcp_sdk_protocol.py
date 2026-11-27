"""Real MCP SDK transports preserve protocol and business outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.application.tools.mcp import registry as mcp_registry
from app.infrastructure.mcp import config as mcp_config
from app.infrastructure.mcp.client import McpToolInfo
from tests.test_application.test_mcp_tools import (
    _config_file,
)
from tests.test_application.test_mcp_tools import (
    _reset_cache as _reset_cache,
)


@pytest.mark.parametrize(
    "business,protocol_error,result_type,state",
    [
        (
            {
                "success": True,
                "execution_state": "queued",
                "execution": {"outcome": "unknown", "committed": False},
            },
            False,
            "complete",
            "unknown",
        ),
        (
            {"success": False, "execution_state": "queued", "task_id": "task-1"},
            False,
            "complete",
            "queued",
        ),
        (
            {"success": False, "execution_state": "queued", "execution": {"outcome": "unknown"}},
            False,
            "complete",
            "unknown",
        ),
        ({"success": False, "pending_approval": True}, False, "complete", "waiting_approval"),
        ({"success": False, "execution_state": "queued"}, True, "complete", "unknown"),
        ({"success": False, "execution_state": "queued"}, False, "input_required", "unknown"),
        ({"success": "false", "execution_state": "queued"}, False, "complete", "unknown"),
    ],
)
def test_real_sdk_business_waits_preserve_unknown_and_protocol_precedence(
    monkeypatch, business, protocol_error, result_type, state
):
    from mcp.types import CallToolResult, TextContent

    from app.infrastructure.mcp import client

    wire = CallToolResult(
        content=[TextContent(type="text", text="delivered")],
        isError=protocol_error,
        resultType=result_type,
        structuredContent=business,
    )
    monkeypatch.setattr(client, "_run_with_reconnect", lambda *_a, **_kw: wire)
    monkeypatch.setattr(mcp_registry, "mcp_enabled", lambda: True)
    monkeypatch.setattr(
        mcp_registry,
        "_snapshot",
        lambda: (
            {"mcp__demo": {"actions": {"write": {}}}},
            {"mcp__demo": mcp_config.McpServerConfig(name="demo", command="x")},
        ),
    )
    result = mcp_registry.call_mcp_tool("mcp__demo", "write", {})
    assert result["success"] is False and result["retryable"] is False
    assert result["structuredContent"] == business
    if state == "unknown":
        assert result["outcome"] == "unknown" and result["reconciliation_required"] is True
    else:
        assert result["execution_state"] == state and result.get("outcome") != "unknown"
        assert not result.get("reconciliation_required") and not result.get("error_code")


def test_real_mcp_stdio_preserves_structured_receipts_and_business_failure(tmp_path, monkeypatch):
    import sys

    from app.infrastructure.mcp import client

    server = tmp_path / "receipt_server.py"
    server.write_text(
        """import asyncio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

async def list_tools(context, params):
    return types.ListToolsResult(tools=[types.Tool(
        name="submit", description="Synthetic form submission",
        inputSchema={"type": "object", "required": ["commit"],
                     "properties": {"commit": {"type": "boolean"}}},
        annotations=types.ToolAnnotations(readOnlyHint=False)), types.Tool(
        name="inspect", inputSchema={"type": "object"},
        annotations=types.ToolAnnotations(readOnlyHint=True))])

async def call_tool(context, params):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="transport delivered")],
        isError=bool(params.arguments.get("protocol_error")),
        structuredContent={"success": params.arguments["commit"],
                           "receipt": {"form_id": "synthetic-form-1"},
                           **params.arguments.get("execution", {})})

async def main():
    server = Server("receipt-test", on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

asyncio.run(main())
""",
        encoding="utf-8",
    )
    config = mcp_config.McpServerConfig(
        name="receipt-test", command=sys.executable, args=(str(server),), timeout_seconds=10
    )
    tools = client.list_tools(config)
    assert len(tools) == 2 and tools[0].name == "submit"
    assert tools[0].input_schema["properties"]["commit"] == {"type": "boolean"}
    assert tools[0].read_only is False and tools[1].read_only is True
    for committed, protocol_error in ((False, False), (True, False), (True, True)):
        output = client.call_tool(
            config, "submit", {"commit": committed, "protocol_error": protocol_error}
        )
        assert output["success"] is (committed and not protocol_error), output
        assert output["structuredContent"] == {
            "success": committed,
            "receipt": {"form_id": "synthetic-form-1"},
        }
        if not committed or protocol_error:
            assert output["outcome"] == "unknown" and output["retryable"] is False
            assert output["error_code"] == (
                "mcp_tool_error" if protocol_error else "mcp_business_error"
            )
    monkeypatch.setattr(mcp_registry, "mcp_enabled", lambda: True)
    monkeypatch.setattr(mcp_registry, "load_server_configs", lambda: [config])
    for committed, state, uncertain, protocol_error in (
        (True, "unknown", False, False),
        (True, "queued", False, False),
        (False, "queued", False, False),
        (True, "queued", True, False),
        (False, "queued", True, False),
        (False, "queued", False, True),
    ):
        execution = {
            "execution_state": state,
            **({"execution": {"outcome": "unknown", "committed": False}} if uncertain else {}),
        }
        output = mcp_registry.call_mcp_tool(
            "mcp__receipt_test",
            "submit",
            {"commit": committed, "execution": execution, "protocol_error": protocol_error},
        )
        assert output["success"] is False and output["retryable"] is False
        assert output["structuredContent"]["success"] is committed
        assert output["structuredContent"]["execution_state"] == state
        if state == "unknown" or uncertain or protocol_error:
            assert output["outcome"] == "unknown" and output["reconciliation_required"] is True
        else:
            assert output["execution_state"] == "queued" and not output.get(
                "reconciliation_required"
            )


@pytest.mark.parametrize("capability", ["tools", "resources", "prompts"])
def test_real_sdk_discovery_registers_only_negotiated_operations(tmp_path, monkeypatch, capability):
    import sys

    server = tmp_path / "capability_server.py"
    server.write_text(
        """import asyncio, sys
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

async def tools(context, params):
    return types.ListToolsResult(tools=[types.Tool(name="inspect", input_schema={"type":"object"})])
async def resources(context, params):
    return types.ListResourcesResult(resources=[])
async def prompts(context, params):
    return types.ListPromptsResult(prompts=[])

async def main():
    kind = sys.argv[1]
    server = Server("capability-test", **{"on_list_" + kind: globals()[kind]})
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
asyncio.run(main())
""",
        encoding="utf-8",
    )
    config = mcp_config.McpServerConfig(
        name="capability-test",
        command=sys.executable,
        args=(str(server), capability),
        timeout_seconds=10,
    )
    monkeypatch.setattr(mcp_registry, "mcp_enabled", lambda: True)
    monkeypatch.setattr(mcp_registry, "load_server_configs", lambda: [config])
    catalog = mcp_registry.merge_mcp_tools({})
    actions = set(catalog["mcp__capability_test"]["actions"])
    expected = {
        "tools": {"inspect"},
        "resources": {"mcp_list_resources", "mcp_read_resource"},
        "prompts": {"mcp_list_prompts", "mcp_get_prompt"},
    }
    assert actions == expected[capability]
    if capability != "tools":
        result = mcp_registry.call_mcp_tool("mcp__capability_test", f"mcp_list_{capability}", {})
        assert result["success"] is True
