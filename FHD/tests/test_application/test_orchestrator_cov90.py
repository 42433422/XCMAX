"""Behavior tests for app.application.employee_runtime.orchestrator.

Targets previously-uncovered lines in EmployeeOrchestrator + helpers:
- _resolve_depends_on manifest-fallback branch
- build_global_collaboration_graph (skip-empty-pid + add)
- _employee_dispatcher success/failure/recoverable-error paths
- EmployeeOrchestrator.depends_on / build_plan / run_upstream /
  run_with_dependencies (skip + execute branches)

All external deps (loader, EmployeeAgent, WorkflowEngine batch) are mocked;
fully offline + deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.employee_runtime import orchestrator as orch_mod
from app.application.employee_runtime.orchestrator import (
    EmployeeOrchestrator,
    _employee_dispatcher,
    _resolve_depends_on,
    build_global_collaboration_graph,
)
from app.application.workflow.types import PlanGraph, WorkflowRunResult
from app.domain.employee.collaboration_graph import CollaborationGraph

# ---------------------------------------------------------------------------
# _resolve_depends_on
# ---------------------------------------------------------------------------


def test_resolve_depends_on_from_config_collaboration():
    """collaboration.depends_on in config takes precedence; dedup + strip."""
    config = {"collaboration": {"depends_on": ["  a  ", "b", "a", ""]}}
    result = _resolve_depends_on({}, config)
    assert result == ["a", "b"]


def test_resolve_depends_on_falls_back_to_manifest():
    """When config has no deps, fall back to manifest.depends_on (lines 36-39)."""
    manifest = {"depends_on": ["upstream1", " upstream2 ", "", "upstream1"]}
    config = {"collaboration": {"depends_on": []}}
    result = _resolve_depends_on(manifest, config)
    assert result == ["upstream1", "upstream2"]


def test_resolve_depends_on_collaboration_not_dict():
    """Non-dict collaboration is ignored, then manifest fallback used."""
    config = {"collaboration": "not-a-dict"}
    manifest = {"depends_on": ["m1"]}
    result = _resolve_depends_on(manifest, config)
    assert result == ["m1"]


def test_resolve_depends_on_empty_everywhere():
    """No deps anywhere returns empty list."""
    assert _resolve_depends_on({}, {}) == []


# ---------------------------------------------------------------------------
# build_global_collaboration_graph
# ---------------------------------------------------------------------------


def test_build_global_collaboration_graph_skips_empty_pid():
    """Pack records without a resolvable pid are skipped (line 50)."""
    packs = [
        {"pack_id": "", "manifest": {}},  # no id -> skipped
        {"pack_id": "emp_a", "manifest": {"depends_on": ["emp_b"]}},
    ]
    with (
        patch.object(orch_mod, "list_installed_pack_records", return_value=packs),
        patch.object(
            orch_mod,
            "parse_employee_config_v2",
            side_effect=lambda m: {"collaboration": {"depends_on": []}},
        ),
    ):
        graph = build_global_collaboration_graph()

    assert isinstance(graph, CollaborationGraph)
    # empty-pid pack excluded; emp_a present with manifest fallback dep
    assert "" not in graph.edges
    assert graph.edges.get("emp_a") == ["emp_b"]


def test_build_global_collaboration_graph_uses_manifest_id_fallback():
    """pack_id missing but manifest.id present -> still added."""
    packs = [{"manifest": {"id": "emp_from_manifest", "depends_on": ["dep_x"]}}]
    with (
        patch.object(orch_mod, "list_installed_pack_records", return_value=packs),
        patch.object(
            orch_mod,
            "parse_employee_config_v2",
            return_value={"collaboration": {"depends_on": []}},
        ),
    ):
        graph = build_global_collaboration_graph()

    assert graph.edges.get("emp_from_manifest") == ["dep_x"]


def test_build_global_collaboration_graph_empty_when_no_packs():
    with patch.object(orch_mod, "list_installed_pack_records", return_value=[]):
        graph = build_global_collaboration_graph()
    assert graph.edges == {}


# ---------------------------------------------------------------------------
# _employee_dispatcher
# ---------------------------------------------------------------------------


def test_employee_dispatcher_success_path():
    """Successful EmployeeAgent.run wraps output with success=True (lines 63-95)."""
    fake_agent = MagicMock()
    fake_agent.run.return_value = {"success": True, "data": "ok"}
    agent_cls = MagicMock(return_value=fake_agent)

    params = {
        "task": "do work",
        "user_id": "7",
        "workspace_root": "/ws",
        "session_id": "sess1",
        "extra_param": "keep_me",
        "_runtime_context": {"node_outputs": {"up1": {"r": 1}}},
    }

    with patch("app.application.employee_runtime.agent.EmployeeAgent", agent_cls):
        result = _employee_dispatcher(tool_id="emp_a", action="run", params=params)

    assert result["success"] is True
    assert result["message"] == "员工协作步骤完成"
    assert result["employee_id"] == "emp_a"
    assert result["output"] == {"success": True, "data": "ok"}

    # EmployeeAgent constructed with tool_id
    agent_cls.assert_called_once_with("emp_a")
    # run() called with task and assembled input_data
    call_args, call_kwargs = fake_agent.run.call_args
    assert call_args[0] == "do work"
    input_data = call_args[1]
    assert input_data["extra_param"] == "keep_me"
    assert input_data["upstream_outputs"] == {"up1": {"r": 1}}
    assert input_data["skip_collaboration"] is True
    # control keys stripped out of input_data
    assert "_runtime_context" not in input_data
    assert "task" not in input_data
    assert call_kwargs["user_id"] == 7
    assert call_kwargs["workspace_root"] == "/ws"
    assert call_kwargs["session_id"] == "sess1"


def test_employee_dispatcher_failure_when_result_not_success():
    """result.success falsy -> success False + failure message (line 89-92)."""
    fake_agent = MagicMock()
    fake_agent.run.return_value = {"success": False}
    agent_cls = MagicMock(return_value=fake_agent)

    with patch("app.application.employee_runtime.agent.EmployeeAgent", agent_cls):
        result = _employee_dispatcher(tool_id="emp_b", action="run", params={})

    assert result["success"] is False
    assert result["message"] == "员工协作步骤失败"
    assert result["employee_id"] == "emp_b"


def test_employee_dispatcher_defaults_task_and_context_from_ctx():
    """task / user_id / workspace pulled from _runtime_context when absent in params."""
    fake_agent = MagicMock()
    fake_agent.run.return_value = {"success": True}
    agent_cls = MagicMock(return_value=fake_agent)

    params = {
        "_runtime_context": {
            "task": "ctx-task",
            "user_id": "3",
            "workspace_root": "/ctx-ws",
            "session_id": "ctx-sess",
            "node_outputs": {},
        }
    }
    with patch("app.application.employee_runtime.agent.EmployeeAgent", agent_cls):
        _employee_dispatcher(tool_id="emp_c", action="run", params=params)

    call_args, call_kwargs = fake_agent.run.call_args
    assert call_args[0] == "ctx-task"
    assert call_kwargs["user_id"] == 3
    assert call_kwargs["workspace_root"] == "/ctx-ws"
    assert call_kwargs["session_id"] == "ctx-sess"


def test_employee_dispatcher_default_task_when_nothing_provided():
    """No task anywhere -> synthesized '协作步骤：<tool_id>' default."""
    fake_agent = MagicMock()
    fake_agent.run.return_value = {"success": True}
    agent_cls = MagicMock(return_value=fake_agent)

    with patch("app.application.employee_runtime.agent.EmployeeAgent", agent_cls):
        _employee_dispatcher(tool_id="emp_d", action="run", params={})

    call_args, _ = fake_agent.run.call_args
    assert call_args[0] == "协作步骤：emp_d"


def test_employee_dispatcher_recoverable_error_returns_error_dict():
    """EmployeeAgent.run raising a recoverable error is caught (lines 96-98)."""
    fake_agent = MagicMock()
    fake_agent.run.side_effect = RuntimeError("boom-x" * 200)  # long -> truncated
    agent_cls = MagicMock(return_value=fake_agent)

    with patch("app.application.employee_runtime.agent.EmployeeAgent", agent_cls):
        result = _employee_dispatcher(tool_id="emp_e", action="run", params={})

    assert result["success"] is False
    assert result["employee_id"] == "emp_e"
    assert "boom-x" in result["error"]
    # error string truncated to <= 400 chars
    assert len(result["error"]) <= 400


def test_employee_dispatcher_runtime_context_not_dict():
    """_runtime_context that's not a dict -> empty ctx, empty node_outputs."""
    fake_agent = MagicMock()
    fake_agent.run.return_value = {"success": True}
    agent_cls = MagicMock(return_value=fake_agent)

    params = {"_runtime_context": "nope", "task": "t"}
    with patch("app.application.employee_runtime.agent.EmployeeAgent", agent_cls):
        _employee_dispatcher(tool_id="emp_f", action="run", params=params)

    call_args, call_kwargs = fake_agent.run.call_args
    input_data = call_args[1]
    assert input_data["upstream_outputs"] == {}
    assert call_kwargs["user_id"] == 0


# ---------------------------------------------------------------------------
# EmployeeOrchestrator construction + depends_on
# ---------------------------------------------------------------------------


def _make_orch(edges: dict[str, list[str]] | None = None) -> EmployeeOrchestrator:
    graph = CollaborationGraph(edges=dict(edges or {}))
    return EmployeeOrchestrator(graph=graph)


def test_orchestrator_init_uses_provided_graph():
    g = CollaborationGraph(edges={"a": ["b"]})
    orch = EmployeeOrchestrator(graph=g)
    assert orch.graph is g


def test_orchestrator_init_builds_graph_when_none():
    """Default graph built via build_global_collaboration_graph."""
    with patch.object(
        orch_mod, "build_global_collaboration_graph", return_value=CollaborationGraph()
    ) as mock_build:
        orch = EmployeeOrchestrator()
    mock_build.assert_called_once()
    assert isinstance(orch.graph, CollaborationGraph)


def test_depends_on_adds_local_edges():
    """Local deps from manifest/config are added to graph and returned (lines 111-115)."""
    orch = _make_orch()
    manifest = {}
    config = {"collaboration": {"depends_on": ["dep1", "dep2"]}}
    result = orch.depends_on("emp_root", manifest, config)
    assert result == ["dep1", "dep2"]
    assert orch.graph.edges.get("emp_root") == ["dep1", "dep2"]


def test_depends_on_no_local_returns_existing_edges():
    """No local deps -> returns existing graph edges (line 115 fallback)."""
    orch = _make_orch(edges={"emp_root": ["pre_existing"]})
    result = orch.depends_on("emp_root", {}, {})
    assert result == ["pre_existing"]


def test_depends_on_no_local_no_existing_returns_local_empty():
    """No local + no edges -> returns the (empty) local list."""
    orch = _make_orch()
    result = orch.depends_on("emp_x", {}, {})
    assert result == []


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


def test_build_plan_returns_none_when_no_dependencies():
    """execution_order of len<=1 -> no plan (lines 120-123)."""
    orch = _make_orch(edges={"solo": []})
    assert orch.build_plan("solo", "task") is None


def test_build_plan_with_dependencies_builds_graph():
    """Plan built with upstream + root nodes; root keeps real task (lines 124-157)."""
    orch = _make_orch(edges={"root": ["up1", "up2"], "up1": [], "up2": []})
    plan = orch.build_plan("root", "real task", include_root=True)

    assert isinstance(plan, PlanGraph)
    assert plan.plan_id.startswith("emp-collab-root-")
    assert plan.metadata == {"root_employee_id": "root", "include_root": True}

    node_ids = {n.node_id for n in plan.nodes}
    assert node_ids == {"root", "up1", "up2"}

    root_node = next(n for n in plan.nodes if n.node_id == "root")
    assert root_node.params["task"] == "real task"
    # root depends on its direct deps within exec order
    assert set(root_node.depends_on) == {"up1", "up2"}

    up_node = next(n for n in plan.nodes if n.node_id == "up1")
    assert up_node.params["task"] == "上游协作：up1"
    assert up_node.depends_on == []


def test_build_plan_exclude_root_drops_root_node():
    """include_root=False removes root from exec order (lines 128-130)."""
    orch = _make_orch(edges={"root": ["up1"], "up1": []})
    plan = orch.build_plan("root", "task", include_root=False)
    assert plan is not None
    node_ids = {n.node_id for n in plan.nodes}
    assert "root" not in node_ids
    assert node_ids == {"up1"}
    assert plan.metadata["include_root"] is False


def test_build_plan_exclude_root_keeps_single_upstream():
    """include_root=False with one upstream keeps a non-empty exec order.

    (lines 128-130: filter root out, exec_order remains non-empty so a plan is
    still produced. The empty-after-filter branch is defensive/unreachable
    because execution_order dedups the root.)
    """
    orch = _make_orch(edges={"root": ["dep"], "dep": []})
    plan = orch.build_plan("root", "task", include_root=False)
    assert plan is not None
    assert {n.node_id for n in plan.nodes} == {"dep"}


def test_build_plan_logs_warning_on_cycle():
    """A detected cycle logs a warning but still produces a plan (lines 125-126)."""
    orch = _make_orch(edges={"root": ["a"], "a": ["root"]})
    with patch.object(orch_mod.logger, "warning") as mock_warn:
        plan = orch.build_plan("root", "task")
    assert plan is not None
    assert mock_warn.called


# ---------------------------------------------------------------------------
# run_with_dependencies / run_upstream
# ---------------------------------------------------------------------------


def test_run_with_dependencies_skipped_when_no_plan():
    """No deps -> skipped result, engine not invoked (lines 189-194)."""
    orch = _make_orch(edges={"solo": []})
    orch._engine = MagicMock()
    result = orch.run_with_dependencies("solo", "task")
    assert result == {"skipped": True, "reason": "no depends_on", "employee_id": "solo"}
    orch._engine._run_batch.assert_not_called()


def test_run_with_dependencies_executes_and_summarizes():
    """Plan present -> _run_batch invoked, summary mapped (lines 196-216)."""
    orch = _make_orch(edges={"root": ["up1"], "up1": []})

    from app.application.workflow.types import NodeExecutionResult

    node_result = NodeExecutionResult(
        node_id="up1",
        success=True,
        tool_id="up1",
        action="run",
        output={"r": 1},
    )
    run_result = WorkflowRunResult(
        plan_id="emp-collab-root-deadbeef",
        success=True,
        node_results=[node_result],
        final_context={"node_outputs": {"up1": {"r": 1}}},
        message="工作流执行完成",
    )
    fake_engine = MagicMock()
    fake_engine._run_batch.return_value = run_result
    orch._engine = fake_engine

    result = orch.run_with_dependencies("root", "the task", runtime_context={"custom": "v"})

    assert result["skipped"] is False
    assert result["employee_id"] == "root"
    assert result["success"] is True
    assert result["message"] == "工作流执行完成"
    assert result["node_outputs"] == {"up1": {"r": 1}}
    assert result["node_results"] == [
        {"node_id": "up1", "success": True, "tool_id": "up1", "error": ""}
    ]

    # ctx passed to engine seeded with task/employee_id + preserves custom
    _, ctx_arg = fake_engine._run_batch.call_args[0]
    assert ctx_arg["custom"] == "v"
    assert ctx_arg["task"] == "the task"
    assert ctx_arg["employee_id"] == "root"


def test_run_with_dependencies_handles_missing_final_context():
    """final_context None / no node_outputs -> empty node_outputs (line 206 guards)."""
    orch = _make_orch(edges={"root": ["up1"], "up1": []})
    run_result = WorkflowRunResult(
        plan_id="pid",
        success=False,
        node_results=[],
        final_context={},
        message="failed",
    )
    fake_engine = MagicMock()
    fake_engine._run_batch.return_value = run_result
    orch._engine = fake_engine

    result = orch.run_with_dependencies("root", "task")
    assert result["success"] is False
    assert result["node_outputs"] == {}
    assert result["node_results"] == []


def test_run_upstream_delegates_with_include_root_false():
    """run_upstream forwards to run_with_dependencies(include_root=False) (line 169)."""
    orch = _make_orch()
    with patch.object(orch, "run_with_dependencies", return_value={"ok": True}) as mock_rwd:
        result = orch.run_upstream(
            "root",
            "task",
            manifest={"m": 1},
            config={"c": 2},
            runtime_context={"rc": 3},
        )
    assert result == {"ok": True}
    mock_rwd.assert_called_once_with(
        "root",
        "task",
        manifest={"m": 1},
        config={"c": 2},
        runtime_context={"rc": 3},
        include_root=False,
    )
