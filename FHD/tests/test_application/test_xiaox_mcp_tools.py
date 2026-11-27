"""The actual Xiaox MCP interface exposes scoped schemas and rejects borrowed identities."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_tools import (
    _bind_goal,
    _invoke,
)
from tests.test_application.test_xiaox_tools import (
    bridge_setup as bridge_setup,
)


def test_employee_mcp_action_uses_live_nested_schema_only_when_visible():
    from jsonschema import Draft202012Validator

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.infrastructure.xiaox.tools import mcp_tool_definitions

    generic = next(
        tool
        for tool in mcp_tool_definitions([("customers", "query")])
        if tool.name == "execute_action"
    )
    assert "allOf" not in generic.input_schema
    tool = next(
        tool
        for tool in mcp_tool_definitions([("employee", "execute")])
        if tool.name == "execute_action"
    )
    spec = get_tool_action_spec("employee", "execute")
    assert tool.input_schema["allOf"][0]["then"]["properties"]["params"] == spec.input_schema
    validator = Draft202012Validator(tool.input_schema)
    base = {"tool_id": "employee", "action": "execute", "call_id": "one", "schema_digest": "a" * 64}
    assert any(
        error.validator == "type"
        for error in validator.iter_errors(
            {
                **base,
                "params": {
                    "employee_id": "excel-template-write-employee",
                    "task": "写入工作簿",
                    "input": '{"plan":{}}',
                },
            }
        )
    )
    assert not list(
        validator.iter_errors(
            {
                **base,
                "params": {
                    "employee_id": "quote-agent",
                    "task": "Prepare a quote",
                    "input": {"customer": "Acme Trading"},
                },
            }
        )
    )
    reader = {
        "employee_id": "excel-full-read-employee",
        "task": "读取工作簿",
        "input": {"user_request": "读取原卷"},
    }
    assert list(validator.iter_errors({**base, "params": reader}))
    assert not list(
        validator.iter_errors(
            {
                **base,
                "params": {**reader, "input": {"upload_id": "owned-upload-id"}},
            }
        )
    )


def test_direct_workbook_reader_exposes_required_source_to_model():
    from jsonschema import Draft202012Validator

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.infrastructure.xiaox.tools import mcp_tool_definitions

    tools = mcp_tool_definitions([("excel_analysis", "read")])
    reader = next(tool for tool in tools if tool.name == "execute_excel_read")
    assert (
        reader.input_schema["properties"]["file_path"]
        == get_tool_action_spec("excel_analysis", "read").input_schema["properties"]["file_path"]
    )
    validator = Draft202012Validator(reader.input_schema)
    base = {"call_id": "read-once", "schema_digest": "a" * 64}
    assert any(error.validator == "required" for error in validator.iter_errors(base))
    assert not list(validator.iter_errors({**base, "file_path": "owned-upload-id"}))
    assert not any(tool.name == "execute_excel_structure" for tool in tools)
    generic = next(tool for tool in tools if tool.name == "execute_action")
    generic_validator = Draft202012Validator(generic.input_schema)
    envelope = {"tool_id": "excel_analysis", "action": "read", **base}
    assert list(generic_validator.iter_errors({**envelope, "params": {}}))
    assert not list(
        generic_validator.iter_errors({**envelope, "params": {"file_path": "owned-upload-id"}})
    )


def test_official_sdk_mcp_endpoint_rejects_wrong_audience_and_lists_tools(bridge_setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.infrastructure.xiaox.mcp_server import MCP_PATH, router
    from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES

    setup = bridge_setup
    app = FastAPI()
    app.state.xiaox_binding_store = setup.store
    app.state.xiaox_tool_bridge = setup.bridge
    app.state.xiaox_run_id = setup.run.run_id
    setup.bridge.run_id = setup.run.run_id
    app.include_router(router)
    headers = {
        "Authorization": f"Bearer {setup.grant.mcp_token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    with TestClient(app) as client:
        denied = client.post(
            MCP_PATH,
            headers={**headers, "Authorization": f"Bearer {setup.grant.model_token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert denied.status_code == 403
        response = client.post(
            MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert response.status_code == 200, response.text
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == (
            set(XIAOX_TOOL_NAMES)
            - {"execute_employee", "execute_excel_read", "execute_excel_structure"}
        )
        # MCP SDK v2 removed automatic lowlevel tool-schema validation.
        # Extra model-supplied authority fields must fail before the business bridge.
        malformed = client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "execute_action",
                    "arguments": {
                        "tool_id": "customers",
                        "action": "create",
                        "call_id": "tampered",
                        "params": {"unit_name": "fixture"},
                        "approved": True,
                    },
                },
            },
        )
        assert malformed.status_code == 200
        tool_error = malformed.json()["result"]
        assert tool_error["isError"] is True
        assert tool_error["structuredContent"] == {
            "success": False,
            "verified": False,
            "status": "not_started",
            "error_code": "invalid_arguments",
            "message": "工具参数不满足已发布的能力契约",
            "schema_violation": {
                "path": "$",
                "validator": "required",
                "missing": ["schema_digest"],
            },
        }
        assert json.loads(tool_error["content"][0]["text"]) == tool_error["structuredContent"]
        assert "fixture" not in malformed.text and "tampered" not in malformed.text
        assert setup.store.get(setup.run.run_id).metadata["calls"] == {}
        action = {"tool_id": "customers", "action": "create"}
        spec = setup.bridge.invoke(setup.grant.mcp_token, "capability_describe", action)[
            "capability"
        ]
        repaired = client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "execute_action",
                    "arguments": {
                        **action,
                        "call_id": "tampered",
                        "params": {"unit_name": "fixture"},
                        "schema_digest": spec["schema_digest"],
                    },
                },
            },
        ).json()["result"]["structuredContent"]
        assert repaired["pending_approval"] is True and repaired["verified"] is False
        assert len(setup.store.get(setup.run.run_id).metadata["calls"]) == 1
        result = client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "request_input", "arguments": {"question": "请提供日期"}},
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["result"]["structuredContent"]["needs_user_input"] is True


@pytest.mark.parametrize("allowed_actions", [["customers.query"], []])
def test_mcp_advertises_only_live_run_actions_and_uniform_discovery(bridge_setup, allowed_actions):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from jsonschema import Draft202012Validator

    from app.infrastructure.xiaox.mcp_server import MCP_PATH, router

    setup = bridge_setup
    run = AgentRun(user_id=setup.run.user_id, message="列出可用能力", status="running")
    run.metadata["runtime_context"] = setup.actor.context
    _bind_goal(run)
    setup.store.repository.save(run)
    grant = setup.store.create(run.run_id, allowed_actions=allowed_actions)
    app = FastAPI()
    app.include_router(router)
    app.state.xiaox_binding_store = setup.store
    app.state.xiaox_tool_bridge = XiaoxToolBridge(setup.store, run_id=run.run_id)
    app.state.xiaox_run_id = run.run_id
    headers = {
        "Authorization": f"Bearer {grant.mcp_token}",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app) as client:

        def rpc(method, params=None):
            body = {"jsonrpc": "2.0", "id": 1, "method": method}
            if params is not None:
                body["params"] = params
            response = client.post(MCP_PATH, headers=headers, json=body)
            assert response.status_code == 200, response.text
            return response.json()["result"]

        def call(name, **arguments):
            return rpc("tools/call", {"name": name, "arguments": arguments})["structuredContent"]

        visible = {tool["name"]: tool["inputSchema"] for tool in rpc("tools/list")["tools"]}
        for schema in visible.values():
            Draft202012Validator.check_schema(schema)
        found = call("capability_search", limit=1)
        assert [
            f"{row['tool_id']}.{row['action']}" for row in found["capabilities"]
        ] == allowed_actions
        assert found["next_offset"] is None
        if allowed_actions:
            for name in ("capability_describe", "execute_action"):
                assert visible[name]["properties"]["tool_id"]["enum"] == ["customers"]
                assert visible[name]["properties"]["action"]["enum"] == ["query"]
            assert call("capability_describe", tool_id="customers", action="query")["success"]
        else:
            assert {"capability_describe", "execute_action"}.isdisjoint(visible)
        denied = call("capability_describe", tool_id="customers", action="create")
        unknown = call("capability_describe", tool_id="fixture_missing", action="missing")
        assert denied == unknown
        assert denied["next_call"] == {"name": "capability_search", "arguments": {}}
    assert setup.store.get(run.run_id).metadata["calls"] == {}


def test_private_mcp_initialize_and_list_cannot_borrow_another_run_token(bridge_setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.infrastructure.xiaox.mcp_server import MCP_PATH, router

    setup = bridge_setup
    other = AgentRun(user_id=setup.run.user_id, message="another task", status="running")
    other.metadata["runtime_context"] = setup.actor.context
    _bind_goal(other)
    setup.store.repository.save(other)
    token = setup.store.create(other.run_id).mcp_token
    app = FastAPI()
    app.state.xiaox_binding_store = setup.store
    app.state.xiaox_tool_bridge = XiaoxToolBridge(setup.store, run_id=setup.run.run_id)
    app.state.xiaox_run_id = setup.run.run_id
    app.include_router(router)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    with TestClient(app) as client:
        for method in ("initialize", "tools/list"):
            response = client.post(
                MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method}
            )
            assert response.status_code == 403
            assert response.json()["error_code"] == "scope_conflict"
        del app.state.xiaox_run_id
        response = client.post(
            MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert response.status_code == 503
