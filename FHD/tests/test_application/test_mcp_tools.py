"""外部 MCP 工具接入：配置、注册表合并、路由与并行开关。"""

from __future__ import annotations

import json
from pathlib import Path

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
        lambda *a, **k: [mcp_config.McpServerConfig(name="demo", command="x")],
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
    assert actions["search_notes"]["required_params"] == ["query"]
    assert actions["write_note"]["risk"] == "high"
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

    def fake_call(config, tool_name, arguments):
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
        lambda tool_id, action, params: {
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
    from app.application.agent_orchestrator.orchestrator import _plan_parallel_enabled

    monkeypatch.setenv("XCAGI_PLAN_PARALLEL", value)
    assert _plan_parallel_enabled() is expected


@pytest.mark.asyncio
async def test_list_all_tools_follows_pagination() -> None:
    pytest.importorskip("mcp")
    from types import SimpleNamespace

    from app.infrastructure.mcp.client import _list_all_tools

    class Session:
        def __init__(self) -> None:
            self.cursors: list[object] = []

        async def list_tools(self, params=None):
            self.cursors.append(params)
            if params is None:
                return SimpleNamespace(tools=[SimpleNamespace(name="first")], nextCursor="page-2")
            return SimpleNamespace(tools=[SimpleNamespace(name="second")], nextCursor=None)

    session = Session()
    tools = await _list_all_tools(session)
    assert [tool.name for tool in tools] == ["first", "second"]
    assert len(session.cursors) == 2
    assert session.cursors[1] is not None


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


def test_oauth_header_is_cached(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.infrastructure.mcp import client as mcp_client
    from app.infrastructure.mcp.config import McpServerConfig

    calls: list[dict] = []

    def fake_post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": "tok", "expires_in": 3600},
        )

    monkeypatch.setattr("httpx.post", fake_post)
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

    first = mcp_client._oauth_header(config)
    second = mcp_client._oauth_header(config)

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
