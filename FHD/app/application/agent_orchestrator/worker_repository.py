"""Bind worker run writes to the durable queue claim that authorized execution."""

import copy


class WorkerLeaseLost(RuntimeError):
    pass


def lock_execution_claim(db, *, run_id, owner_id, execution_count):
    """Hold the queue row's conditional write lock until the caller commits."""
    from app.application.agent_orchestrator.run_models import utc_now_iso
    from app.db.models.agent import AgentTaskExecutionRecord

    owned = (
        db.query(AgentTaskExecutionRecord)
        .filter(
            AgentTaskExecutionRecord.run_id == run_id,
            AgentTaskExecutionRecord.state == "claimed",
            AgentTaskExecutionRecord.lease_owner == owner_id,
            AgentTaskExecutionRecord.execution_count == execution_count,
            AgentTaskExecutionRecord.lease_expires_at > utc_now_iso(),
        )
        .update(
            {AgentTaskExecutionRecord.lease_owner: owner_id}, synchronize_session=False
        )
    )
    if owned != 1:
        raise WorkerLeaseLost("worker lease expired or replaced before business write")


class ClaimedRunRepository:
    def __init__(self, repository, execution, owner_id):
        self._repository = repository
        self._execution = copy.deepcopy(execution)
        self._owner_id = owner_id

    def save(self, run):
        if run.run_id != self._execution.run_id:
            raise WorkerLeaseLost("worker attempted to save another run")
        return self._repository.save_claimed(
            run,
            owner_id=self._owner_id,
            execution_count=self._execution.execution_count,
        )

    def __getattr__(self, name):
        return getattr(self._repository, name)
