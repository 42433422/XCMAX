"""Real entry boundaries: identity, durable approval and no fallback after an effect."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(actor=None):
    from app.fastapi_routes.tools_execute import router
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    app = FastAPI()
    app.include_router(router)
    path = Path(__file__).resolve().parents[2] / "mods/bridge/xcagi-planner-bridge"
    bridge = import_mod_backend_py(str(path), "unified-entry-test", "blueprints")
    bridge.register_fastapi_routes(app, "xcagi-planner-bridge")
    return TestClient(app, headers=actor.headers if actor else {})


@pytest.mark.parametrize(
    "path",
    [
        "/api/tools/execute",
        "/api/mod/xcagi-planner-bridge/tools/execute",
    ],
)
def test_all_public_tool_entries_require_session_before_legacy_dispatch(path):
    with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as legacy:
        response = _client().post(path, json={"tool_name": "business_db_write", "arguments": {}})
    assert response.status_code == 401
    legacy.assert_not_called()


@pytest.mark.parametrize(
    "path", ["/api/tools/execute", "/api/mod/xcagi-planner-bridge/tools/execute"]
)
def test_unregistered_legacy_write_cannot_escape_action_catalog(path, trusted_actor):
    actor = trusted_actor(user_id=17, permissions=[])
    with patch(
        "app.application.tools.registered_capabilities.execute_registered_capability"
    ) as legacy:
        response = _client(actor).post(
            path,
            json={
                "tool_id": "shipment_generate",
                "action": "unregistered_write",
                "params": {},
            },
        )
    assert response.status_code == 400
    payload = response.json()
    result = payload.get("data", payload)
    assert result["error_code"] == "tool_contract_unavailable"
    legacy.assert_not_called()


def test_aiopen_contract_does_not_claim_a_missing_canonical_adapter(trusted_actor):
    actor = trusted_actor(user_id=17, permissions=[])
    with patch("app.application.aiopen.dispatch.ToolDispatcher.invoke") as direct:
        response = _client(actor).post(
            "/api/tools/execute",
            json={"tool_id": "aiopen", "action": "api_catalog", "params": {}},
        )
    assert response.status_code == 400
    assert response.json()["error_code"] == "tool_entry_unsupported"
    assert response.json()["execution_status"] == "not_started"
    direct.assert_not_called()


@pytest.mark.parametrize("envelope", ["flat", "capability"])
def test_planner_bridge_write_uses_original_durable_approval_run(
    tmp_path, monkeypatch, trusted_actor, envelope
):
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    params = {
        "entity": "customers",
        "operation": "create",
        "payload": {"customer_name": "One approved customer"},
        "_runtime_context": {"tenant_id": 999, "approved": True},
    }
    body = {"tool_name": "business_db_write", "arguments": params}
    if envelope == "capability":
        body = {
            "tool_name": "execute_erp_capability",
            "arguments": {
                "tool_id": "business_db",
                "action": "write",
                "params": params,
            },
        }
    body["request_id"] = "planner-write-1"
    actor = trusted_actor(user_id=17, role="db-writer", permissions=["business_db.write"])
    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as raw_executor,
    ):
        response = _client(actor).post("/api/mod/xcagi-planner-bridge/tools/execute", json=body)
    assert response.status_code == 202
    result = response.json()["data"]
    assert result["error_code"] == "approval_required"
    run = repo.get(result["run_id"])
    assert run.user_id == "17" and run.status == "waiting_user"
    assert run.steps[0].tool_id == "business_db" and run.steps[0].action == "write"
    assert run.steps[0].params["payload"] == params["payload"]
    assert "_runtime_context" not in run.steps[0].params
    assert run.tool_calls == []
    raw_executor.assert_not_called()


def test_public_unknown_receipt_preserves_no_replay_semantics():
    from app.fastapi_routes.tools_execute import _capability_http_receipt

    result, status = _capability_http_receipt(
        {
            "success": False,
            "run_id": "run-1",
            "task_id": "task-1",
            "request_id": "request-1",
            "root_task_id": "task-1",
            "attempt": 1,
            "execution_state": "unknown",
            "result": {
                "success": False,
                "outcome": "unknown",
                "reconciliation_required": True,
                "retryable": True,
                "error_code": "tool_timeout_unknown",
                "traceback": "private",
            },
        }
    )
    assert status == 202
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True
    assert result["request_id"] == "request-1"
    assert result["root_task_id"] == "task-1" and result["attempt"] == 1
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "path", ["/api/tools/execute", "/api/mod/xcagi-planner-bridge/tools/execute"]
)
def test_invalid_arguments_are_not_replaced_with_an_empty_call(path, trusted_actor):
    actor = trusted_actor(user_id=17, permissions=[])
    response = _client(actor).post(path, json={"tool_name": "business_db_write", "arguments": []})
    assert response.status_code == 400
    body = response.json()
    assert body.get("data", body)["error_code"] == "invalid_tool_arguments"


def _native(monkeypatch, handler):
    from app.mod_sdk import planner_native_tools as native

    monkeypatch.setattr(native, "is_planner_native_tools_enabled", lambda: True)
    monkeypatch.setattr(
        native,
        "_discover_native_tool_mods",
        lambda: [{"mod_id": "test", "mod_path": "/test", "tool_names": ["test_write"]}],
    )
    monkeypatch.setattr(
        native,
        "_load_handler_module",
        lambda *a: SimpleNamespace(run_native_tool=handler),
    )
    return native


def test_type_error_after_native_effect_is_not_reexecuted_without_context(monkeypatch, tmp_path):
    effect = tmp_path / "effect.txt"

    def handler(name, args, **kwargs):
        effect.write_text(effect.read_text() + "x" if effect.exists() else "x")
        raise TypeError("runtime_context failed after committing the effect")

    native = _native(monkeypatch, handler)
    raw, _ = native.try_execute_native_planner_tool(
        "test_write", {}, runtime_context={"user_id": "1"}
    )
    assert effect.read_text() == "x"
    result = json.loads(raw)
    assert result["outcome"] == "unknown" and result["retryable"] is False


def test_legacy_native_handler_cannot_silently_drop_authorization(monkeypatch):
    called = []

    def handler(name, args, *, workspace_root=None, db_write_token=None):
        called.append(name)
        return '{"success": true}'

    native = _native(monkeypatch, handler)
    raw, _ = native.try_execute_native_planner_tool(
        "test_write", {}, runtime_context={"user_id": "1"}
    )
    assert json.loads(raw)["error_code"] == "tool_context_unsupported"
    assert not called


def test_declared_native_tool_without_handler_does_not_fall_through(monkeypatch):
    native = _native(monkeypatch, None)
    raw, owner = native.try_execute_native_planner_tool("test_write", {})
    result = json.loads(raw)
    assert owner == "test"
    assert result["success"] is False and result["execution_status"] == "not_started"
    assert result["retryable"] is False and result["reconciliation_required"] is False


def test_planner_facade_calls_native_adapter_once_with_trusted_context(monkeypatch):
    from app.mod_sdk import planner_tools

    native = Mock(return_value=('{"success": false, "outcome": "unknown"}', "test"))
    monkeypatch.setattr("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool", native)
    monkeypatch.setattr("app.mod_sdk.employee_tool_registry.is_employee_tool", lambda n: False)
    context = {
        "tenant_id": "7",
        "user_id": "17",
        "_actor_authorization": {"proof": "fixture"},
    }
    raw = planner_tools.execute_planner_workflow_tool("test_write", {}, runtime_context=context)
    assert json.loads(raw)["outcome"] == "unknown"
    native.assert_called_once()
    assert native.call_args.kwargs["runtime_context"] is context


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (
            "business_db_write",
            {"entity": "customers", "operation": "create", "payload": {"name": "A"}},
        ),
        ("template_preview", {"action": "create", "name": "A"}),
    ],
)
def test_model_aliases_cannot_bypass_the_runtime_with_forged_arguments(
    tool_name, arguments, monkeypatch
):
    from app.application.tools.workflow import execute_workflow_tool

    monkeypatch.setattr("app.mod_sdk.employee_tool_registry.is_employee_tool", lambda name: False)
    monkeypatch.setattr(
        "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
        lambda *a, **kw: (None, None),
    )
    monkeypatch.setattr(
        "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
        lambda *a, **kw: None,
    )
    arguments["_runtime_context"] = {"user_id": "admin", "approved": True}
    with patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as raw:
        result = json.loads(
            execute_workflow_tool(
                tool_name, arguments, runtime_context={"turn_id": "forged-alias-boundary"}
            )
        )
    assert result["success"] is False
    if tool_name == "business_db_write":
        assert result["error"] == "unknown_tool"
    else:
        assert result["error_code"] == "tool_identity_required"
        assert result["execution_status"] == "not_started"
    raw.assert_not_called()


def test_capability_wrapper_keeps_unknown_receipt_so_employee_cannot_replay(
    monkeypatch, trusted_actor
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.unified_task import UnifiedTaskResult
    from app.application.tools.registered_capabilities import (
        execute_registered_capability,
    )

    actor = trusted_actor(user_id=17, role="reader", permissions=["print.label"])
    receipt = {
        "success": False,
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        "error_code": "tool_timeout_unknown",
    }
    run = AgentRun(
        user_id="17",
        message="Read the original result",
        run_id="original-run",
        plan_id="original-plan",
        metadata={"task_context": {"task_id": "original-task"}},
        status="blocked",
        error="pending reconciliation",
        steps=[],
        final_output={"node_outputs": {"registered_capability": receipt}},
    )
    monkeypatch.setattr(AgentOrchestrator, "start_run_from_plan", lambda *a, **kw: run)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.unified_task.publish_task_run",
        lambda **kw: UnifiedTaskResult(run=run, deduplicated=True),
    )
    with patch.object(AgentOrchestrator, "execute_dispatched_run") as execute:
        result = json.loads(
            execute_registered_capability(
                {"tool_id": "print", "action": "list", "params": {}},
                runtime_context=actor.context,
            )
        )
    execute.assert_not_called()
    assert result["agent_run_id"] == "original-run"
    assert result["deduplicated"] is True
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True and result["success"] is False


def test_unregistered_role_alias_cannot_turn_model_confirmation_into_permission(
    monkeypatch,
):
    from app.application.tools.workflow import execute_workflow_tool

    monkeypatch.setattr("app.mod_sdk.employee_tool_registry.is_employee_tool", lambda name: False)
    monkeypatch.setattr(
        "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
        lambda *a, **kw: (None, None),
    )
    monkeypatch.setattr(
        "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
        lambda *a, **kw: None,
    )
    with patch("app.application.rbac_app_service.get_rbac_app_service") as service:
        result = json.loads(
            execute_workflow_tool(
                "assign_role",
                {"user_id": 17, "role": "admin", "confirm": True},
                runtime_context={"user_id": "17", "approved": True},
            )
        )
    assert result["error"] == "unknown_tool"
    assert result["success"] is False
    service.assert_not_called()


def test_schema_only_registered_tool_never_reports_business_success(tmp_path):
    from app.application import agent_tool_lifecycle as service
    from app.infrastructure.tenant_scope import tenant_scope

    service.reset_for_tests(str(tmp_path / "tools.sqlite"))
    actor = service.Actor(actor_id="admin", role="admin", employee_id=None, tenant_id=7)
    try:
        tool = service.create_tool(
            actor,
            {
                "tool_key": "schema_only",
                "name": "Schema only",
                "description": "No adapter",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
            },
        )
        service.publish_tool(actor, tool["id"], {"scope": "global"})
        receipt = service.invoke_tool(actor, tool["id"], {"arguments": {"value": "hello"}})
        assert receipt["validated"] == {"value": "hello"}
        assert receipt["success"] is False and receipt["execution_status"] == "not_started"
        started = service.begin_call(actor, tool["id"], {"arguments": {"value": "hello"}})
        assert started["execution_status"] == "not_started"
        assert "status" not in started or started["status"] != "inflight"
        with tenant_scope(7):
            from app.application.tools.workflow import get_workflow_tool_registry

            assert get_workflow_tool_registry({"employee_id": "emp"}) == []
    finally:
        service.reset_for_tests(None)


@pytest.mark.parametrize("key_source", ["header", "body"])
def test_http_and_mod_entry_share_one_request_identity(
    tmp_path, monkeypatch, trusted_actor, key_source
):
    actor = trusted_actor(user_id=17, role="reader", permissions=["products.query"])
    body = {"tool_id": "products", "action": "query", "params": {"keyword": "one"}}
    headers = {"Idempotency-Key": "shared-call-1"} if key_source == "header" else {}
    if key_source == "body":
        body["request_id"] = "shared-call-1"
    context_seen = []

    def invoke(args, **kwargs):
        context_seen.append(kwargs["runtime_context"])
        return json.dumps({"success": True, "execution_state": "completed", "run_id": "run-1"})

    with patch(
        "app.application.tools.registered_capabilities.execute_registered_capability",
        invoke,
    ):
        first = _client(actor).post("/api/tools/execute", json=body, headers=headers)
        second = _client(actor).post(
            "/api/mod/xcagi-planner-bridge/tools/execute", json=body, headers=headers
        )
    assert first.status_code == second.status_code == 200
    assert first.json()["run_id"] == second.json()["data"]["run_id"]
    assert [ctx["idempotency_key"] for ctx in context_seen] == [
        "shared-call-1",
        "shared-call-1",
    ]
    assert [ctx["user_id"] for ctx in context_seen] == ["17", "17"]
    assert context_seen[0]["tenant_id"] == context_seen[1]["tenant_id"]


def test_conflicting_request_keys_are_rejected_before_dispatch(trusted_actor):
    actor = trusted_actor(user_id=17, permissions=["products.query"])
    with patch(
        "app.application.tools.registered_capabilities.execute_registered_capability"
    ) as execute:
        response = _client(actor).post(
            "/api/tools/execute",
            headers={"Idempotency-Key": "one"},
            json={
                "tool_id": "products",
                "action": "query",
                "request_id": "two",
                "params": {},
            },
        )
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_idempotency_key"
    execute.assert_not_called()


def test_removed_skill_route_and_raw_dispatcher_are_absent():
    import importlib.util

    from app.fastapi_routes.tools_execute import router

    assert "/api/skills/execute" not in {route.path for route in router.routes}
    for module in (
        "app.services.tools_execution.executor",
        "app.domain.shared_services.tools_payload_legacy",
    ):
        assert importlib.util.find_spec(module) is None


def test_mcp_action_names_are_not_rewritten_as_host_aliases():
    from app.fastapi_routes.tools_execute import _resolve_tool_request

    assert _resolve_tool_request(
        {"tool_id": "mcp__external", "action": "search", "arguments": {"query": "needle"}}
    ) == ("mcp__external", "search", {"query": "needle"})


def test_openclaw_canonical_entry_requires_current_permission(trusted_actor):
    actor = trusted_actor(role="openclaw-denied", permissions=[])
    with patch("app.application.aiopen.service._openclaw.chat") as upstream:
        response = _client(actor).post(
            "/api/tools/execute",
            json={
                "tool_id": "openclaw",
                "action": "chat",
                "request_id": "denied-openclaw",
                "params": {"message": "hello", "gateway_url": "http://localhost:28789"},
            },
        )
    assert response.status_code == 403, response.text
    assert response.json()["error_code"] == "tool_permission_denied"
    upstream.assert_not_called()


def test_openclaw_requires_approval_and_reuses_original_request(monkeypatch, trusted_actor):
    from uuid import uuid4

    repo = InMemoryAgentRunRepository()
    actor = trusted_actor(role="openclaw-operator", permissions=["tool.openclaw.chat"])
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    body = {
        "tool_id": "openclaw",
        "action": "chat",
        "request_id": uuid4().hex,
        "params": {"message": "hello", "gateway_url": "http://localhost:28789"},
    }
    with patch("app.application.aiopen.service._openclaw.chat") as upstream:
        client = _client(actor)
        first = client.post("/api/tools/execute", json=body)
        second = client.post("/api/tools/execute", json=body)
    assert first.status_code == second.status_code == 202, (first.text, second.text)
    assert first.json()["pending_approval"] is True
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["task_id"] == second.json()["task_id"]
    assert second.json()["deduplicated"] is True
    assert repo.get(first.json()["run_id"]).status == "waiting_user"
    upstream.assert_not_called()
