"""Legacy persisted workspace hints cannot survive real run resumption."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.employee_runtime.task_continuity import ledger_path, load_employee_task_ledger
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("has_plan", [False, True])
def test_sqlite_legacy_run_resume_uses_server_workspace(
    tmp_path, monkeypatch, trusted_actor, has_plan
):
    actor = trusted_actor(user_id=17, role="admin")
    server = tmp_path / "server"
    outside = tmp_path / "outside"
    server.mkdir()
    outside.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(server))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.sqlite'}")
    factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    run = AgentRun(
        user_id="17",
        message="resume legacy task",
        status="waiting_user",
        steps=[
            AgentStep(
                node_id="employee",
                tool_id="employee",
                action="execute",
                status="waiting_user",
                params={
                    "employee_id": "clerk",
                    "task": "start continuity",
                    "continuity_action": "start",
                    "goal": "verify persisted root boundary",
                    "workspace_root": str(outside),
                    "_runtime_context": {"workspace_root": str(outside)},
                    "input": {"workspace_root": str(outside), "continuity_action": "start"},
                },
            )
        ],
        metadata={"runtime_context": {**actor.context, "workspace_root": str(outside)}},
    )
    if has_plan:
        step = run.steps[0]
        plan = PlanGraph(
            plan_id="legacy-workspace-plan",
            intent="employee",
            todo_steps=[],
            nodes=[
                WorkflowNode(
                    node_id=step.node_id,
                    tool_id=step.tool_id,
                    action=step.action,
                    params=step.params,
                    risk=step.risk,
                    idempotent=step.idempotent,
                )
            ],
        )
        AgentOrchestrator(repository=repository)._apply_plan(run, plan)
        run.status = "waiting_user"
        run.steps[0].status = "waiting_user"
    repository.save(run)
    engine.dispose()
    # Reopen the database: this is not a reference to a previously mutated run.
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'runs.sqlite'}")
    fresh = SQLAlchemyAgentRunRepository(
        session_factory=sessionmaker(bind=fresh_engine), auto_create=False
    )
    stored = fresh.get(run.run_id)
    assert stored.metadata["runtime_context"]["workspace_root"] == str(outside)
    assert stored.steps[0].params["_runtime_context"]["workspace_root"] == str(outside)
    try:
        finished = AgentOrchestrator(repository=fresh).continue_run(
            run.run_id, approved_by="17", runtime_context={"workspace_root": str(outside)}
        )
        if not has_plan:
            assert finished.status == "blocked"
            assert not finished.tool_calls
            assert not ledger_path(server).exists()
            assert list(outside.iterdir()) == []
            return
        assert finished.status == "completed", finished.to_dict()
        assert finished.tool_calls and finished.tool_calls[0].output["success"]
        assert ledger_path(server).is_file()
        assert load_employee_task_ledger(server)["tasks"]
        assert list(outside.iterdir()) == []
        assert fresh.get(run.run_id).status == "completed"
    finally:
        fresh_engine.dispose()
