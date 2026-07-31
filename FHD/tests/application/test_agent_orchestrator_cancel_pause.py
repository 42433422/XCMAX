"""AgentOrchestrator cancel/pause。"""

from __future__ import annotations

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository


def _waiting_run(repo: InMemoryAgentRunRepository) -> AgentRun:
    run = AgentRun(user_id="u1", message="m")
    run.status = "waiting_user"
    run.steps = [
        AgentStep(
            node_id="n1",
            tool_id="business_db",
            action="write",
            status="waiting_user",
            risk="medium",
        )
    ]
    repo.save(run)
    return run


def test_cancel_run_marks_cancelled():
    repo = InMemoryAgentRunRepository()
    run = _waiting_run(repo)
    out = AgentOrchestrator(repository=repo).cancel_run(run.run_id)
    assert out is not None
    assert out.status == "cancelled"
    assert out.steps[0].status == "cancelled"


def test_pause_run_marks_blocked():
    repo = InMemoryAgentRunRepository()
    run = _waiting_run(repo)
    out = AgentOrchestrator(repository=repo).pause_run(run.run_id)
    assert out is not None
    assert out.status == "blocked"
    assert out.steps[0].status == "blocked"
