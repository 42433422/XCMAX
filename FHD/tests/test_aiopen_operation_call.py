"""AIOPEN must consume the same live grants, task identity and business receipt."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.aiopen import service
from app.application.aiopen.generated_tools import operation_call
from app.domain.aiopen.principal import ScreenPrincipal
from app.infrastructure.aiopen.principal_context import execution_context_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize(
    "state,label", [("waiting_input", "等待输入"), ("blocked", "已阻断"), ("accepted", "已受理")]
)
def test_mcp_text_preserves_known_wait_in_nested_receipt(state, label):
    from app.application.aiopen.result_text import format_tool_result_text

    text = format_tool_result_text(
        "operation_call",
        {
            "success": True,
            "execution_state": "completed",
            "operation_id": "capability.fixture.action",
            "run_id": "original-run",
            "result": {"success": False, "execution_state": state},
        },
    )
    assert label in text
    assert "已完成" not in text and "待核对" not in text
    assert "original-run" in text


@pytest.fixture
def bound_key(trusted_actor, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    monkeypatch.setitem(service.AIOPEN_STATE, "runtime_keys", {})
    actor = trusted_actor(permissions=["customer.view", "customer.create"])

    def issue(scopes=None, expires_at=None):
        return service.generate_api_key(
            principal=ScreenPrincipal(str(actor.user_id), str(actor.tenant_id)),
            scopes=scopes or ["*"],
            expires_at=expires_at,
            execution_context=actor.context,
        )

    return actor, issue


def test_key_grant_never_exceeds_current_role_and_revocation_is_live(bound_key):
    from app.db.models.permission import Role

    actor, issue = bound_key
    issued = issue(["capability.business_db.read"])
    assert "execution_context" not in issued
    context = service.resolve_api_key_execution_context(issued["key"])
    assert actor_tool_denial("business_db", "read", context, {"entity": "customers"}) is None
    assert actor_tool_denial("customers", "create", context)["reason"] == "credential_scope_denied"
    with actor.factory.begin() as db:
        db.query(Role).filter_by(name="user").one().permissions = []
    assert (
        actor_tool_denial("business_db", "read", context, {"entity": "customers"})["reason"]
        == "permission_denied"
    )
    assert service.revoke_api_key(issued["key"])
    assert service.resolve_api_key_execution_context(issued["key"]) is None
    assert (
        actor_tool_denial("business_db", "read", context, {"entity": "customers"})["reason"]
        == "credential_scope_denied"
    )


def test_key_scope_cannot_be_replaced_in_durable_context(bound_key):
    _, issue = bound_key
    issued = issue(["capability.business_db.read"])
    context = service.resolve_api_key_execution_context(issued["key"])
    context["_credential_authorization"]["scopes"] = ["*"]
    assert actor_tool_denial("customers", "create", context)["reason"] == "credential_scope_denied"


def test_expired_key_and_logged_out_actor_cannot_execute(bound_key):
    from app.db.models.user import Session

    actor, issue = bound_key
    assert service.resolve_api_key_execution_context(issue(expires_at=1)["key"]) is None
    active = issue()
    context = service.resolve_api_key_execution_context(active["key"])
    with actor.factory.begin() as db:
        db.delete(db.get(Session, actor.session_row_id))
    assert service.resolve_api_key_execution_context(active["key"]) is None
    assert (
        actor_tool_denial("business_db", "read", context, {"entity": "customers"})["reason"]
        == "credential_scope_denied"
    )


@pytest.mark.asyncio
async def test_raw_http_tool_is_removed():
    result = await service.invoke_tool(
        "api_call", {"path": "/api/customers", "method": "DELETE"}, FastAPI()
    )
    assert result["code"] == "UNKNOWN_TOOL"
    assert "api_call" not in {item["name"] for item in service.aiopen_manifest()["tools"]}


def test_request_key_mismatch_stops_before_executor(bound_key, monkeypatch):
    _, issue = bound_key
    context = service.resolve_api_key_execution_context(issue()["key"])
    context["idempotency_key"] = "original"
    executor = Mock()
    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability", executor
    )
    with execution_context_scope(context):
        result = operation_call(
            FastAPI(), {"operation_id": "capability.business_db.read", "request_id": "changed"}
        )
    assert result["code"] == "INVALID_ARGUMENT"
    executor.assert_not_called()


def test_rest_and_mcp_keep_original_business_receipt(bound_key, monkeypatch):
    from app.fastapi_routes import ai_open

    actor, issue = bound_key
    issued = issue()
    expected = {
        "success": False,
        "execution_state": "waiting_approval",
        "pending_approval": True,
        "run_id": "original-run",
        "agent_run_id": "original-run",
        "task_id": "original-task",
        "approval_request_id": "original-approval",
    }
    calls = []

    def execute(args, *, runtime_context):
        calls.append((args, runtime_context))
        assert runtime_context["user_id"] == str(actor.user_id)
        assert runtime_context["idempotency_key"] == "stable-request"
        assert (
            runtime_context["_credential_authorization"]["credential_id"] == issued["credential_id"]
        )
        return json.dumps(expected)

    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability", execute
    )
    trace = Mock(
        side_effect=AssertionError("business receipt must not be replaced with a trace run")
    )
    monkeypatch.setattr(ai_open, "_trace_aiopen_tool_call", trace)
    app = FastAPI()
    app.include_router(ai_open.router)
    client = TestClient(app, headers={"X-AIOPEN-Key": issued["key"]})
    arguments = {
        "operation_id": "capability.business_db.read",
        "params": {"entity": "customers"},
        "request_id": "stable-request",
    }
    rest = client.post(
        "/api/aiopen/invoke", json={"tool": "operation_call", "args": arguments}
    ).json()
    mcp = client.post(
        "/api/aiopen/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "operation_call", "arguments": arguments},
        },
    ).json()["result"]
    assert rest["run_id"] == mcp["_meta"]["run_id"] == "original-run"
    assert rest["task_id"] == mcp["structuredContent"]["task_id"] == "original-task"
    assert mcp["_meta"]["approval_request_id"] == "original-approval"
    assert mcp["_meta"]["request_id"] == "stable-request"
    assert all(
        call[0] == {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}}
        for call in calls
    )
    assert len(calls) == 2
    trace.assert_not_called()


def test_environment_key_cannot_borrow_browser_session(bound_key, monkeypatch):
    from app.fastapi_routes import ai_open

    actor, _ = bound_key
    monkeypatch.setenv("AIOPEN_API_KEY", "unbound-service-key")
    execute = Mock()
    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability", execute
    )
    app = FastAPI()
    app.include_router(ai_open.router)
    with TestClient(app) as client:
        response = client.post(
            "/api/aiopen/invoke",
            headers={**actor.headers, "X-AIOPEN-Key": "unbound-service-key"},
            json={
                "tool": "operation_call",
                "args": {
                    "operation_id": "capability.business_db.read",
                    "params": {"entity": "customers"},
                },
            },
        )
    assert response.json()["error_code"] == "tool_identity_required"
    execute.assert_not_called()


def test_discovery_is_narrowed_by_api_key_scope(bound_key):
    from app.application.capability_catalog import discover_capabilities

    _, issue = bound_key
    context = service.resolve_api_key_execution_context(
        issue(["capability.business_db.read"])["key"]
    )
    result = discover_capabilities(context)
    assert result["success"] is True
    assert [row["capability_id"] for row in result["capabilities"]] == ["business_db.read"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("market_user_id", 999),
        ("market_is_admin", True),
        ("account_kind", "admin"),
        ("impersonating_market_user_id", 999),
        ("tenant_id", 999),
    ],
)
def test_live_market_session_change_invalidates_bound_task(trusted_actor, field, value):
    from app.db.models.user import Session
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    actor = trusted_actor(permissions=["customer.view"])
    assert validate_actor_context(actor.context) is None
    with actor.factory.begin() as db:
        setattr(db.get(Session, actor.session_row_id), field, value)
    assert validate_actor_context(actor.context)["error_code"] == "tool_identity_required"


def test_chat_goal_uses_original_task_and_rejects_changed_request(bound_key, tmp_path, monkeypatch):
    from app.application.agent_orchestrator import task_dispatcher
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_runtime import gateway
    from app.application.aiopen.generated_tools import execute_message
    from app.infrastructure.xiaox import queued_runtime
    from app.infrastructure.xiaox.policy import ModelRoute, RuntimeSettings

    actor, issue = bound_key
    context = service.resolve_api_key_execution_context(issue()["key"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    settings = RuntimeSettings(
        engine="xiaox",
        route=ModelRoute(
            base_url="http://127.0.0.1:19112/v1",
            model="queue-fixture",
            provider_id="fixture",
            upstream_vendor="fixture",
            context_window=32000,
            max_output_tokens=4000,
        ),
        runtime_root=tmp_path / "codex-runtime",
    )
    monkeypatch.setattr(gateway, "runtime_settings", lambda: settings)
    monkeypatch.setattr(gateway, "get_agent_run_repository", lambda: repository)
    monkeypatch.setattr(queued_runtime, "get_task_execution_repository", lambda: queue)
    notified = Mock()
    monkeypatch.setattr(task_dispatcher, "notify_agent_task_dispatcher", notified)
    runtime = Mock(side_effect=AssertionError("durable admission must not execute a model"))
    monkeypatch.setattr(gateway, "run_xiaox_agent", runtime)
    with execution_context_scope(context):
        first = execute_message({"message": "读取客户", "request_id": "same-goal"})
        second = execute_message({"message": "读取客户", "request_id": "same-goal"})
        conflict = execute_message({"message": "改为创建客户", "request_id": "same-goal"})
    other_credential = service.resolve_api_key_execution_context(
        issue(["capability.business_db.read"])["key"]
    )
    with execution_context_scope(other_credential):
        foreign_key = execute_message({"message": "读取客户", "request_id": "same-goal"})
    assert foreign_key["error_code"] == "owner_changed"
    assert foreign_key["success"] is False
    assert first["execution_state"] == second["execution_state"] == "queued", first
    assert first["run_id"] == second["run_id"]
    assert first["task_id"] == second["task_id"]
    assert first["success"] is False and first["pending_approval"] is False
    assert second["deduplicated"] is True
    assert conflict["error_code"] == "task_idempotency_conflict"
    notified.assert_called_once()
    runtime.assert_not_called()
    run = repository.get(first["run_id"])
    assert run.intent == "xiaox.runtime" and run.metadata["runtime_type"] == "xiaox"
    assert run.tool_calls == [] and run.message == "读取客户"
    assert (
        run.metadata["runtime_context"]["_credential_authorization"]
        == context["_credential_authorization"]
    )
    assert run.metadata["task_context"]["task_id"] == first["task_id"]
    assert queue.get(first["run_id"]).execution_count == 0
