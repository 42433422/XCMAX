"""Stateful browser contracts against a real official-SDK stdio server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.infrastructure.mcp import client
from app.infrastructure.mcp.config import McpServerConfig, _server_config

_SERVER = """
import asyncio
import os
import sys
from pathlib import Path
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

log = Path(sys.argv[1])
with log.open("a") as stream:
    stream.write("opened\\n")
state = {"url": "about:blank", "clicks": 0, "pid": os.getpid()}
server = MCPServer("stateful-browser-contract", log_level="ERROR")

@server.tool()
async def browser_navigate(url: str) -> dict:
    state["url"] = url
    return dict(state)

@server.tool(annotations=ToolAnnotations(read_only_hint=True))
async def browser_snapshot() -> dict:
    return dict(state)

@server.tool()
async def browser_click(ref: str, disconnect: bool = False) -> dict:
    before = state["clicks"]
    with log.open("a") as stream:
        stream.write("clicked\\n")
    if disconnect:
        os._exit(0)
    await asyncio.sleep(0.02)
    state["clicks"] = before + 1
    return dict(state)

@server.tool()
async def browser_evidence() -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text="snapshot"),
                 ImageContent(type="image", data="c3ludGhldGlj", mimeType="image/png")],
        structuredContent={"url": state["url"], "verified": True},
    )

@server.tool()
async def browser_stale_ref() -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text="stale ref")])

server.run(transport="stdio")
"""


@pytest.fixture(autouse=True)
def _sessions():
    client.close_all_sessions()
    yield
    client.close_all_sessions()


@pytest.fixture
def server(tmp_path):
    pytest.importorskip("mcp.server.mcpserver")
    script = tmp_path / "mcp_server.py"
    script.write_text(_SERVER, encoding="utf-8")
    log = tmp_path / "events.log"
    return (
        McpServerConfig(
            name="browser-contract",
            command=sys.executable,
            args=(str(script), str(log)),
            timeout_seconds=10,
            session_mode="persistent",
            session_start_tools=("browser_navigate", "browser_snapshot"),
            max_sessions=2,
            browser=True,
        ),
        log,
    )


def _call(config, action, params=None, scope="tenant1:user1:run1", **kwargs):
    return client.call_tool(config, action, params or {}, session_scope=scope, **kwargs)


def _state(result):
    assert result["success"] is True, result
    return result.get("structured_content") or json.loads(result["content"])


def test_official_sdk_discovery_keeps_full_schema_and_readonly_annotation(server):
    config, _log = server
    infos = {info.name: info for info in client.list_tools(config)}
    assert infos["browser_snapshot"].read_only is True
    click_schema = infos["browser_click"].input_schema
    assert click_schema["required"] == ["ref"]
    assert click_schema["properties"]["ref"]["type"] == "string"
    assert click_schema["properties"]["disconnect"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_official_sdk_pagination_attributes_are_consumed():
    from mcp.types import ListToolsResult, Tool

    class Session:
        async def list_tools(self, params=None):
            return ListToolsResult(
                tools=[Tool(name="second" if params else "first", input_schema={"type": "object"})],
                next_cursor=None if params else "page-2",
            )

    assert [tool.name for tool in await client._list_all_tools(Session())] == ["first", "second"]


def test_official_sdk_keeps_page_and_isolates_authenticated_run_scopes(server):
    config, log = server
    first = _call(config, "browser_navigate", {"url": "https://example.test/one"})
    second = _call(config, "browser_snapshot", scope="tenant2:user2:run1")
    after = _call(config, "browser_click", {"ref": "e1"}, expected_session_id=first["session_id"])
    assert _state(first)["url"] == _state(after)["url"] == "https://example.test/one"
    assert _state(after)["clicks"] == 1
    assert _state(second)["url"] == "about:blank"
    assert first["session_id"] != second["session_id"]
    assert first["session_id"] == after["session_id"]
    assert log.read_text().splitlines().count("opened") == 2


def test_official_sdk_serializes_concurrent_actions_without_lost_page_updates(server):
    config, _log = server
    first = _call(config, "browser_snapshot")
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(
                lambda index: _call(
                    config,
                    "browser_click",
                    {"ref": f"e{index}"},
                    expected_session_id=first["session_id"],
                ),
                range(8),
            )
        )
    assert sorted(_state(result)["clicks"] for result in results) == list(range(1, 9))


def test_official_sdk_lost_write_and_followup_read_are_never_replayed(server):
    config, log = server
    first = _call(config, "browser_navigate", {"url": "https://example.test"})
    failed = _call(config, "browser_click", {"ref": "pay", "disconnect": True})
    after = _call(config, "browser_snapshot", retry_safe=True)
    for result in (failed, after):
        assert result["error_code"] == "mcp_session_lost"
        assert result["outcome"] == "unknown" and result["retryable"] is False
        assert result["session_id"] == first["session_id"]
    assert log.read_text().splitlines() == ["opened", "clicked"]


def test_generation_receipt_detects_lost_worker_without_reopening_browser(server):
    config, log = server
    first = _call(config, "browser_snapshot")
    assert client.close_scope("tenant1:user1:run1") == 1
    stale = _call(config, "browser_snapshot", expected_session_id=first["session_id"])
    assert stale["error_code"] == "mcp_session_lost"
    assert log.read_text().splitlines() == ["opened"]
    fresh = _call(config, "browser_snapshot", scope="tenant1:user1:run2")
    assert fresh["session_id"] != first["session_id"]


def test_wrong_generation_does_not_close_the_live_session(server):
    config, _log = server
    first = _call(config, "browser_navigate", {"url": "https://example.test"})
    stale = _call(config, "browser_click", {"ref": "e1"}, expected_session_id="old-worker")
    assert stale["error_code"] == "mcp_session_lost"
    current = _call(config, "browser_snapshot", expected_session_id=first["session_id"])
    assert _state(current)["clicks"] == 0
    assert _state(current)["url"] == "https://example.test"


def test_capacity_never_evicts_another_run_and_release_reclaims_capacity(server):
    config, log = server
    _call(config, "browser_snapshot", scope="a")
    _call(config, "browser_snapshot", scope="b")
    blocked = _call(config, "browser_snapshot", scope="c")
    assert blocked["error_code"] == "mcp_session_limit"
    assert log.read_text().splitlines() == ["opened", "opened"]
    assert client.close_session(config, "a") == 1
    assert _call(config, "browser_snapshot", scope="c")["success"] is True


def test_missing_scope_and_nonstarter_never_launch_a_process(server):
    config, log = server
    assert (
        client.call_tool(config, "browser_snapshot", {})["error_code"]
        == "mcp_session_scope_required"
    )
    assert _call(config, "browser_click", {"ref": "e1"})["error_code"] == "mcp_session_not_started"
    assert not log.exists()


def test_full_evidence_and_recoverable_tool_error_keep_session_identity(server):
    config, _log = server
    first = _call(config, "browser_navigate", {"url": "https://example.test"})
    error = _call(config, "browser_stale_ref")
    assert error["error_code"] == "mcp_tool_error" and error["session_id"] == first["session_id"]
    evidence = _call(config, "browser_evidence")
    assert evidence["session_id"] == first["session_id"]
    assert evidence["structured_content"] == {
        "url": "https://example.test",
        "verified": True,
    }
    assert evidence["content_blocks"][1]["type"] == "image"
    assert evidence["content_blocks"][1]["data"] == "c3ludGhldGlj"


def test_configuration_rotation_invalidates_session_instead_of_reusing_credentials(
    server,
):
    config, log = server
    first = _call(config, "browser_snapshot")
    changed = replace(config, env={"ROTATED_AUTH": "synthetic"})
    result = _call(changed, "browser_snapshot", expected_session_id=first["session_id"])
    assert result["error_code"] == "mcp_session_lost"
    assert log.read_text().splitlines() == ["opened"]


@pytest.mark.parametrize("expiry", ["idle", "operation"])
def test_timeout_closes_context_on_its_own_task_and_never_reconnects(monkeypatch, expiry):
    entered, exited = [], []

    async def connection(config, operation):
        owner = asyncio.current_task()
        entered.append(owner)

        class Session:
            async def call_tool(self, name, arguments):
                assert asyncio.current_task() is owner
                if name == "hang":
                    await asyncio.Event().wait()
                return SimpleNamespace(content=[], isError=False)

        try:
            return await operation(Session())
        finally:
            exited.append(asyncio.current_task())

    monkeypatch.setattr(client, "_with_session", connection)
    config = McpServerConfig(
        name="timeout",
        command="unused",
        session_mode="persistent",
        session_start_tools=("start",),
        timeout_seconds=0.1,
        session_idle_seconds=0.05,
    )
    first = _call(config, "start")
    assert first["success"] is True
    if expiry == "idle":
        deadline = time.monotonic() + 2
        while not exited and time.monotonic() < deadline:
            time.sleep(0.005)
    else:
        assert _call(config, "hang")["error_code"] == "mcp_session_lost"
    assert _call(config, "start", retry_safe=True)["error_code"] == "mcp_session_lost"
    client.close_all_sessions()
    assert len(entered) == 1 and entered == exited


def test_session_configuration_is_bounded_explicit_and_default_is_stateless():
    config = _server_config("old", {"command": "x"})
    assert config is not None and config.session_mode == "stateless"
    config = _server_config(
        "browser",
        {
            "command": "x",
            "session_mode": "persistent",
            "browser": True,
            "session_idle_seconds": 99999,
            "max_sessions": 999,
            "session_start_tools": ["browser_navigate", None],
        },
    )
    assert config is not None and config.browser is True
    assert config.session_idle_seconds == 3600 and config.max_sessions == 32
    assert config.session_start_tools == ("browser_navigate",)
    assert _server_config("bad", {"command": "x", "session_mode": "implicit"}) is None
    assert _server_config("bad", {"command": "x", "session_idle_seconds": float("nan")}) is None
    assert _server_config("bad", {"command": "x", "timeout_seconds": float("inf")}) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-liveness check")
def test_explicit_release_reaps_the_real_stdio_process(server):
    config, _log = server
    pid = _state(_call(config, "browser_snapshot"))["pid"]
    os.kill(pid, 0)
    client.close_scope("tenant1:user1:run1")
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
