"""Live resource availability is checked for the full plan before its first effect."""

from unittest.mock import Mock

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator, _execution_registry
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _node(node_id, tool_id, action, dependencies=()):
    spec = get_tool_action_spec(tool_id, action)
    return WorkflowNode(
        node_id,
        tool_id,
        action,
        params={},
        risk=spec.risk,
        idempotent=spec.idempotent,
        depends_on=list(dependencies),
    )


def test_disabled_later_resource_rejects_before_any_earlier_dispatch(trusted_actor, monkeypatch):
    actor = trusted_actor(role="admin", tier="admin")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", "1")
    registry = _execution_registry(actor.context)
    assert "computer_observe" in registry["desktop_automation"]["actions"]
    plan = PlanGraph(
        "live-preflight",
        "query then inspect",
        nodes=[
            _node("query", "customers", "query"),
            _node("inspect", "desktop_automation", "computer_observe", ["query"]),
        ],
    )
    dispatcher = Mock()
    runner = AgentOrchestrator(
        repository=SQLAlchemyAgentRunRepository(session_factory=actor.factory),
        tool_executor=dispatcher,
    )
    run = runner.start_run_from_plan(
        user_id=str(actor.user_id),
        message="query then inspect",
        plan=plan,
        runtime_context=actor.context,
        auto_execute=False,
    )
    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", "0")
    assert runner._preflight_resume_plan(run, actor.context)
    runner._execute_ready_steps(run, runtime_context=actor.context)
    assert run.status == "blocked" and "未授权" in run.error
    assert "desktop_automation" in run.error
    dispatcher.execute_with_deadline.assert_not_called()
    assert run.tool_calls == []


def test_live_registry_rejects_disconnected_resource(trusted_actor, monkeypatch):
    actor = trusted_actor(role="admin", tier="admin")
    monkeypatch.setattr(
        "app.application.tools.kellai.connection_scope", lambda *_a, **_kw: {"available": True}
    )
    assert "kellai" in _execution_registry(actor.context)
    monkeypatch.setattr(
        "app.application.tools.kellai.connection_scope", lambda *_a, **_kw: {"available": False}
    )
    assert "kellai" not in _execution_registry(actor.context)


def test_denied_later_node_preserves_reason_without_earlier_dispatch(trusted_actor, monkeypatch):
    actor = trusted_actor(role="admin", tier="admin")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", "1")
    context = {**actor.context, "employee_tool_allowlist": ["customers"]}
    plan = PlanGraph(
        "permission-preflight",
        "query then inspect",
        nodes=[
            _node("query", "customers", "query"),
            _node("inspect", "desktop_automation", "computer_observe", ["query"]),
        ],
    )
    dispatcher = Mock()
    runner = AgentOrchestrator(
        repository=SQLAlchemyAgentRunRepository(session_factory=actor.factory),
        tool_executor=dispatcher,
    )
    run = runner.start_run_from_plan(
        user_id=str(actor.user_id),
        message="query then inspect",
        plan=plan,
        runtime_context=context,
        auto_execute=False,
    )
    assert runner._preflight_resume_plan(run, context) == "计划权限复核未通过，拒绝续跑"
    runner._execute_ready_steps(run, runtime_context=context)
    assert run.status == "blocked"
    assert run.steps[1].output["error_code"] == "tool_permission_denied"
    assert run.steps[1].output["reason"] == "employee_tool_not_granted"
    audit = next(e for e in run.events if e.event_type == "workflow.plan_audit_rejected")
    assert audit.data["error_code"] == "tool_permission_denied"
    assert audit.data["execution_started"] is False
    assert all(step.status == "pending" for step in run.steps)
    assert run.tool_calls == []
    dispatcher.execute_with_deadline.assert_not_called()
