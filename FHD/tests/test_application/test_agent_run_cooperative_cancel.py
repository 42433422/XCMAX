"""A second controller cancels an active run at its next tool boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.workflow.types import PlanGraph, WorkflowNode


def test_cancel_during_tool_preserves_completed_step_and_skips_next(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    entered, release = Event(), Event()
    calls = []

    class ControlledTool:
        def execute(self, step, *, runtime_context):
            calls.append(step.node_id)
            entered.set()
            assert release.wait(5), "test must release the in-flight tool"
            return {"success": True, "data": {"finished": step.node_id}}

    repo = InMemoryAgentRunRepository()
    worker = AgentOrchestrator(repository=repo, tool_executor=ControlledTool())
    controller = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id="cancel-boundary",
        intent="test",
        nodes=[
            WorkflowNode(
                node_id="first", tool_id="products", action="query", risk="low", idempotent=True
            ),
            WorkflowNode(
                node_id="second",
                tool_id="products",
                action="query",
                risk="low",
                idempotent=True,
                depends_on=["first"],
            ),
        ],
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            worker.start_run_from_plan,
            user_id="u1",
            message="两步查询",
            plan=plan,
            auto_execute=True,
        )
        try:
            assert entered.wait(5)
            active = repo.list_recent(user_id="u1")[0]
            assert active.metadata["execution"]["state"] == "active"
            controller.cancel_run(active.run_id, requested_by="u1")
            assert repo.latest_task_control(active.run_id).status == "requested"
        finally:
            release.set()
        run = future.result(timeout=5)
    assert calls == ["first"]
    assert run.status == "cancelled"
    assert [s.status for s in run.steps] == ["completed", "skipped"]
    assert run.final_output["completed_step_ids"] == [run.steps[0].step_id]
    assert repo.get(run.run_id).status == "cancelled"
    assert repo.latest_task_control(run.run_id).status == "applied"
    assert run.metadata["execution"]["state"] == "idle"
