"""A second controller cancels an active run at its next tool boundary."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.workflow.types import PlanGraph, WorkflowNode


@pytest.mark.parametrize("persistent", [False, True])
def test_cancel_during_tool_preserves_completed_step_and_skips_next(
    tmp_path, monkeypatch, persistent
):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    entered, release = Event(), Event()
    calls = []

    class ControlledTool:
        def execute(self, step, *, runtime_context):
            calls.append(step.node_id)
            entered.set()
            assert release.wait(30), "test must release the in-flight tool"
            return {"success": True, "data": {"finished": step.node_id}}

    database_url = "sqlite:///" + str(tmp_path / "runs.sqlite3")
    if persistent:
        from app.application.agent_orchestrator.run_sql_repository import (
            SQLAlchemyAgentRunRepository,
        )

        engine = create_engine(database_url)
        factory = sessionmaker(bind=engine)
        repo = SQLAlchemyAgentRunRepository(session_factory=factory)
        repo.list_recent()  # Initialize schema before concurrent access.
    else:
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
            if persistent:
                code = """
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
engine = create_engine(os.environ["TEST_RUN_DB"])
repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
run = AgentOrchestrator(repository=repo).cancel_run(os.environ["TEST_RUN_ID"], requested_by="u1")
assert run is not None
assert repo.latest_task_control(run.run_id).status == "requested"
engine.dispose()
"""
                env = os.environ.copy()
                env.update(TEST_RUN_DB=database_url, TEST_RUN_ID=active.run_id)
                child = subprocess.run(
                    [sys.executable, "-c", code],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                assert child.returncode == 0, child.stderr
            else:
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

    if persistent:
        restored = SQLAlchemyAgentRunRepository(session_factory=factory)
        assert restored.get(run.run_id).status == "cancelled"
        assert restored.latest_task_control(run.run_id).status == "applied"
        engine.dispose()
