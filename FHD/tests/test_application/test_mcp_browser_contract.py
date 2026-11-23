"""Browser contracts retain model inputs and bind sessions to the executing run."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.application.agent_orchestrator import tool_spec
from app.application.tools.mcp import registry
from app.infrastructure.mcp.client import McpToolInfo
from app.infrastructure.mcp.config import McpServerConfig


@pytest.fixture(autouse=True)
def reset_contracts():
    registry.reset_mcp_cache_for_tests()
    tool_spec.invalidate_tool_specs_cache()
    yield
    registry.reset_mcp_cache_for_tests()
    tool_spec.invalidate_tool_specs_cache()


def register_browser(monkeypatch, *, persistent=True):
    schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "minLength": 1},
            "button": {"type": "string", "enum": ["left", "right"]},
        },
        "required": ["target"],
        "additionalProperties": False,
    }
    config = McpServerConfig(
        name="browser",
        command="node",
        browser=True,
        session_mode="persistent" if persistent else "stateless",
        read_only_tools=("browser_snapshot",),
    )
    monkeypatch.setattr(registry, "load_server_configs", lambda: [config])
    monkeypatch.setattr(registry, "_register_with_guard", lambda tools: None)
    monkeypatch.setattr(
        registry,
        "list_tools",
        lambda config: [
            McpToolInfo("browser_click", "Click an observed element", deepcopy(schema), False),
            McpToolInfo("browser_snapshot", "Read the current page", {"type": "object"}, True),
        ],
    )
    return config, schema


def test_browser_schema_reaches_canonical_catalog_and_rejects_invalid_action(monkeypatch):
    _config, schema = register_browser(monkeypatch)
    catalog = registry.merge_mcp_tools({})
    monkeypatch.setattr(
        "app.services.tools_execution.registry.get_workflow_tool_registry", lambda: catalog
    )
    contracts = tool_spec.build_tool_specs_v2()
    click = contracts[("mcp__browser", "browser_click")]
    for name, original in schema["properties"].items():
        assert click.input_schema["properties"][name] == original
    assert set(click.input_schema["required"]) == {*schema["required"], "verification"}
    assert click.description.startswith("Click an observed element")
    assert "verification" in click.description
    assert click.risk == "high"
    assert not click.idempotent
    snapshot = contracts[("mcp__browser", "browser_snapshot")]
    assert snapshot.read_only and snapshot.idempotent
    assert not tool_spec.validate_tool_call(
        "mcp__browser", "browser_click", {"target": "button", "button": "middle"}
    ).ok
    # Codex capability discovery uses the complete canonical schema, including
    # original minLength/enums/closed objects. No second planner compresses it.
    for name, original in schema["properties"].items():
        assert click.input_schema["properties"][name] == original
    assert set(click.input_schema["required"]) == {*schema["required"], "verification"}
    assert click.input_schema["properties"]["button"]["enum"] == ["left", "right"]
    assert click.input_schema["additionalProperties"] is False


@pytest.mark.parametrize("context", [{}, {"tenant_id": "1", "run_id": "run-one"}])
def test_browser_rejects_model_supplied_session_identity(monkeypatch, context):
    register_browser(monkeypatch)
    monkeypatch.setattr(registry, "call_tool", lambda *a, **k: pytest.fail("must not execute"))
    result = registry.call_mcp_tool(
        "mcp__browser",
        "browser_snapshot",
        {"_runtime_context": {"tenant_id": "other", "user_id": "other", "run_id": "other"}},
        runtime_context=context,
    )
    assert result["error_code"] == "mcp_session_scope_required"


def test_browser_session_is_account_tenant_and_run_scoped(monkeypatch):
    register_browser(monkeypatch)
    seen = []

    def call(config, action, arguments, **options):
        seen.append((arguments, options["session_scope"]))
        return {"success": True}

    monkeypatch.setattr(registry, "call_tool", call)
    base = {"tenant_id": "tenant-a", "user_id": "user-a", "run_id": "run-a"}
    for context in (
        base,
        dict(base),
        {**base, "tenant_id": "tenant-b"},
        {**base, "user_id": "user-b"},
        {**base, "run_id": "run-b"},
    ):
        registry.call_mcp_tool(
            "mcp__browser", "browser_snapshot", {"_run_id": "injected"}, runtime_context=context
        )
    assert seen[0] == seen[1]
    assert all(arguments == {} for arguments, scope in seen)
    assert len({scope for arguments, scope in seen}) == 4


def test_durable_generation_is_carried_to_next_action(monkeypatch):
    register_browser(monkeypatch)
    seen = {}

    def call(config, action, arguments, **options):
        seen.update(options)
        return {"success": True}

    monkeypatch.setattr(registry, "call_tool", call)
    context = {
        "tenant_id": "1",
        "user_id": "user",
        "run_id": "run",
        "node_outputs": {
            "navigate": {"server": "browser", "session_id": "generation-a", "success": True},
            "other": {"server": "different", "session_id": "generation-b", "success": True},
        },
    }
    assert registry.call_mcp_tool("mcp__browser", "browser_snapshot", runtime_context=context)[
        "success"
    ]
    assert seen["expected_session_id"] == "generation-a"
    context["node_outputs"]["drift"] = {"server": "browser", "session_id": "generation-b"}
    result = registry.call_mcp_tool("mcp__browser", "browser_snapshot", runtime_context=context)
    assert result["error_code"] == "mcp_session_lost"


def test_direct_mcp_boundary_checks_the_real_schema_before_transport(monkeypatch):
    register_browser(monkeypatch)
    monkeypatch.setattr(registry, "call_tool", lambda *a, **k: pytest.fail("must not execute"))
    result = registry.call_mcp_tool("mcp__browser", "browser_click", {"target": 123})
    assert result["error_code"] == "mcp_arguments_invalid"


def test_repaired_or_direct_browser_arguments_cannot_request_local_output(monkeypatch):
    register_browser(monkeypatch)
    monkeypatch.setattr(registry, "call_tool", lambda *a, **k: pytest.fail("must not execute"))
    result = registry.call_mcp_tool(
        "mcp__browser", "browser_snapshot", {"filename": "/tmp/unapproved-page.yml"}
    )
    assert result["error_code"] == "mcp_browser_action_rejected"


def test_stateless_tools_keep_existing_transport_contract(monkeypatch):
    register_browser(monkeypatch, persistent=False)
    seen = {}

    def call(config, action, arguments, *, retry_safe):
        seen.update(retry_safe=retry_safe)
        return {"success": True}

    monkeypatch.setattr(registry, "call_tool", call)
    assert registry.call_mcp_tool("mcp__browser", "browser_snapshot")["success"]
    assert seen == {"retry_safe": True}
    assert registry.browser_server_config("mcp__browser") is None


def test_local_config_rotation_invalidates_discovery_before_ttl(tmp_path, monkeypatch):
    path = tmp_path / "servers.json"
    monkeypatch.setenv("XCAGI_MCP_SERVERS_FILE", str(path))
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "1")
    monkeypatch.setattr(registry, "_register_with_guard", lambda tools: None)
    discoveries = []

    def discover(config):
        discoveries.append(config.headers["Authorization"])
        return [McpToolInfo("browser_snapshot", "", {"type": "object"}, True)]

    monkeypatch.setattr(registry, "list_tools", discover)
    server = {
        "transport": "http",
        "url": "https://browser.example/mcp",
        "browser": True,
        "session_mode": "persistent",
        "headers": {"Authorization": "Bearer first"},
    }
    path.write_text(json.dumps({"servers": {"browser": server}}), encoding="utf-8")
    assert registry.browser_server_config("mcp__browser").headers == server["headers"]
    registry.browser_server_config("mcp__browser")
    assert discoveries == ["Bearer first"]
    server["headers"] = {"Authorization": "Bearer rotated"}
    path.write_text(json.dumps({"servers": {"browser": server}}), encoding="utf-8")
    assert registry.browser_server_config("mcp__browser").headers == server["headers"]
    assert discoveries == ["Bearer first", "Bearer rotated"]
    path.unlink()
    assert registry.browser_server_config("mcp__browser") is None
