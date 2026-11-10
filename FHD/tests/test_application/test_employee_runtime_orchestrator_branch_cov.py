"""Employee dependency graphs execute through the single AgentRun runtime."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from app.application.employee_runtime.orchestrator import (
    EmployeeOrchestrator,
    _resolve_depends_on,
    build_global_collaboration_graph,
)
from app.domain.employee.collaboration_graph import CollaborationGraph


def test_resolve_depends_on_prefers_config_and_deduplicates():
    assert _resolve_depends_on(
        {"depends_on": ["manifest"]},
        {"collaboration": {"depends_on": [" dep-a ", "dep-a", "dep-b", None]}},
    ) == ["dep-a", "dep-b"]


def test_resolve_depends_on_falls_back_to_manifest():
    assert _resolve_depends_on({"depends_on": ["m1", "m2"]}, {}) == ["m1", "m2"]


def test_build_global_graph_uses_installed_employee_packs():
    with (
        patch(
            "app.application.employee_runtime.orchestrator.list_installed_pack_records",
            return_value=[{"pack_id": "root", "manifest": {"depends_on": ["worker"]}}],
        ),
        patch(
            "app.application.employee_runtime.orchestrator.parse_employee_config_v2",
            return_value={},
        ),
    ):
        graph = build_global_collaboration_graph()
    assert graph.edges == {"root": ["worker"]}


def test_plan_uses_registered_employee_context_action_and_dependency_edges():
    graph = CollaborationGraph()
    graph.add("root", ["worker"])
    graph.add("worker", [])

    plan = EmployeeOrchestrator(graph).build_plan("root", "check inventory")

    assert plan is not None
    assert [(n.tool_id, n.action) for n in plan.nodes] == [
        ("employee", "context"),
        ("employee", "context"),
    ]
    assert plan.nodes[1].depends_on == ["worker"]
    assert plan.nodes[1].params["task"] == "check inventory"


def test_run_without_dependencies_skips():
    result = EmployeeOrchestrator(CollaborationGraph()).run_with_dependencies("root", "task")
    assert result == {"skipped": True, "reason": "no depends_on", "employee_id": "root"}


def test_run_requires_authenticated_actor_before_creating_agent_run():
    graph = CollaborationGraph()
    graph.add("root", ["worker"])
    result = EmployeeOrchestrator(graph).run_with_dependencies("root", "task")
    assert result["success"] is False
    assert result["error_code"] == "employee_actor_required"


def test_run_with_dependencies_uses_agent_run_and_returns_receipts():
    graph = CollaborationGraph()
    graph.add("root", ["worker"])
    run = NS(
        plan_id="stable-plan",
        run_id="run-1",
        status="completed",
        error=None,
        final_output={"message": "done", "node_outputs": {"worker": {"ok": True}}},
        steps=[NS(node_id="worker", status="completed", tool_id="employee", error=None)],
    )
    orchestrator = MagicMock()
    orchestrator.start_run_from_plan.return_value = run

    with patch(
        "app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator
    ):
        result = EmployeeOrchestrator(graph).run_with_dependencies(
            "root",
            "task",
            runtime_context={"user_id": 7, "run_id": "parent-1", "task_id": "task-1"},
        )

    assert result["success"] is True
    assert result["agent_run_id"] == "run-1"
    assert result["node_outputs"] == {"worker": {"ok": True}}
    orchestrator.start_run_from_plan.assert_called_once()
    kwargs = orchestrator.start_run_from_plan.call_args.kwargs
    assert kwargs["auto_execute"] is True
    assert kwargs["runtime_context"]["parent_run_id"] == "parent-1"
    orchestrator.attach_child_run.assert_called_once_with("parent-1", run)


def test_failed_agent_run_is_not_reported_as_success():
    graph = CollaborationGraph()
    graph.add("root", ["worker"])
    run = NS(
        plan_id="stable-plan",
        run_id="run-2",
        status="failed",
        error="tool failure",
        final_output={},
        steps=[NS(node_id="worker", status="failed", tool_id="employee", error="tool failure")],
    )
    orchestrator = MagicMock()
    orchestrator.start_run_from_plan.return_value = run
    with patch(
        "app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator
    ):
        result = EmployeeOrchestrator(graph).run_with_dependencies(
            "root", "task", runtime_context={"user_id": 7}
        )
    assert result["success"] is False
    assert result["message"] == "tool failure"
    assert result["node_results"][0]["success"] is False
