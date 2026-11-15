"""失败补偿：受信补偿声明、逆序执行与默认关闭。"""

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


def test_disabled_without_plan_opt_in() -> None:
    run = _run(AgentStep(node_id="n1", tool_id="products", action="update", status="completed"))
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
        plan=_plan({"compensation": True}),
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


def test_compensation_failure_is_recorded_without_raising(monkeypatch) -> None:
    class Guard:
        def get_action_spec(self, tool_id, action):
            return {"compensate": {"tool_id": tool_id, "action": "undo"}}

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(AgentStep(node_id="n1", tool_id="products", action="create", status="completed"))

    def broken(tool_id, action, params):
        raise OSError("database unavailable")

    executed = run_compensations(
        run,
        plan=_plan({"compensation": True}),
        execute=broken,
        runtime_context={},
    )

    assert executed[0]["success"] is False
    assert "补偿执行失败" in executed[0]["message"]


def test_compensations_are_not_repeated(monkeypatch) -> None:
    class Guard:
        def get_action_spec(self, tool_id, action):
            return {"compensate": {"tool_id": tool_id, "action": "undo"}}

    monkeypatch.setattr("app.domain.autonomy.autonomy_guard.get_autonomy_guard", lambda: Guard())
    run = _run(AgentStep(node_id="n1", tool_id="products", action="create", status="completed"))
    calls: list[tuple] = []
    execute = lambda tool_id, action, params: calls.append((tool_id, action)) or {"success": True}

    run_compensations(run, plan=_plan({"compensation": True}), execute=execute, runtime_context={})
    run_compensations(run, plan=_plan({"compensation": True}), execute=execute, runtime_context={})

    assert len(calls) == 1
    assert compensation_enabled(_plan({"compensation": True})) is True
    assert compensation_enabled(None) is False
