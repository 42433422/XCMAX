"""外部 MCP 工具接入：配置、注册表合并、路由与并行开关。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.application.tools.mcp import registry as mcp_registry
from app.infrastructure.mcp import config as mcp_config
from app.infrastructure.mcp.client import McpToolInfo


@pytest.fixture(autouse=True)
def _reset_cache():
    mcp_registry.reset_mcp_cache_for_tests()
    yield
    mcp_registry.reset_mcp_cache_for_tests()


def _config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict) -> Path:
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("XCAGI_MCP_SERVERS_FILE", str(path))
    monkeypatch.delenv("XCAGI_MCP_ENABLED", raising=False)
    return path


def test_load_server_configs_reads_stdio_and_http(tmp_path, monkeypatch) -> None:
    _config_file(
        tmp_path,
        monkeypatch,
        {
            "servers": {
                "local": {"transport": "stdio", "command": "npx", "args": ["-y", "srv"]},
                "remote": {"transport": "http", "url": "https://example.com/mcp"},
                "broken": {"transport": "stdio"},
            }
        },
    )
    configs = {item.name: item for item in mcp_config.load_server_configs()}
    assert set(configs) == {"local", "remote"}
    assert configs["local"].command == "npx"
    assert configs["local"].args == ("-y", "srv")
    assert configs["remote"].url.startswith("https://")


def test_disabled_env_skips_config(tmp_path, monkeypatch) -> None:
    _config_file(tmp_path, monkeypatch, {"servers": {"local": {"command": "x"}}})
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "0")
    assert mcp_config.load_server_configs() == []


def test_merge_registers_read_and_write_actions(tmp_path, monkeypatch) -> None:
    _config_file(tmp_path, monkeypatch, {"servers": {"demo": {"command": "x"}}})
    monkeypatch.setattr(mcp_config, "load_server_configs", lambda *a, **k: [])
    monkeypatch.setattr(
        mcp_registry,
        "load_server_configs",
        lambda *a, **k: [
            mcp_config.McpServerConfig(name="demo", command="x", read_only_tools=("search_notes",))
        ],
    )
    monkeypatch.setattr(
        mcp_registry,
        "list_tools",
        lambda config: [
            McpToolInfo(
                name="search_notes",
                description="搜索笔记",
                input_schema={"type": "object", "required": ["query"]},
                read_only=True,
            ),
            McpToolInfo(
                name="write_note",
                description="写入笔记",
                input_schema={"type": "object", "required": []},
                read_only=False,
            ),
        ],
    )
    registered: dict = {}

    class Guard:
        def register_actions(self, tool_id, *, description="", actions=None):
            registered[tool_id] = {"description": description, "actions": actions}

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())

    merged = mcp_registry.merge_mcp_tools({"customers": {"actions": {}}})
    tool_id = mcp_registry.tool_id_for("demo")
    assert tool_id == "mcp__demo"
    assert tool_id in merged
    actions = merged[tool_id]["actions"]
    assert actions["search_notes"]["risk"] == "low"
    assert actions["search_notes"]["idempotent"] is True
    assert actions["search_notes"]["read_only"] is True
    assert actions["search_notes"]["required_params"] == ["query"]
    assert actions["write_note"]["risk"] == "high"
    assert actions["write_note"]["read_only"] is False
    assert actions["write_note"]["requires_write_approval"] is True
    assert registered[tool_id]["actions"]["write_note"]["risk"] == "high"


def test_merge_without_config_keeps_registry(monkeypatch) -> None:
    monkeypatch.setattr(mcp_registry, "load_server_configs", lambda *a, **k: [])
    original = {"customers": {"actions": {}}}
    assert mcp_registry.merge_mcp_tools(original) == original


def test_call_mcp_tool_strips_internal_params(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_registry,
        "load_server_configs",
        lambda *a, **k: [mcp_config.McpServerConfig(name="demo", command="x")],
    )
    monkeypatch.setattr(
        mcp_registry,
        "list_tools",
        lambda config: [
            McpToolInfo(name="search_notes", description="", input_schema={}, read_only=True)
        ],
    )
    captured: dict = {}

    def fake_call(config, tool_name, arguments, *, retry_safe=False):
        captured.update(server=config.name, tool=tool_name, arguments=arguments)
        return {"success": True, "content": "ok"}

    monkeypatch.setattr(mcp_registry, "call_tool", fake_call)
    mcp_registry.merge_mcp_tools({})
    result = mcp_registry.call_mcp_tool(
        "mcp__demo", "search_notes", {"query": "门", "_runtime_context": {"secret": 1}}
    )
    assert result["success"] is True
    assert captured == {"server": "demo", "tool": "search_notes", "arguments": {"query": "门"}}


def test_router_dispatches_mcp_prefix(monkeypatch) -> None:
    from app.domain.shared_services.tools_workflow_dispatch import _REGISTERED_WORKFLOW_ROUTERS

    monkeypatch.setattr(
        "app.application.tools.mcp.registry.call_mcp_tool",
        lambda tool_id, action, params, *, runtime_context=None: {
            "success": True,
            "tool_id": tool_id,
            "action": action,
            "params": params,
        },
    )
    router = _REGISTERED_WORKFLOW_ROUTERS.get("mcp__demo")
    assert router is not None
    result = router("search_notes", {"query": "门"}, {}, "normal", "")
    assert result == {
        "success": True,
        "tool_id": "mcp__demo",
        "action": "search_notes",
        "params": {"query": "门"},
    }


def test_workflow_registry_merges_external_tools(monkeypatch) -> None:
    from app.services.tools_execution import registry as tool_registry

    monkeypatch.setattr(
        "app.application.tools.mcp.registry.merge_mcp_tools",
        lambda registry: {**registry, "mcp__demo": {"actions": {"search": {}}}},
    )
    merged = tool_registry.get_workflow_tool_registry()
    assert "mcp__demo" in merged


@pytest.mark.parametrize(
    "value,expected",
    [("", True), ("1", True), ("0", False), ("off", False), ("false", False)],
)
def test_plan_parallel_switch(monkeypatch, value, expected) -> None:
    from app.application.agent_orchestrator.compensation import plan_parallel_enabled

    monkeypatch.setenv("XCAGI_PLAN_PARALLEL", value)
    assert plan_parallel_enabled() is expected


@pytest.mark.asyncio
async def test_list_all_tools_follows_pagination() -> None:
    from mcp.types import ListToolsResult, Tool

    from app.infrastructure.mcp.client import _list_all_tools

    class Session:
        def __init__(self) -> None:
            self.cursors: list[object] = []

        async def list_tools(self, params=None):
            self.cursors.append(params)
            if params is None:
                return ListToolsResult(
                    tools=[Tool(name="first", inputSchema={})], nextCursor="page-2"
                )
            return ListToolsResult(tools=[Tool(name="second", inputSchema={})])

    session = Session()
    tools = await _list_all_tools(session)
    assert [tool.name for tool in tools] == ["first", "second"]
    assert len(session.cursors) == 2
    assert session.cursors[1].cursor == "page-2"


def test_resource_actions_are_registered(monkeypatch) -> None:
    from app.infrastructure.mcp.config import McpServerConfig

    monkeypatch.setattr(
        mcp_registry,
        "load_server_configs",
        lambda *a, **k: [McpServerConfig(name="demo", command="x")],
    )
    monkeypatch.setattr(
        mcp_registry,
        "list_tools",
        lambda config: [
            McpToolInfo(name="search", description="", input_schema={}, read_only=True)
        ],
    )
    monkeypatch.setattr(
        "app.domain.autonomy.autonomy_guard.get_autonomy_guard",
        lambda: type("G", (), {"register_actions": lambda *a, **k: None})(),
    )
    merged = mcp_registry.merge_mcp_tools({})
    actions = merged["mcp__demo"]["actions"]
    assert actions["mcp_list_resources"]["risk"] == "low"
    assert actions["mcp_read_resource"]["required_params"] == ["uri"]
    assert actions["mcp_get_prompt"]["required_params"] == ["name"]


@pytest.mark.asyncio
async def test_oauth_header_is_cached(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.infrastructure.mcp import client as mcp_client
    from app.infrastructure.mcp.config import McpServerConfig

    calls: list[dict] = []

    async def fake_post(self, url, data=None, timeout=None):
        calls.append({"url": url, "data": data})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": "tok", "expires_in": 3600},
        )

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    mcp_client._TOKEN_CACHE.clear()
    config = McpServerConfig(
        name="remote",
        transport="http",
        url="https://example.com/mcp",
        auth={
            "token_url": "https://example.com/token",
            "client_id": "cid",
            "client_secret": "secret",
        },
    )

    first = await mcp_client._oauth_header(config)
    second = await mcp_client._oauth_header(config)

    assert first == {"Authorization": "Bearer tok"}
    assert second == first
    assert len(calls) == 1
    assert calls[0]["data"]["grant_type"] == "client_credentials"


def test_synthetic_resource_action_dispatches_to_session(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.infrastructure.mcp import client as mcp_client
    from app.infrastructure.mcp.config import McpServerConfig

    class Session:
        async def read_resource(self, uri):
            return SimpleNamespace(contents=[SimpleNamespace(text=f"content:{uri}")])

    async def fake_with_session(config, action):
        return await action(Session())

    monkeypatch.setattr(mcp_client, "_with_session", fake_with_session)
    result = mcp_client.call_tool(
        McpServerConfig(name="demo", command="x"), "mcp_read_resource", {"uri": "file://a"}
    )

    assert result["success"] is True
    assert result["content"] == "content:file://a"
    assert result["tool"] == "mcp_read_resource"


def test_reader_gate_caps_concurrency(monkeypatch) -> None:
    from app.infrastructure.workflow.langgraph_runtime import _ReadersWriterGate

    monkeypatch.setenv("XCAGI_PLAN_PARALLEL_MAX", "1")
    gate = _ReadersWriterGate(parallel=True)
    assert gate._max_readers == 1


@pytest.mark.parametrize(
    "name,hint", [("get_and_delete", False), ("list_secrets", True), ("query", True)]
)
def test_remote_name_and_hint_alone_never_grant_readonly_authority(name, hint):
    info = McpToolInfo(name=name, description="", input_schema={}, read_only=hint)
    spec = mcp_registry._action_spec(info, mcp_config.McpServerConfig(name="demo", command="x"))
    assert spec["risk"] == "high" and spec["idempotent"] is False
    assert spec["read_only"] is False
    assert spec["requires_write_approval"] is True


def test_local_allowlist_does_not_override_explicit_remote_write_declaration():
    info = McpToolInfo(name="read", description="", input_schema={}, read_only=False)
    config = mcp_config.McpServerConfig(name="demo", command="x", read_only_tools=("read",))
    assert mcp_registry._action_spec(info, config)["requires_write_approval"] is True


def test_slug_collision_fails_closed_without_replacing_internal_tools(monkeypatch):
    configs = [mcp_config.McpServerConfig(name=n, command="x") for n in ("a-b", "a_b")]
    monkeypatch.setattr(mcp_registry, "load_server_configs", lambda: configs)
    monkeypatch.setattr(
        mcp_registry,
        "list_tools",
        lambda _: [McpToolInfo(name="read", description="", input_schema={}, read_only=True)],
    )
    original = {"customers": {"actions": {"query": {}}}}
    assert mcp_registry.merge_mcp_tools(original) == original
    assert mcp_registry._CACHE["servers"] == {}


def test_disabled_or_unregistered_calls_never_reach_transport(monkeypatch):
    calls = []
    config = mcp_config.McpServerConfig(name="demo", command="x")
    monkeypatch.setattr(
        mcp_registry,
        "_snapshot",
        lambda: ({"mcp__demo": {"actions": {"known": {}}}}, {"mcp__demo": config}),
    )
    monkeypatch.setattr(mcp_registry, "call_tool", lambda *a: calls.append(a))
    assert mcp_registry.call_mcp_tool("mcp__demo", "unknown")["success"] is False
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "0")
    assert mcp_registry.call_mcp_tool("mcp__demo", "known")["success"] is False
    assert calls == []


@pytest.mark.parametrize("safe", [False, True])
def test_unknown_transport_outcome_cannot_reconnect_even_for_trusted_reads(monkeypatch, safe):
    from app.infrastructure.mcp import client

    calls = []

    def fail(factory, timeout):
        calls.append("possibly committed")
        raise httpx.ReadTimeout("connection dropped after send")

    monkeypatch.setattr(client, "_sync", fail)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    result = client.call_tool(
        mcp_config.McpServerConfig(name="demo", command="x"), "write", {}, retry_safe=safe
    )
    assert len(calls) == 1 and result["success"] is False
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True


def test_mcp_reconnect_spends_one_inherited_deadline(monkeypatch):
    from types import SimpleNamespace

    from app.application.tool_execution_deadline import invocation_deadline
    from app.infrastructure.mcp import client

    calls, clock = [], [100.0]
    monkeypatch.setattr(
        client,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda _: None),
    )
    monkeypatch.setattr(
        "app.application.tool_execution_deadline.time",
        SimpleNamespace(monotonic=lambda: clock[0]),
    )

    def once(factory, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            clock[0] += 0.4
            raise httpx.ConnectError("connection unavailable before send")
        return "same operation completed"

    monkeypatch.setattr(client, "_sync", once)
    with invocation_deadline(101.0):
        assert (
            client._run_with_reconnect(lambda: None, 30, retry_safe=True)
            == "same operation completed"
        )
    assert calls == pytest.approx([1.0, 0.6])


def test_mcp_read_retry_preserves_original_nested_arguments(monkeypatch):
    import copy
    from types import SimpleNamespace

    from app.infrastructure.mcp import client

    calls = []
    original = {"filter": {"query": "original"}}

    class Session:
        async def call_tool(self, name, arguments):
            calls.append(copy.deepcopy(arguments))
            arguments["filter"]["query"] = "changed by transport"
            if len(calls) == 1:
                raise httpx.ConnectError("connection unavailable before send")
            return SimpleNamespace(isError=False, structuredContent={"items": []}, content=[])

    async def with_session(config, action):
        return await action(Session())

    monkeypatch.setattr(client, "_with_session", with_session)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    result = client.call_tool(
        mcp_config.McpServerConfig(name="demo", command="x"), "read", original, retry_safe=True
    )
    assert result["success"] is True
    assert original == {"filter": {"query": "original"}}
    assert calls == [original, original]


def test_mcp_cannot_reconnect_after_total_budget_is_exhausted(monkeypatch):
    from types import SimpleNamespace

    from app.infrastructure.mcp import client

    calls, clock = [], [100.0]
    monkeypatch.setattr(
        client,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda _: None),
    )

    def once(factory, timeout):
        calls.append(timeout)
        clock[0] += 5
        raise httpx.ConnectError("connection unavailable before send")

    monkeypatch.setattr(client, "_sync", once)
    with pytest.raises(client.McpClientError, match="预算"):
        client._run_with_reconnect(lambda: None, 1, retry_safe=True)
    assert len(calls) == 1


def test_mcp_thread_retains_trusted_invocation_context():
    import time
    from contextvars import ContextVar

    from app.application.tool_execution_deadline import _DEADLINE, invocation_deadline
    from app.infrastructure.mcp import client

    tenant = ContextVar("mcp_test_tenant", default=None)
    token = tenant.set("original-tenant")

    async def observe():
        return tenant.get(), _DEADLINE.get().deadline

    try:
        with invocation_deadline(time.monotonic() + 1) as budget:
            assert client._sync(observe, 30) == ("original-tenant", budget.deadline)
    finally:
        tenant.reset(token)


def test_real_mcp_timeout_cancels_the_original_call_without_reconnect(monkeypatch):
    import asyncio
    import threading
    import time

    from app.infrastructure.mcp import client

    attempts, ended = [], threading.Event()

    async def with_session(config, action):
        attempts.append(1)
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    monkeypatch.setattr(client, "_with_session", with_session)
    started = time.monotonic()
    result = client.call_tool(
        mcp_config.McpServerConfig(name="demo", command="x", timeout_seconds=0.05),
        "read",
        {},
        retry_safe=True,
    )
    assert attempts == [1] and ended.wait(0.5)
    assert time.monotonic() - started < 0.75
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("denied"),
        ValueError("invalid arguments"),
        FileNotFoundError("missing server"),
    ],
)
def test_mcp_never_retries_authorization_or_parameter_failures(monkeypatch, error):
    from app.infrastructure.mcp import client

    calls = []

    def fail(factory, timeout):
        calls.append(1)
        raise error

    monkeypatch.setattr(client, "_sync", fail)
    result = client.call_tool(
        mcp_config.McpServerConfig(name="demo", command="x"),
        "read",
        {},
        retry_safe=True,
    )
    assert calls == [1] and result["success"] is False and result["retryable"] is False


@pytest.mark.asyncio
async def test_oauth_scope_and_rotated_secret_do_not_share_token_cache(monkeypatch):
    from types import SimpleNamespace

    from app.infrastructure.mcp import client

    calls = []

    async def post(self, url, **kwargs):
        calls.append(kwargs["data"])
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": f"t{len(calls)}", "expires_in": 1},
        )

    monkeypatch.setattr("httpx.AsyncClient.post", post)
    client._TOKEN_CACHE.clear()

    def config(scope, secret="s1"):
        return mcp_config.McpServerConfig(
            name="demo",
            command="x",
            auth={
                "token_url": "https://example.invalid/token",
                "client_id": "same",
                "client_secret": secret,
                "scope": scope,
            },
        )

    assert await client._oauth_header(config("alice")) != await client._oauth_header(config("bob"))
    assert await client._oauth_header(config("alice", "s2")) != await client._oauth_header(
        config("alice")
    )
    assert len(calls) == 3
    assert all(expiry <= client.time.time() + 1 for _, expiry in client._TOKEN_CACHE.values())
    client._TOKEN_CACHE.clear()


def test_internal_serialization_error_is_never_retried():
    from app.infrastructure.mcp.client import _serialize

    calls = []

    class Broken:
        def model_dump(self, mode="json"):
            calls.append(mode)
            raise TypeError("internal serialization bug")

    with pytest.raises(TypeError, match="internal serialization bug"):
        _serialize(Broken())
    assert calls == ["json"]


@pytest.mark.asyncio
async def test_oauth_network_io_is_cancellable_before_session_start(monkeypatch):
    import asyncio

    import httpx

    from app.infrastructure.mcp import client

    started = asyncio.Event()
    cancelled = asyncio.Event()
    client._TOKEN_CACHE.clear()

    async def stalled_post(self, url, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    def forbid_blocking_post(*args, **kwargs):
        raise AssertionError("OAuth must not block the MCP event-loop worker")

    monkeypatch.setattr(httpx.AsyncClient, "post", stalled_post)
    monkeypatch.setattr(httpx, "post", forbid_blocking_post)
    config = mcp_config.McpServerConfig(
        name="cancellable-auth",
        transport="http",
        url="https://mcp.example.invalid",
        timeout_seconds=0.03,
        auth={
            "token_url": "https://auth.example.invalid/token",
            "client_id": "test-client",
            "client_secret": "synthetic-test-secret",
        },
    )

    async def unexpected_session(session):
        raise AssertionError("Session must not start without its OAuth token")

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(config.timeout_seconds):
            await client._with_session(config, unexpected_session)

    assert started.is_set()
    assert cancelled.is_set()
    assert client._TOKEN_CACHE == {}


def test_discovered_contract_reaches_agent_validation_without_losing_constraints(monkeypatch):
    from app.application.agent_orchestrator import tool_spec

    schema = {
        "type": "object",
        "required": ["target"],
        "additionalProperties": False,
        "properties": {
            "target": {
                "type": "object",
                "required": ["role", "limit"],
                "additionalProperties": False,
                "properties": {
                    "role": {"type": "string", "enum": ["button", "textbox"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 2},
                },
            }
        },
    }
    info = McpToolInfo("inspect_form", "Inspect a form", schema, True)
    config = mcp_config.McpServerConfig(
        name="browser", command="x", read_only_tools=("inspect_form",)
    )
    action = mcp_registry._action_spec(info, config)
    action["output_schema"] = {
        "type": "object",
        "required": ["success", "receipt"],
        "properties": {"success": {"type": "boolean"}, "receipt": {"type": "string"}},
    }
    registry = {
        "mcp__browser": {"actions": {"inspect_form": action}},
        "shipment_orders": {
            "actions": {"generate_batch": {"input_schema": {}, "output_schema": {}}}
        },
    }
    monkeypatch.setattr(
        "app.services.tools_execution.registry.get_workflow_tool_registry", lambda: registry
    )
    monkeypatch.setattr(tool_spec, "_TOOL_SPECS_CACHE", None)
    spec = tool_spec.get_tool_action_spec("mcp__browser", "inspect_form")
    assert spec is not None and spec.read_only and spec.idempotent
    assert spec.description == "Inspect a form"
    assert spec.input_schema == schema
    assert spec.output_schema == action["output_schema"]
    valid = {"target": {"role": "button", "limit": 1}}
    assert tool_spec.validate_tool_call("mcp__browser", "inspect_form", valid).ok
    for invalid in (
        {"target": {"role": "dialog", "limit": 1}},
        {"target": {"role": "button", "limit": 3}},
        {"target": {"role": "button", "limit": "1"}},
        {"target": {"role": "button", "limit": 1, "hidden": True}},
    ):
        assert not tool_spec.validate_tool_call("mcp__browser", "inspect_form", invalid).ok
    assert not tool_spec.validate_tool_result("mcp__browser", "inspect_form", {"success": True}).ok
    fixed_key = ("shipment_orders", "generate_batch")
    fixed = tool_spec.get_tool_action_spec(*fixed_key)
    assert fixed.input_schema == tool_spec._SPECIAL_INPUT_SCHEMAS[fixed_key]
    assert fixed.output_schema == tool_spec._SPECIAL_OUTPUT_SCHEMAS[fixed_key]
    schema["properties"]["target"]["properties"]["limit"]["maximum"] = 100
    assert spec.input_schema["properties"]["target"]["properties"]["limit"]["maximum"] == 2
    assert action["input_schema"]["properties"]["target"]["properties"]["limit"]["maximum"] == 2


@pytest.mark.parametrize("success", [False, "false", "true", 1, 0, None, {}, []])
def test_mcp_transport_success_does_not_promote_failed_or_invalid_business_receipts(
    monkeypatch, success
):
    from mcp.types import CallToolResult, TextContent

    from app.infrastructure.mcp import client

    receipt = {"success": success, "evidence": {"observed": "not committed"}}
    result = CallToolResult(
        content=[TextContent(type="text", text="transport delivered")],
        structuredContent=receipt,
        isError=False,
    )
    monkeypatch.setattr(client, "_run_with_reconnect", lambda *a, **kw: result)
    output = client.call_tool(mcp_config.McpServerConfig(name="demo", command="x"), "submit", {})
    assert output["success"] is False
    assert output["structuredContent"] == receipt
    assert output["error_code"] == (
        "mcp_business_error" if success is False else "mcp_result_invalid"
    )
    assert output["retryable"] is False and output["reconciliation_required"] is True
    assert output["outcome"] == "unknown"


def test_incomplete_mcp_result_cannot_complete_a_write(monkeypatch):
    from mcp.types import CallToolResult

    from app.infrastructure.mcp import client

    monkeypatch.setattr(
        client,
        "_run_with_reconnect",
        lambda *a, **kw: CallToolResult(content=[], resultType="input_required"),
    )
    output = client.call_tool(mcp_config.McpServerConfig(name="demo", command="x"), "submit", {})
    assert output["success"] is False and output["resultType"] == "input_required"
    assert output["error_code"] == "mcp_result_incomplete" and output["retryable"] is False


@pytest.mark.parametrize("structured", [{"success": True}, {"rows": []}, [{"id": 1}]])
def test_mcp_sdk_structured_data_is_preserved_without_inventing_business_fields(
    monkeypatch, structured
):
    from mcp.types import CallToolResult

    from app.infrastructure.mcp import client

    monkeypatch.setattr(
        client,
        "_run_with_reconnect",
        lambda *a, **kw: CallToolResult(content=[], structuredContent=structured),
    )
    output = client.call_tool(mcp_config.McpServerConfig(name="demo", command="x"), "read", {})
    assert output["success"] is True and output["structuredContent"] == structured
    assert output["structuredContent"] is not structured


def test_real_mcp_stdio_preserves_structured_receipts_and_business_failure(tmp_path):
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
                           "receipt": {"form_id": "synthetic-form-1"}})

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
