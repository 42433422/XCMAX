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
        "/api/skills/execute",
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
    with patch("app.application.facades.tools_facade.run_archive_tools_execute") as legacy:
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
            "/api/tools/execute", json={"tool_id": "aiopen", "action": "api_catalog", "params": {}}
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
    from app.fastapi_routes.tools_execute import tool_route_agent_payload

    run = SimpleNamespace(
        run_id="run-1",
        status="blocked",
        final_output={
            "node_outputs": {
                "write": {
                    "success": False,
                    "outcome": "unknown",
                    "reconciliation_required": True,
                    "retryable": True,
                    "error_code": "tool_timeout_unknown",
                    "traceback": "private",
                }
            }
        },
    )
    result = tool_route_agent_payload(run, "write")
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True
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
    monkeypatch.setattr(
        "app.application.agent_tool_lifecycle.execute_if_registered", lambda *a: None
    )
    context = {
        "tenant_id": "7",
        "user_id": "17",
        "_actor_authorization": {"proof": "fixture"},
    }
    raw = planner_tools.execute_planner_workflow_tool("test_write", {}, runtime_context=context)
    assert json.loads(raw)["outcome"] == "unknown"
    native.assert_called_once()
    assert native.call_args.kwargs["runtime_context"] is context


def test_registry_unavailable_cannot_fall_through_to_another_implementation(
    monkeypatch,
):
    from app.application.tools.workflow import execute_workflow_tool

    monkeypatch.setattr(
        "app.application.agent_tool_lifecycle.execute_if_registered",
        Mock(side_effect=OSError("offline")),
    )
    native = Mock()
    monkeypatch.setattr("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool", native)
    result = json.loads(execute_workflow_tool("test_write", {}))
    assert result["error_code"] == "tool_receipt_unavailable"
    assert result["execution_state"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True
    native.assert_not_called()


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
        result = json.loads(execute_workflow_tool(tool_name, arguments))
    assert result["success"] is False
    assert result["error_code"] == "tool_identity_required"
    assert result["execution_status"] == "not_started"
    raw.assert_not_called()


@pytest.mark.parametrize(
    "state,expected",
    [("unknown", "unknown"), ("waiting_approval", "waiting_approval"), ("queued", "unknown")],
)
def test_capability_wrapper_keeps_pending_receipt_so_employee_cannot_replay(
    monkeypatch,
    tmp_path,
    state,
    expected,
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator import AgentOrchestrator, SQLAlchemyAgentRunRepository
    from app.application.tools.registered_capabilities import (
        execute_registered_capability,
    )

    receipt = {
        "success": state != "unknown",
        "execution_state": state,
        "retryable": True,
    }
    if state == "unknown":
        receipt.update(outcome="unknown", reconciliation_required=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'capability-unknown.db'}")
    factory = sessionmaker(bind=engine)
    execute = Mock(return_value=receipt)

    def service():
        return AgentOrchestrator(
            repository=SQLAlchemyAgentRunRepository(session_factory=factory),
            tool_executor=SimpleNamespace(execute=execute),
        )

    monkeypatch.setattr("app.application.agent_orchestrator.AgentOrchestrator", service)
    context = {"user_id": "17", "session_id": "session", "turn_id": "turn", "call_id": "call"}
    try:
        results = [
            json.loads(
                execute_registered_capability(
                    {"tool_id": "print", "action": "list", "params": {}}, runtime_context=context
                )
            )
            for _ in range(2)
        ]
        assert results[0]["agent_run_id"] == results[1]["agent_run_id"]
        for result in results:
            # A mocked queue acknowledgement has no durable admission evidence.
            # Keep its original state and require reconciliation without replay.
            assert result["execution_state"] == expected
            assert result["retryable"] is False and result["success"] is False
            if expected == "unknown":
                assert result["outcome"] == "unknown"
                assert result["reconciliation_required"] is True
                if state == "queued":
                    assert result["result"]["execution_state"] == "queued"
                    assert result["result"]["agent_status"] == "blocked"
            else:
                assert result["result"]["execution_state"] == state
                assert result.get("outcome") != "unknown"
                assert not result.get("reconciliation_required")
        execute.assert_called_once()
    finally:
        engine.dispose()


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
    with patch("app.application.tools.rbac_tools._get_service") as service:
        result = json.loads(
            execute_workflow_tool(
                "assign_role",
                {"user_id": 17, "role": "admin", "confirm": True},
                runtime_context={"user_id": "17", "approved": True},
            )
        )
    assert result["error_code"] == "tool_contract_unavailable"
    assert result["execution_status"] == "not_started" and result["retryable"] is False
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
        with tenant_scope(7):
            runtime_result = json.loads(
                service.execute_if_registered(
                    "schema_only", {"value": "hello"}, {"employee_id": "emp"}
                )
            )
        assert runtime_result["success"] is False
    finally:
        service.reset_for_tests(None)


def test_capability_wrapper_keeps_unknown_receipt_so_employee_cannot_replay(
    monkeypatch,
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.unified_task import UnifiedTaskResult
    from app.application.tools.registered_capabilities import (
        execute_registered_capability,
    )

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
                runtime_context={"user_id": "17"},
            )
        )
    execute.assert_not_called()
    assert result["agent_run_id"] == "original-run"
    assert result["deduplicated"] is True
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True and result["success"] is False
