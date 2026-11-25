"""Stateful browser contracts against a real official-SDK stdio server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
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

@server.tool()
async def receipt_contract(case: str) -> CallToolResult:
    with log.open("a") as stream:
        stream.write("receipt:" + case + "\\n")
    payloads = {
        "business_error": {"success": False, "reason": "declined"},
        "invalid_success": {"success": "false"},
        "created_task": {"accepted": True},
        "complete": {"success": True},
        "empty": None,
    }
    return CallToolResult(
        content=[],
        structured_content=payloads[case],
        result_type="complete",
    )

@server.resource("fixture://result")
def receipt_document() -> str:
    return '{"success": false, "accepted": true}'

@server.prompt()
def receipt_prompt() -> str:
    return '{"success": false, "accepted": true}'

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


@pytest.mark.parametrize("session_mode", ["stateless", "persistent"])
def test_official_sdk_result_contract_does_not_promote_partial_receipts(server, session_mode):
    config, log = server
    config = replace(config, session_mode=session_mode)
    first = _call(config, "browser_snapshot")
    generation = first.get("session_id")
    for case, expected_error in (
        ("business_error", "mcp_business_error"),
        ("invalid_success", "mcp_result_invalid"),
        ("created_task", None),
        ("complete", None),
        ("empty", None),
    ):
        result = _call(config, "receipt_contract", {"case": case}, expected_session_id=generation)
        assert result["success"] is (expected_error is None), result
        assert result.get("error_code") == expected_error
        assert result.get("session_id") == generation
        assert result["content_blocks"] == []
        if expected_error:
            assert result["outcome"] == "unknown" and result["retryable"] is False
            assert result["reconciliation_required"] is True
        if case == "business_error":
            assert result["structured_content"]["success"] is False
        assert log.read_text().splitlines().count(f"receipt:{case}") == 1
    after = _call(config, "browser_snapshot", expected_session_id=generation)
    assert after["success"] is True and after.get("session_id") == generation


@pytest.mark.parametrize("session_mode", ["stateless", "persistent"])
def test_official_sdk_resource_and_prompt_documents_are_not_business_receipts(server, session_mode):
    config, _log = server
    config = replace(config, session_mode=session_mode)
    generation = _call(config, "browser_snapshot").get("session_id")
    for action, params in (
        ("mcp_list_resources", {}),
        ("mcp_read_resource", {"uri": "fixture://result"}),
        ("mcp_list_prompts", {}),
        ("mcp_get_prompt", {"name": "receipt_prompt"}),
    ):
        result = _call(config, action, params, expected_session_id=generation)
        assert result["success"] is True, result
        assert result.get("session_id") == generation
        if action in {"mcp_read_resource", "mcp_get_prompt"}:
            assert json.loads(result["content"]) == {"success": False, "accepted": True}


@pytest.mark.parametrize(
    "raw",
    [
        None,
        SimpleNamespace(accepted=True),
        SimpleNamespace(content=None),
        SimpleNamespace(content=[], structuredContent={"success": 0}),
        SimpleNamespace(content=[], structuredContent={"success": None}),
    ],
    ids=["missing", "accepted-only", "missing-content", "numeric-success", "null-success"],
)
def test_missing_mcp_result_shape_is_not_success(monkeypatch, raw):
    async def connection(config, operation):
        return raw

    monkeypatch.setattr(client, "_with_session", connection)
    result = client.call_tool(McpServerConfig(name="contract", command="unused"), "write", {})
    assert result["success"] is False
    assert result["error_code"] == "mcp_result_invalid"
    assert result["outcome"] == "unknown" and result["retryable"] is False


@pytest.mark.parametrize("wire_alias", [False, True])
@pytest.mark.parametrize("action", ["write", "mcp_read_resource"])
def test_noncomplete_sdk_results_are_not_completion(monkeypatch, action, wire_alias):
    from mcp.types import CallToolResult, ReadResourceResult

    # The SDK's legacy 2025-11-25 stdio wire omits resultType. Check the
    # normalized SDK result and legacy attribute adapter without inventing a
    # completion rule for arbitrary {"accepted": true} business payloads.
    raw = (
        ReadResourceResult(contents=[], result_type="accepted")
        if action == "mcp_read_resource"
        else CallToolResult(
            content=[], structured_content={"accepted": True}, result_type="accepted"
        )
    )
    if wire_alias:
        raw = SimpleNamespace(**raw.model_dump(mode="json", by_alias=True))
    calls = []

    async def connection(config, operation):
        calls.append(action)
        return raw

    monkeypatch.setattr(client, "_with_session", connection)
    result = client.call_tool(McpServerConfig(name="contract", command="unused"), action, {})
    assert result["success"] is False and result["error_code"] == "mcp_result_incomplete"
    assert result["result_type"] == "accepted" and calls == [action]
    if action == "write":
        assert result["structured_content"] == {"accepted": True}
        assert result["outcome"] == "unknown" and result["retryable"] is False


@pytest.mark.parametrize("action", client.RESOURCE_ACTIONS)
def test_empty_standard_resource_and_prompt_results_remain_valid(monkeypatch, action):
    from mcp.types import (
        GetPromptResult,
        ListPromptsResult,
        ListResourcesResult,
        ReadResourceResult,
    )

    result = {
        "mcp_list_resources": ListResourcesResult(resources=[]),
        "mcp_read_resource": ReadResourceResult(contents=[]),
        "mcp_list_prompts": ListPromptsResult(prompts=[]),
        "mcp_get_prompt": GetPromptResult(messages=[]),
    }[action]

    async def connection(config, operation):
        return result

    monkeypatch.setattr(client, "_with_session", connection)
    actual = client.call_tool(McpServerConfig(name="contract", command="unused"), action, {})
    assert actual["success"] is True and actual["content"] == ""


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


@pytest.mark.parametrize("phase", ["connection", "operation"])
def test_persistent_call_keeps_parent_deadline_and_unknown_write_tombstone(monkeypatch, phase):
    from app.application.tool_execution_deadline import invocation_deadline

    entered, exited, effects = [], [], []

    async def connection(config, operation):
        entered.append(asyncio.current_task())

        class Session:
            async def call_tool(self, name, arguments):
                if name == "change":
                    await asyncio.sleep(0.25)
                    effects.append("late write")
                return SimpleNamespace(content=[], isError=False)

        try:
            if phase == "connection":
                await asyncio.sleep(0.25)
            return await operation(Session())
        finally:
            exited.append(asyncio.current_task())

    monkeypatch.setattr(client, "_with_session", connection)
    config = McpServerConfig(
        name="inherited-deadline",
        command="unused",
        session_mode="persistent",
        session_start_tools=("start",),
        timeout_seconds=2,
    )
    if phase == "operation":
        assert _call(config, "start")["success"] is True
    with invocation_deadline(time.monotonic() + 0.03):
        result = _call(config, "start" if phase == "connection" else "change")
    assert result["success"] is False and result["error_code"] == "mcp_session_lost"
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True
    assert _call(config, "start", retry_safe=True)["error_code"] == "mcp_session_lost"
    client.close_all_sessions()
    assert len(entered) == 1 and entered == exited and effects == []


def test_persistent_queue_wait_cannot_renew_the_parent_deadline(monkeypatch):
    from app.application.tool_execution_deadline import invocation_deadline

    started, calls = threading.Event(), []

    async def connection(config, operation):
        class Session:
            async def call_tool(self, name, arguments):
                calls.append(name)
                if name == "hold":
                    started.set()
                    await asyncio.Event().wait()
                return SimpleNamespace(content=[], isError=False)

        return await operation(Session())

    monkeypatch.setattr(client, "_with_session", connection)
    config = McpServerConfig(
        name="queued-deadline",
        command="unused",
        session_mode="persistent",
        session_start_tools=("hold",),
        timeout_seconds=1,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(_call, config, "hold")
        assert started.wait(timeout=1)
        before = time.monotonic()
        with invocation_deadline(before + 0.03):
            result = _call(config, "queued_write")
        assert time.monotonic() - before < 0.5
        assert result["error_code"] == "mcp_session_lost"
        assert first.result(timeout=1)["error_code"] == "mcp_session_lost"
    assert calls == ["hold"]


def test_expired_parent_deadline_never_starts_a_persistent_session(monkeypatch):
    from app.application.tool_execution_deadline import invocation_deadline

    entered = []

    async def connection(config, operation):
        entered.append(config.name)

    monkeypatch.setattr(client, "_with_session", connection)
    config = McpServerConfig(
        name="expired-before-start",
        command="unused",
        session_mode="persistent",
        session_start_tools=("start",),
    )
    with invocation_deadline(time.monotonic() - 1):
        result = _call(config, "start")
    assert result["error_code"] == "mcp_session_deadline_exceeded"
    assert result["outcome"] == "not_started" and not result["reconciliation_required"]
    assert entered == []


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX asyncio subprocess transport")
def test_release_during_sdk_shutdown_finishes_transport_cleanup(server, monkeypatch):
    import anyio
    from mcp.client import stdio

    config, _log = server
    config = replace(config, session_idle_seconds=0.02)
    closing_stdout = threading.Event()
    interrupted = threading.Event()
    processes = []
    spawn, close_pipe = stdio._create_platform_compatible_process, stdio._close_pipe

    async def observe_process(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        return process

    async def observe_close(stream):
        await close_pipe(stream)
        if processes and stream is processes[0].stdout:
            closing_stdout.set()
            # Expose the real SDK shielded shutdown race without replacing it.
            try:
                await anyio.sleep(0.1)
            except asyncio.CancelledError:
                interrupted.set()
                raise

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", observe_process)
    monkeypatch.setattr(stdio, "_close_pipe", observe_close)
    try:
        pid = _state(_call(config, "browser_snapshot"))["pid"]
        assert closing_stdout.wait(timeout=5)
        assert client.close_scope("tenant1:user1:run1") == 1
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not interrupted.is_set()
        assert processes[0]._process._transport.is_closing()
    finally:
        client.close_all_sessions()
        # Keep a failed assertion from leaking the fixture's retained transport.
        for process in processes:
            process._process._transport.close()


def test_stateless_deadline_does_not_interrupt_sdk_shielded_cleanup():
    import anyio

    finished, cleaned = threading.Event(), threading.Event()

    async def shutdown():
        try:
            with anyio.CancelScope(shield=True):
                await anyio.sleep(0.1)
                cleaned.set()
        finally:
            finished.set()

    with pytest.raises(client.McpClientError):
        client._sync(shutdown, 0.02)
    assert finished.wait(timeout=2)
    assert cleaned.is_set()


def test_stateless_timeout_stops_write_without_replay_and_finishes_cleanup(monkeypatch):
    import anyio

    dispatched = []
    stopped, cleaned, finished = threading.Event(), threading.Event(), threading.Event()

    async def write(tool, arguments):
        dispatched.append((tool, arguments))
        try:
            await anyio.sleep_forever()
        finally:
            stopped.set()

    async def connection(_config, action):
        try:
            return await action(SimpleNamespace(call_tool=write))
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    await anyio.sleep(0.05)
                    cleaned.set()
            finally:
                finished.set()

    monkeypatch.setattr(client, "_with_session", connection)
    result = client.call_tool(
        McpServerConfig(name="bounded-write", command="unused", timeout_seconds=0.1),
        "write",
        {"receipt_id": "original-effect"},
    )
    assert result["success"] is False and result["error_code"] == "mcp_call_failed"
    assert result["outcome"] == "unknown"
    assert result["reconciliation_required"] is True and result["retryable"] is False
    assert finished.wait(timeout=2)
    assert stopped.is_set() and cleaned.is_set()
    assert dispatched == [("write", {"receipt_id": "original-effect"})]
