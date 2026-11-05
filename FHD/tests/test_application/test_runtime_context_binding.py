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


@pytest.mark.parametrize(
    "metadata",
    [
        {"non_retryable": True},
        {"recovery": {"state": "manual_reconciliation_required"}},
    ],
)
def test_internal_retry_cannot_replay_unreconciled_work(monkeypatch, metadata):
    from unittest.mock import Mock

    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="external write", status="blocked", metadata=metadata)
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    orchestrator = AgentOrchestrator(repository=repository)
    start = Mock(return_value=AgentRun(user_id="owner", message="duplicate", status="running"))
    monkeypatch.setattr(orchestrator, "start_run", start)
    with pytest.raises(ValueError, match="核对"):
        orchestrator.retry_run(run.run_id, requested_by="owner", auto_execute=False)
    start.assert_not_called()
    assert repository.get(run.run_id).to_dict() == before
    assert len(repository.list_recent()) == 1


@pytest.mark.parametrize("method", ["resume_run", "stage_resume_run"])
def test_paused_unreconciled_run_cannot_resume(monkeypatch, method):
    from unittest.mock import Mock

    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="unknown write", status="paused")
    run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    orchestrator = AgentOrchestrator(repository=repository)
    execute = Mock()
    monkeypatch.setattr(orchestrator, "_execute_with_durable_lease", execute)
    with pytest.raises(ValueError, match="核对"):
        getattr(orchestrator, method)(run.run_id, requested_by="owner")
    execute.assert_not_called()
    assert repository.get(run.run_id).to_dict() == before
    assert repository.latest_task_control(run.run_id) is None
