import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentRun


@pytest.mark.parametrize(
    "method,status",
    [("resume_run", "paused"), ("stage_resume_run", "paused"), ("retry_run", "failed")],
)
def test_continuation_rejects_tenant_change_before_state_or_command_writes(method, status):
    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="task", status=status)
    run.metadata["runtime_context"] = {"tenant_id": "1"}
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    orchestrator = AgentOrchestrator(repository=repository)
    with pytest.raises(ValueError, match="租户"):
        getattr(orchestrator, method)(run.run_id, runtime_context={"tenant_id": "2"})
    assert repository.get(run.run_id).to_dict() == before
    assert repository.latest_task_control(run.run_id) is None
    assert len(repository.list_recent()) == 1
