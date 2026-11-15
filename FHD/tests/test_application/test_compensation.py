"""失败补偿：受信补偿声明、逆序执行、输出取值与服务端开关。"""

from __future__ import annotations

from app.application.agent_orchestrator.compensation import (
    compensation_enabled,
    run_compensations,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import PlanGraph


def _run(*steps: AgentStep, metadata: dict | None = None) -> AgentRun:
    run = AgentRun(user_id="7", message="demo", steps=list(steps))
    run.metadata.update(metadata or {})
    return run


def _plan(metadata: dict | None = None) -> PlanGraph:
    return PlanGraph(plan_id="p1", intent="demo", metadata=dict(metadata or {}))


def test_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_COMPENSATION", raising=False)
    assert compensation_enabled(_plan()) is True
    assert compensation_enabled(None) is False


def test_server_switch_disables(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_COMPENSATION", "0")
    assert compensation_enabled(_plan()) is False


def test_plan_metadata_can_opt_out() -> None:
    assert compensation_enabled(_plan({"compensation": False})) is False


def test_server_switch_off_skips_execution(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_COMPENSATION", "off")
    run = _run(AgentStep(node_id="n1", tool_id="products", action="create", status="completed"))
    calls: list[tuple] = []

    executed = run_compensations(
        run,
        plan=_plan(),
        execute=lambda *args: calls.append(args) or {"success": True},
        runtime_context={},
    )

    assert executed == []
    assert calls == []


def test_runs_declared_compensations_in_reverse_order(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_COMPENSATION", raising=False)
    specs = {
        ("products", "create"): {
            "compensate": {"tool_id": "products", "action": "delete", "params_from": {"id": "id"}}
        },
        ("customers", "update"): {
            "compensate": {"tool_id": "customers", "action": "restore", "params": {}}
        },
    }

    class Guard:
        def get_action_spec(self, tool_id, action):
            return specs.get((tool_id, action))

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(
        AgentStep(
            node_id="n1",
            tool_id="products",
            action="create",
            params={"id": 11},
            idempotent=False,
            status="completed",
        ),
        AgentStep(
            node_id="n2",
            tool_id="customers",
            action="update",
            params={"id": 22},
            idempotent=False,
            status="completed",
        ),
        AgentStep(
            node_id="n3",
            tool_id="reports",
            action="export",
            idempotent=True,
            status="completed",
        ),
    )
    calls: list[tuple] = []

    executed = run_compensations(
        run,
        plan=_plan(),
        execute=lambda tool_id, action, params: (
            calls.append((tool_id, action, params)) or {"success": True}
        ),
        runtime_context={"tenant_id": "2"},
    )

    assert [item["node_id"] for item in executed] == ["n2", "n1"]
    assert [(call[0], call[1]) for call in calls] == [
        ("customers", "restore"),
        ("products", "delete"),
    ]
    assert calls[1][2]["id"] == 11
    assert calls[1][2]["_runtime_context"] == {"tenant_id": "2"}
    assert run.metadata["compensated_node_ids"] == ["n2", "n1"]


def test_output_params_prefer_first_non_empty_path(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_COMPENSATION", raising=False)

    class Guard:
        def get_action_spec(self, tool_id, action):
            return {
                "compensate": {
                    "tool_id": tool_id,
                    "action": "delete",
                    "params_from_output": {"id": ["id", "data.id"]},
                }
            }

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(
        AgentStep(
            node_id="n1",
            tool_id="customers",
            action="create",
            status="completed",
            output={"success": True, "data": {"id": 31}},
        )
    )
    calls: list[tuple] = []

    run_compensations(
        run,
        plan=_plan(),
        execute=lambda tool_id, action, params: (
            calls.append((tool_id, action, params)) or {"success": True}
        ),
        runtime_context={},
    )

    assert calls == [("customers", "delete", {"id": 31, "_runtime_context": {}})]


def test_missing_output_id_keeps_declared_params(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_COMPENSATION", raising=False)

    class Guard:
        def get_action_spec(self, tool_id, action):
            return {
                "compensate": {
                    "tool_id": tool_id,
                    "action": "delete",
                    "params": {"force": False},
                    "params_from_output": {"id": ["data.id"]},
                }
            }

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(AgentStep(node_id="n1", tool_id="products", action="create", status="completed"))
    calls: list[tuple] = []

    run_compensations(
        run,
        plan=_plan(),
        execute=lambda tool_id, action, params: (
            calls.append((tool_id, action, params)) or {"success": True}
        ),
        runtime_context={},
    )

    assert calls == [("products", "delete", {"force": False, "_runtime_context": {}})]


def test_compensation_failure_is_recorded_without_raising(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_COMPENSATION", raising=False)

    class Guard:
        def get_action_spec(self, tool_id, action):
            return {"compensate": {"tool_id": tool_id, "action": "undo"}}

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(AgentStep(node_id="n1", tool_id="products", action="create", status="completed"))

    def broken(tool_id, action, params):
        raise OSError("database unavailable")

    executed = run_compensations(run, plan=_plan(), execute=broken, runtime_context={})

    assert executed[0]["success"] is False
    assert "补偿执行失败" in executed[0]["message"]


def test_compensations_are_not_repeated(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_COMPENSATION", raising=False)

    class Guard:
        def get_action_spec(self, tool_id, action):
            return {"compensate": {"tool_id": tool_id, "action": "undo"}}

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(AgentStep(node_id="n1", tool_id="products", action="create", status="completed"))
    calls: list[tuple] = []
    execute = lambda tool_id, action, params: calls.append((tool_id, action)) or {"success": True}

    run_compensations(run, plan=_plan(), execute=execute, runtime_context={})
    run_compensations(run, plan=_plan(), execute=execute, runtime_context={})

    assert len(calls) == 1


def test_registry_declares_create_compensation() -> None:
    from app.domain.autonomy.autonomy_guard import get_autonomy_guard

    for tool_id in ("customers", "products", "materials"):
        spec = get_autonomy_guard().get_action_spec(tool_id, "create") or {}
        compensate = spec.get("compensate") or {}
        assert compensate.get("tool_id") == tool_id
        assert compensate.get("action") == "delete"
        assert compensate.get("params_from_output", {}).get("id")


def _orchestrator_for_compensation():
    from types import SimpleNamespace

    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    service = AgentOrchestrator.__new__(AgentOrchestrator)
    service._repo = SimpleNamespace(save=lambda run: None)
    return service


def test_compensating_delete_rechecks_real_action_allowlist():
    service = _orchestrator_for_compensation()
    result = service._execute_compensation(
        _run(),
        "products",
        "delete",
        {"id": 7, "_runtime_context": {"employee_tool_allowlist": ["products"]}},
        runtime_context={"employee_tool_allowlist": ["products.create"]},
    )
    assert result["success"] is False
    assert result["error_code"] == "tool_permission_denied"
    assert result["reason"] == "employee_tool_not_granted"


def test_original_create_approval_cannot_approve_compensating_delete():
    service = _orchestrator_for_compensation()
    run = _run(metadata={"approval_receipt": {"status": "approved"}})
    result = service._execute_compensation(
        run,
        "products",
        "delete",
        {"id": 7},
        runtime_context={"employee_tool_allowlist": ["products"], "approved": True},
    )
    assert result["success"] is False
    assert result["error_code"] == "compensation_approval_required"
    assert result["reconciliation_required"] is True
    assert run.steps == []


def test_safe_compensation_obeys_original_cost_budget():
    service = _orchestrator_for_compensation()
    service._step_cost_units = lambda step: 1
    run = _run(metadata={"ai_cost_budget_units": 1, "ai_cost_units_total": 1})
    result = service._execute_compensation(
        run,
        "products",
        "query",
        {},
        runtime_context={},
    )
    assert result == {"success": False, "error_code": "budget_exceeded"}
    assert run.steps == []
    assert run.metadata["ai_cost_units_total"] == 1


def test_safe_compensation_uses_normal_step_boundary_and_stable_identity():
    service = _orchestrator_for_compensation()
    service._step_cost_units = lambda step: 1
    calls = []

    def execute(run, step, *, runtime_context, node_outputs):
        calls.append((step.step_id, dict(runtime_context), dict(step.params)))
        step.output = {"success": True, "data": []}
        step.status = "completed"
        run.status = "running"

    service._execute_step = execute
    run = _run()
    run.status, run.error = "failed", "original failure"
    for _ in range(2):
        result = service._execute_compensation(
            run,
            "products",
            "query",
            {"_runtime_context": {"tenant_id": "attacker"}},
            runtime_context={"tenant_id": "owner"},
        )
        assert result["success"] is True
    assert len(calls) == 1
    assert calls[0][1] == {"tenant_id": "owner"}
    assert calls[0][2] == {}
    assert run.status == "failed"
    assert run.error == "original failure"
    assert len(run.steps) == 1
