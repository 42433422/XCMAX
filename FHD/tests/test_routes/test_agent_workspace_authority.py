"""HTTP workspace hints cannot become employee filesystem authority."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.employee_runtime.task_continuity import ledger_path
from app.application.tools.workflow_tools.dispatch import execute_registered_workflow_tool
from app.fastapi_routes.domains.agent import agent_routes
from app.fastapi_routes.domains.agent.route_support import (
    authenticated_runtime_context,
    without_runtime_identity,
)
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal


@pytest.fixture
def roots(tmp_path, monkeypatch):
    server, outside = tmp_path / "server", tmp_path / "outside"
    server.mkdir()
    outside.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(server))
    from app.application.agent_orchestrator import (
        InMemoryAgentRunRepository,
        set_agent_run_repository_for_tests,
    )

    set_agent_run_repository_for_tests(InMemoryAgentRunRepository())
    yield server, outside
    set_agent_run_repository_for_tests(None)


def _dispatch(context, outside, monkeypatch, *, registered=False):
    import app.mod_sdk.employee_tool_registry as registry

    monkeypatch.setattr(registry, "is_employee_tool", lambda name: name == "test_clerk")
    monkeypatch.setattr(registry, "resolve_tool_to_pack_id", lambda name: "clerk")
    monkeypatch.setattr(registry, "build_employee_tools_status", lambda: {})
    params = {
        "task": "safe ledger start",
        "continuity_action": "start",
        "workspace_root": str(outside),
        "employee_id": "clerk",
        "goal": "verify boundary",
        "_runtime_context": context,
    }
    result = execute_registered_workflow_tool(
        "employee" if registered else "test_clerk", "execute", params
    )
    assert result["success"], result


@pytest.mark.parametrize("registered", [False, True])
def test_real_http_run_context_to_employee_ledger(roots, monkeypatch, registered):
    server, outside = roots
    captured = {}

    def start_run(self, **kwargs):
        captured.update(kwargs["runtime_context"])
        return SimpleNamespace(status="completed")

    monkeypatch.setattr(agent_routes.AgentOrchestrator, "start_run", start_run)
    monkeypatch.setattr(agent_routes, "_run_response", lambda run, **kw: {"success": True})
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.dependency_overrides[require_agent_principal] = lambda: AgentPrincipal(
        user_id="17", tenant_id="29"
    )
    response = TestClient(app).post(
        "/api/agent/runs",
        json={
            "message": "check workspace",
            "auto_execute": False,
            "runtime_context": {
                "workspace_root": str(outside),
                "user_id": "forged",
                "tenant_id": "forged",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert captured["workspace_root"] == str(server)
    assert captured["user_id"] == "17"
    assert captured["tenant_id"] == "29"
    _dispatch(captured, outside, monkeypatch, registered=registered)
    assert ledger_path(server).is_file()
    assert list(outside.iterdir()) == []


def test_persisted_root_rebound_and_turn_cannot_replace_it(roots, monkeypatch):
    from app.application.agent_orchestrator.tool_permission import (
        merge_turn_context,
        seal_server_context,
    )

    server, outside = roots
    context = seal_server_context({"workspace_root": str(outside), "user_id": "17"})
    context = merge_turn_context(context, {"workspace_root": str(outside)})
    assert context["workspace_root"] == str(server)
    _dispatch(context, outside, monkeypatch)
    assert ledger_path(server).is_file()
    assert list(outside.iterdir()) == []


def test_shared_ingress_sanitizer_strips_root_without_mutating_input(roots):
    server, outside = roots
    raw = {"workspace_root": str(outside), "source": "chat"}
    assert without_runtime_identity(raw) == {"source": "chat"}
    assert raw["workspace_root"] == str(outside)
    context = authenticated_runtime_context(raw, AgentPrincipal(user_id="17", tenant_id="29"))
    assert context["workspace_root"] == str(server)


def test_internal_explicit_workspace_stays_supported(roots, monkeypatch):
    _, outside = roots
    _dispatch({"workspace_root": str(outside)}, outside, monkeypatch)
    assert ledger_path(outside).is_file()


def test_tools_body_uses_same_server_root_and_discards_nested_override(roots, monkeypatch):
    import app.infrastructure.auth.agent_principal as auth
    from app.fastapi_routes.tools_execute import _authenticated_tool_body

    _, outside = roots
    monkeypatch.setattr(
        auth, "require_agent_principal", lambda *a, **kw: AgentPrincipal(user_id="17")
    )
    body = _authenticated_tool_body(
        None,
        {
            "params": {
                "workspace_root": str(outside),
                "_runtime_context": {"workspace_root": str(outside)},
            }
        },
    )
    assert "workspace_root" not in body["params"]
    assert body["params"]["_runtime_context"]["workspace_root"] == str(roots[0])


def test_planner_body_root_cannot_select_directory(roots, monkeypatch):
    import app.mod_sdk.planner_tools as planner

    server, outside = roots
    captured = {}

    def execute(name, args, workspace, **kwargs):
        captured["workspace"] = workspace
        return '{"success": true}'

    monkeypatch.setattr(planner, "resolve_planner_tool_executor", lambda: execute)
    planner.execute_planner_tool_from_body({"tool_name": "test", "workspace_root": str(outside)})
    assert captured["workspace"] == str(server)


def test_trigger_payload_root_cannot_select_directory(roots, monkeypatch):
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.employee_runtime.triggers import _make_handler
    from app.domain.employee.trigger_binding import TriggerBinding

    server, outside = roots
    captured = {}

    def run(self, task, payload, **kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(EmployeeAgent, "run", run)
    monkeypatch.setattr(
        "app.application.employee_runtime.metrics.record_employee_trigger", lambda *a: None
    )
    handler = _make_handler("clerk", TriggerBinding(employee_id="clerk"))
    handler(SimpleNamespace(event_type="test", payload={"workspace_root": str(outside)}))
    assert captured["workspace_root"] == str(server)


def test_body_only_root_is_removed_before_employee_continuity(roots, monkeypatch):
    import app.application.employee_runtime.task_continuity as continuity
    from app.application.employee_runtime.agent import EmployeeAgent

    _, outside = roots
    captured = {}

    def probe(employee_id, task, payload, **kwargs):
        captured.update(kwargs)
        assert "workspace_root" not in payload
        return {"success": False, "error": "workspace required"}

    monkeypatch.setattr(continuity, "maybe_continue_employee_task", probe)
    result = EmployeeAgent("clerk").run("task", {"workspace_root": str(outside)})
    assert not result["success"]
    assert captured["workspace_root"] is None
