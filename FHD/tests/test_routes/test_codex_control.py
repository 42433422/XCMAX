from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import AgentOrchestrator, set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
    set_task_execution_repository_for_tests,
)
from app.fastapi_routes.domains.agent.agent_routes import router
from app.infrastructure.auth.agent_principal import require_agent_principal
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from app.infrastructure.codex.tools import CodexToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

_PRIVATE_CONTROL_MARKERS = (
    "/srv/private/codex/control.json",
    "control-token-canary",
    "control-stack-canary",
)


@pytest.fixture
def control_setup(trusted_actor, monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["tool.customers.create", "product.view"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(repository)
    set_task_execution_repository_for_tests(InMemoryTaskExecutionRepository())
    run = AgentRun(
        user_id=str(actor.user_id), message="原任务", status="running", intent="codex.runtime"
    )
    run.metadata.update(
        runtime_context=actor.context,
        _codex_system_prompt="server instructions",
        _codex_input_data={"source": "original"},
        runtime_completion_mode="auto",
        runtime_allowed_actions=None,
    )
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract

    contract = build_goal_contract(run)
    run.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(run)
    store = CodexBindingStore(repository)
    grant = store.create(run.run_id)
    orchestrator = AgentOrchestrator(repository=repository)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_agent_principal] = lambda: actor.principal
    with TestClient(app) as client:
        yield SimpleNamespace(
            actor=actor,
            store=store,
            run=run,
            grant=grant,
            orchestrator=orchestrator,
            app=app,
            client=client,
        )
    set_agent_run_repository_for_tests(None)
    set_task_execution_repository_for_tests(None)


def test_public_run_does_not_leak_callback_hashes_or_actor_proofs(control_setup):
    setup = control_setup
    response = setup.client.get(f"/api/agent/runs/{setup.run.run_id}")
    assert response.status_code == 200
    for value in (
        "token_hashes",
        "_actor_authorization",
        "_codex_system_prompt",
        "server instructions",
        setup.actor.context["_actor_authorization"]["proof"],
    ):
        assert value not in response.text
    assert setup.store.authenticate(setup.grant.mcp_token).run_id == setup.run.run_id
    assert (
        setup.store.get(setup.run.run_id).run.metadata["_codex_system_prompt"]
        == "server instructions"
    )


def test_cancel_revokes_root_and_cancels_pending_child(control_setup):
    setup = control_setup
    bridge = CodexToolBridge(setup.store, setup.orchestrator)
    receipt = bridge.invoke(
        setup.grant.mcp_token,
        "execute_action",
        {
            "schema_digest": bridge.invoke(
                setup.grant.mcp_token,
                "capability_describe",
                {"tool_id": "customers", "action": "create"},
            )["capability"]["schema_digest"],
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    response = setup.client.post(f"/api/agent/runs/{setup.run.run_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "cancelled"
    assert setup.store.repository.get(receipt["run_id"]).status == "cancelled"
    with pytest.raises(CodexBindingError):
        setup.store.authenticate(setup.grant.mcp_token)


def test_pause_resume_uses_saved_instructions_and_original_codex_run(control_setup, monkeypatch):
    setup = control_setup
    seen = []

    def runtime(**kwargs):
        seen.append(kwargs)
        setup.store.update(
            setup.run.run_id, lambda run, metadata: setattr(run, "status", "completed")
        )
        return {"ok": True, "runtime": "codex", "execution_state": "completed"}

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", runtime)
    monkeypatch.setattr(
        AgentOrchestrator, "stage_resume_run", lambda *a, **k: pytest.fail("native parent resume")
    )
    assert setup.client.post(f"/api/agent/runs/{setup.run.run_id}/pause").status_code == 200
    response = setup.client.post(
        f"/api/agent/runs/{setup.run.run_id}/resume",
        json={
            "request_id": "resume-one",
            "message": "补充原任务信息",
            "system_prompt": "untrusted",
        },
    )
    assert response.status_code == 200, response.text
    assert len(seen) == 1
    assert seen[0]["run_id"] == setup.run.run_id
    assert seen[0]["system_prompt"] == "server instructions"
    assert seen[0]["input_data"] == {"source": "original"}
    assert seen[0]["runtime_context"]["turn_id"] == "resume-one"
    assert (
        seen[0]["runtime_context"]["_actor_authorization"]
        == setup.actor.context["_actor_authorization"]
    )
    assert setup.store.repository.latest_task_control(setup.run.run_id).action == "resume"


def test_retry_is_dispatched_to_codex_without_native_plan_replay(control_setup, monkeypatch):
    setup = control_setup
    setup.store.close(setup.run.run_id, "failed")
    setup.store.update(setup.run.run_id, lambda run, metadata: setattr(run, "status", "failed"))
    seen = []
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **kwargs: (
            seen.append(kwargs)
            or {
                "ok": True,
                "runtime": "codex",
                "execution_state": "completed",
            }
        ),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "retry_run", lambda *a, **k: pytest.fail("native parent retry")
    )
    response = setup.client.post(f"/api/agent/runs/{setup.run.run_id}/retry")
    assert response.status_code == 200, response.text
    assert seen[0]["run_id"] == setup.run.run_id


def test_unknown_parent_never_resumes_either_engine(control_setup, monkeypatch):
    setup = control_setup
    setup.store.close(setup.run.run_id, "interrupted")
    setup.store.update(
        setup.run.run_id, lambda run, metadata: run.metadata.update(non_retryable=True)
    )
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **kwargs: pytest.fail("unknown replay"),
    )
    for operation in ("resume", "retry"):
        response = setup.client.post(f"/api/agent/runs/{setup.run.run_id}/{operation}", json={})
        assert response.status_code == 409
        assert response.json()["error_code"] == "reconciliation_required"


@pytest.mark.parametrize("state", ["reserved", "unknown"])
def test_unsettled_model_request_prevents_control_resume(control_setup, monkeypatch, state):
    setup = control_setup
    setup.store.close(setup.run.run_id, "interrupted")
    setup.store.update(
        setup.run.run_id,
        lambda run, metadata: metadata.update(model_requests={"m1": {"state": state}}),
    )
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **kwargs: pytest.fail("model replay"),
    )
    response = setup.client.post(f"/api/agent/runs/{setup.run.run_id}/resume", json={})
    assert response.status_code == 409
    assert response.json()["error_code"] == "reconciliation_required"


def test_runtime_context_override_and_foreign_principal_are_rejected(control_setup, trusted_actor):
    setup = control_setup
    setup.client.post(f"/api/agent/runs/{setup.run.run_id}/pause")
    response = setup.client.post(
        f"/api/agent/runs/{setup.run.run_id}/resume",
        json={
            "runtime_context": {"tenant_id": "999"},
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "identity_override"
    foreign = trusted_actor(tenant_id=99)
    setup.app.dependency_overrides[require_agent_principal] = lambda: foreign.principal
    response = setup.client.post(f"/api/agent/runs/{setup.run.run_id}/cancel")
    assert response.status_code == 403
    assert setup.store.get(setup.run.run_id).run.status == "paused"


@pytest.mark.parametrize(
    "error_code,expected_code,message",
    [
        (
            "reconciliation_required",
            "reconciliation_required",
            "原任务执行结果尚需核对，暂不能恢复或重试",
        ),
        (
            "owner_changed",
            "owner_changed",
            "任务身份或授权已变化，请确认当前账号与原任务的业务范围",
        ),
        (
            "identity_override",
            "identity_override",
            "续跑不能修改原任务的运行范围，请从原任务继续操作",
        ),
        ("run_inactive", "run_inactive", "终态任务不能恢复；重新执行业务请提交新任务"),
        (
            "binding_conflict",
            "binding_conflict",
            "任务操作未完成，请刷新原任务并核对状态、授权和执行结果",
        ),
        (None, "runtime_control_denied", "任务操作未完成，请刷新原任务并核对状态、授权和执行结果"),
        (
            "traceback private internal details",
            "runtime_control_denied",
            "任务操作未完成，请刷新原任务并核对状态、授权和执行结果",
        ),
        (
            ["private internal error code"],
            "runtime_control_denied",
            "任务操作未完成，请刷新原任务并核对状态、授权和执行结果",
        ),
    ],
)
def test_control_errors_keep_internal_details_out_of_http_responses(
    control_setup, monkeypatch, caplog, error_code, expected_code, message
):
    setup = control_setup
    assert setup.client.post(f"/api/agent/runs/{setup.run.run_id}/pause").status_code == 200
    detail = " ".join(_PRIVATE_CONTROL_MARKERS)
    failure = CodexBindingError(error_code, detail) if error_code else ValueError(detail)
    looked_up = []

    def fail_binding(self, run_id):
        looked_up.append(run_id)
        raise failure

    monkeypatch.setattr(CodexBindingStore, "get", fail_binding)
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.run_runtime_task",
        lambda **kwargs: pytest.fail("denied control cannot restart the task"),
    )
    with caplog.at_level("WARNING", logger="app.fastapi_routes.domains.agent.route_support"):
        response = setup.client.post(f"/api/agent/runs/{setup.run.run_id}/resume", json={})
    assert response.status_code == 409
    assert response.json()["error_code"] == expected_code
    assert looked_up == [setup.run.run_id]
    for marker in _PRIVATE_CONTROL_MARKERS:
        assert marker not in response.text
    assert response.json()["message"] == message
    assert response.json()["success"] is False
    assert setup.store.repository.get(setup.run.run_id).status == "paused"
    assert any(record.exc_info and record.exc_info[1] is failure for record in caplog.records)


@pytest.mark.parametrize(
    "binding_error", [False, True], ids=["released-parent-budget", "paused-child-binding-error"]
)
def test_child_cannot_retry_or_resume_after_releasing_parent_budget(
    control_setup, monkeypatch, caplog, binding_error
):
    setup = control_setup
    bridge = CodexToolBridge(setup.store, setup.orchestrator)
    receipt = bridge.invoke(
        setup.grant.mcp_token,
        "execute_action",
        {
            "schema_digest": bridge.invoke(
                setup.grant.mcp_token,
                "capability_describe",
                {"tool_id": "customers", "action": "create"},
            )["capability"]["schema_digest"],
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    child = setup.store.repository.get(receipt["run_id"])
    if binding_error:
        assert setup.client.post(f"/api/agent/runs/{child.run_id}/pause").status_code == 200
    else:
        child.status = "failed"
        setup.store.repository.save(child)
        setup.store.receipt_snapshot(setup.run.run_id)
    expected_status = "paused" if binding_error else "failed"
    assert setup.store.repository.get(child.run_id).status == expected_status
    monkeypatch.setattr(AgentOrchestrator, "retry_run", lambda *a, **k: pytest.fail("child replay"))
    denied = setup.client.post(f"/api/agent/runs/{child.run_id}/retry")
    assert denied.status_code == 409
    assert denied.json()["error_code"] == "codex_child_retry_forbidden"
    assert denied.json()["parent_run_id"] == setup.run.run_id
    assert denied.json()["message"] == "请先核对原父任务；不能绕过父任务预算重新执行子任务"
    looked_up = []
    failure = CodexBindingError("binding_missing", " ".join(_PRIVATE_CONTROL_MARKERS))
    if binding_error:

        def fail_parent_binding(self, run_id):
            looked_up.append(run_id)
            raise failure

        monkeypatch.setattr(CodexBindingStore, "get", fail_parent_binding)
    with caplog.at_level("WARNING", logger="app.fastapi_routes.domains.agent.route_support"):
        denied = setup.client.post(f"/api/agent/runs/{child.run_id}/resume", json={})
    assert denied.status_code == 409
    assert denied.json()["error_code"] == "codex_parent_control_required"
    assert denied.json()["parent_run_id"] == setup.run.run_id
    for marker in _PRIVATE_CONTROL_MARKERS:
        assert marker not in denied.text
    assert denied.json()["message"] == "请从原父任务恢复，原子任务授权或预算不能单独重建"
    assert setup.store.repository.get(child.run_id).status == expected_status
    if binding_error:
        assert looked_up == [setup.run.run_id]
        assert any(record.exc_info and record.exc_info[1] is failure for record in caplog.records)


def test_parent_resume_preserves_original_child_approval_and_reservation(
    control_setup, monkeypatch
):
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )

    setup = control_setup
    set_task_execution_repository_for_tests(
        SQLAlchemyTaskExecutionRepository(session_factory=setup.actor.factory)
    )
    bridge = CodexToolBridge(setup.store, setup.orchestrator)
    receipt = bridge.invoke(
        setup.grant.mcp_token,
        "execute_action",
        {
            "schema_digest": bridge.invoke(
                setup.grant.mcp_token,
                "capability_describe",
                {"tool_id": "customers", "action": "create"},
            )["capability"]["schema_digest"],
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    assert setup.client.post(f"/api/agent/runs/{setup.run.run_id}/pause").status_code == 200
    denied = setup.client.post(f"/api/agent/runs/{receipt['run_id']}/resume", json={})
    assert denied.status_code == 409

    def runtime(**kwargs):
        setup.store.update(
            setup.run.run_id, lambda run, metadata: setattr(run, "status", "waiting_user")
        )
        return {"ok": False, "runtime": "codex", "execution_state": "waiting_user"}

    monkeypatch.setattr("app.application.agent_runtime.gateway.run_runtime_task", runtime)
    response = setup.client.post(
        f"/api/agent/runs/{setup.run.run_id}/resume", json={"request_id": "parent-resume"}
    )
    assert response.status_code == 202, response.text
    child = setup.store.repository.get(receipt["run_id"])
    assert child.status == "waiting_user"
    assert child.tool_calls == []
    call = setup.store.get(setup.run.run_id).metadata["calls"]["write"]
    assert call["reservation_state"] == "held"
    assert call["reservation_units"] > 0
