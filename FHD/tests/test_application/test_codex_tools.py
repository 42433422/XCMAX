from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from app.infrastructure.codex.tools import CodexToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def bridge_setup(trusted_actor, monkeypatch, tmp_path):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["product.view", "tool.customers.create", "customer.view"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(user_id=str(actor.user_id), message="执行企业任务", status="running")
    run.metadata["runtime_context"] = actor.context
    repository.save(run)
    store = CodexBindingStore(repository)
    grant = store.create(run.run_id)
    orchestrator = AgentOrchestrator(
        repository=repository, tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute)
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    return SimpleNamespace(
        actor=actor, store=store, run=run, grant=grant, bridge=CodexToolBridge(store, orchestrator)
    )


def test_authority_arguments_and_unbound_tools_never_publish_tasks(bridge_setup):
    setup = bridge_setup
    for params in (
        {"tenant_id": 999},
        {"approved": True},
        {"_actor_authorization": {}},
        {"idempotency_key": "replace"},
    ):
        with pytest.raises(CodexBindingError) as error:
            setup.bridge.invoke(
                setup.grant.mcp_token,
                "execute_action",
                {
                    "call_id": "attack",
                    "tool_id": "products",
                    "action": "query",
                    "params": params,
                },
            )
        assert error.value.code == "identity_override"
    with pytest.raises(CodexBindingError):
        setup.bridge.invoke(
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "recursive",
                "tool_id": "aiopen",
                "action": "chat",
                "params": {"message": "re-enter"},
            },
        )
    assert setup.store.get(setup.run.run_id).metadata["calls"] == {}
    assert len(setup.store.repository.list_recent()) == 1


def test_write_uses_original_approval_and_stable_task_for_repeated_model_calls(bridge_setup):
    setup = bridge_setup
    args = {
        "call_id": "first",
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "fixture"},
    }
    first = setup.bridge.invoke(setup.grant.mcp_token, "execute_action", args)
    assert first["status"] == "waiting_user"
    assert first["pending_approval"] is True
    assert first["verified"] is False
    assert first["tool_calls"] == []
    again = setup.bridge.invoke(
        setup.grant.mcp_token, "execute_action", {**args, "call_id": "fresh-model-id"}
    )
    assert again["task_id"] == first["task_id"]
    assert again["run_id"] == first["run_id"]
    assert len(setup.store.repository.list_recent()) == 2
    child = setup.store.repository.get(first["run_id"])
    assert child.metadata["runtime_context"]["parent_run_id"] == setup.run.run_id
    assert child.metadata["plan"]["nodes"][0]["params"] == args["params"]
    card = first["approval_card"]
    assert card["kind"] == "approval_pending"
    assert card["run_id"] == child.run_id and card["plan_id"] == child.plan_id
    assert card["blocking_nodes"] == [child.steps[0].node_id]
    assert card["approval_nodes"][0]["step_id"] == child.steps[0].step_id
    assert card["approval_nodes"][0]["params"] == args["params"]
    assert "approval_grant" not in card


def test_read_executes_controlled_chain_and_replays_persisted_receipt(bridge_setup, monkeypatch):
    setup = bridge_setup
    calls = []

    def dispatch(tool, action, params):
        from app.infrastructure.tenant_scope import current_tenant_id

        assert current_tenant_id() == setup.actor.tenant_id
        assert params["_runtime_context"]["parent_run_id"] == setup.run.run_id
        calls.append((tool, action))
        return {"success": True, "data": [{"model_number": "fixture", "price": 12}]}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    args = {
        "call_id": "read",
        "tool_id": "products",
        "action": "query",
        "params": {"keyword": "fixture"},
    }
    receipt = setup.bridge.invoke(setup.grant.mcp_token, "execute_action", args)
    child = setup.store.repository.get(receipt["run_id"])
    assert receipt["verified"] is True, (
        receipt,
        child.error,
        [s.output for s in child.steps],
        calls,
    )
    reopened = CodexToolBridge(
        CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    )
    replay = reopened.invoke(setup.grant.mcp_token, "execute_action", args)
    assert replay["run_id"] == receipt["run_id"]
    assert replay["verified"] is True
    assert calls == [("products", "query")]


def test_lost_claim_without_child_cannot_be_replayed(bridge_setup):
    setup = bridge_setup
    setup.store.claim_call(
        setup.run.run_id,
        "lost",
        tool_id="customers",
        action="create",
        params={"unit_name": "fixture"},
        read_only=False,
        generation=setup.grant.binding.metadata["generation"],
    )
    active = setup.bridge.invoke(setup.grant.mcp_token, "task_evidence", {"call_id": "lost"})
    assert active["status"] == "claimed"
    assert active["in_progress"] is True
    setup.store.close(setup.run.run_id, "interrupted")
    result = setup.store.receipt_snapshot(setup.run.run_id)[0]["receipt"]
    assert result["outcome"] == "unknown"
    with pytest.raises(CodexBindingError) as error:
        setup.store.create(setup.run.run_id)
    assert error.value.code == "reconciliation_required"
    assert len(setup.store.repository.list_recent()) == 1


def test_http_403_inside_transport_success_does_not_verify_business_success(bridge_setup):
    setup = bridge_setup
    result = setup.bridge.invoke(
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    child = setup.store.repository.get(result["run_id"])
    child.status = "completed"
    step = child.steps[0]
    step.status = "completed"
    step.output = {"success": True, "status_code": 403, "data": {"message": "denied"}}
    child.tool_calls.append(
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=step.params,
            status="completed",
            output=step.output,
        )
    )
    setup.store.repository.save(child)
    result = setup.bridge.invoke(setup.grant.mcp_token, "task_evidence", {"call_id": "write"})
    assert result["verified"] is False
    assert result["status"] == "failed"


def test_request_input_is_durable_and_blocks_additional_actions(bridge_setup):
    setup = bridge_setup
    result = setup.bridge.invoke(
        setup.grant.mcp_token, "request_input", {"question": "请提供客户名称"}
    )
    assert result["needs_user_input"] is True
    assert (
        setup.store.get(setup.run.run_id).metadata["waiting_input"]["question"] == "请提供客户名称"
    )
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "read",
                "tool_id": "products",
                "action": "query",
                "params": {},
            },
        )
    assert error.value.code == "waiting_user"


def test_employee_gate_cannot_be_lost_or_override_actor_permissions(bridge_setup):
    setup = bridge_setup
    setup.store.update(
        setup.run.run_id,
        lambda run, metadata: metadata["runtime_config"].update(gate_required=True),
    )
    args = {"call_id": "gated", "tool_id": "products", "action": "query", "params": {}}
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(setup.grant.mcp_token, "execute_action", args)
    assert error.value.code == "gate_required"
    setup.bridge.gate = lambda tool, action, params: {"ok": False, "reason": "workspace blocked"}
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(setup.grant.mcp_token, "execute_action", args)
    assert error.value.code == "gate_denied"
    setup.bridge.gate = lambda tool, action, params: {"ok": True}
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token,
            "execute_action",
            {
                **args,
                "tool_id": "materials",
                "action": "list",
            },
        )
    assert error.value.code == "permission_denied"
    assert setup.store.get(setup.run.run_id).metadata["calls"] == {}


def test_private_bridge_rejects_a_valid_token_for_another_run(bridge_setup):
    setup = bridge_setup
    other = AgentRun(user_id=setup.run.user_id, message="another task", status="running")
    other.metadata["runtime_context"] = setup.actor.context
    setup.store.repository.save(other)
    other_grant = setup.store.create(other.run_id)
    bridge = CodexToolBridge(
        setup.store,
        setup.bridge.orchestrator,
        gate=lambda *args: {"ok": True},
        run_id=setup.run.run_id,
    )
    with pytest.raises(CodexBindingError) as error:
        bridge.invoke(other_grant.mcp_token, "request_input", {"question": "new question"})
    assert error.value.code == "scope_conflict"
    assert "waiting_input" not in setup.store.get(other.run_id).metadata


def test_waiting_approval_blocks_new_business_actions(bridge_setup):
    setup = bridge_setup
    setup.bridge.invoke(
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "pending",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "second",
                "tool_id": "products",
                "action": "query",
                "params": {},
            },
        )
    assert error.value.code == "waiting_user"
    assert len(setup.store.repository.list_recent()) == 2


def test_receipt_cannot_substitute_different_parameters(bridge_setup):
    setup = bridge_setup
    receipt = setup.bridge.invoke(
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    child = setup.store.repository.get(receipt["run_id"])
    child.steps[0].params = {"unit_name": "changed-after-approval"}
    child.metadata["plan"]["nodes"][0]["params"] = child.steps[0].params
    setup.store.repository.save(child)
    with pytest.raises(CodexBindingError) as error:
        setup.bridge.invoke(setup.grant.mcp_token, "task_evidence", {"call_id": "write"})
    assert error.value.code == "evidence_mismatch"


def test_revoke_after_child_is_saved_prevents_dispatch(bridge_setup, monkeypatch):
    setup = bridge_setup
    original = setup.store.record_call
    dispatched = []

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("child_run_id") and kwargs.get("receipt") is None:
            setup.store.close(setup.run.run_id, "cancelled")
        return result

    monkeypatch.setattr(setup.store, "record_call", record)
    monkeypatch.setattr(setup.bridge.orchestrator, "execute_dispatched_run", dispatched.append)
    with pytest.raises(CodexBindingError):
        setup.bridge.invoke(
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "read",
                "tool_id": "products",
                "action": "query",
                "params": {},
            },
        )
    assert dispatched == []
    call = setup.store.get(setup.run.run_id).metadata["calls"]["read"]
    assert setup.store.repository.get(call["child_run_id"]).status == "cancelled"


def test_official_sdk_mcp_endpoint_rejects_wrong_audience_and_lists_tools(bridge_setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.infrastructure.codex.mcp_server import MCP_PATH, router
    from app.infrastructure.codex.tools import CODEX_TOOL_NAMES

    setup = bridge_setup
    app = FastAPI()
    app.state.codex_binding_store = setup.store
    app.state.codex_tool_bridge = setup.bridge
    app.state.codex_run_id = setup.run.run_id
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
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == set(
            CODEX_TOOL_NAMES
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
        assert malformed.json()["result"]["isError"] is True
        assert malformed.json()["result"]["structuredContent"]["error_code"] == "invalid_arguments"
        assert setup.store.get(setup.run.run_id).metadata["calls"] == {}
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


def test_private_mcp_initialize_and_list_cannot_borrow_another_run_token(bridge_setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.infrastructure.codex.mcp_server import MCP_PATH, router

    setup = bridge_setup
    other = AgentRun(user_id=setup.run.user_id, message="another task", status="running")
    other.metadata["runtime_context"] = setup.actor.context
    setup.store.repository.save(other)
    token = setup.store.create(other.run_id).mcp_token
    app = FastAPI()
    app.state.codex_binding_store = setup.store
    app.state.codex_tool_bridge = CodexToolBridge(setup.store, run_id=setup.run.run_id)
    app.state.codex_run_id = setup.run.run_id
    app.include_router(router)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    with TestClient(app) as client:
        for method in ("initialize", "tools/list"):
            response = client.post(
                MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method}
            )
            assert response.status_code == 403
            assert response.json()["error_code"] == "scope_conflict"
        del app.state.codex_run_id
        response = client.post(
            MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert response.status_code == 503
