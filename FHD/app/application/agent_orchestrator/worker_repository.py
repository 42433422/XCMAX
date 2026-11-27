"""Bind worker run writes to the durable queue claim that authorized execution."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository


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
            AgentTaskExecutionRecord.state.in_(("running", "claimed")),
            AgentTaskExecutionRecord.lease_owner == owner_id,
            AgentTaskExecutionRecord.execution_count == execution_count,
            AgentTaskExecutionRecord.lease_expires_at > utc_now_iso(),
        )
        .update({AgentTaskExecutionRecord.lease_owner: owner_id}, synchronize_session=False)
    )
    if owned != 1:
        raise WorkerLeaseLost("worker lease expired or replaced before business write")


class ClaimedRunRepository:
    def __init__(self, repository: SQLAlchemyAgentRunRepository, execution, owner_id):
        self._repository = repository
        self._execution = copy.deepcopy(execution)
        self._owner_id = owner_id

    @contextmanager
    def _claim_transaction(self, run_id):
        if run_id != self._execution.run_id:
            raise WorkerLeaseLost("worker attempted to save another run")
        with self._repository.transaction() as db:
            lock_execution_claim(
                db,
                run_id=run_id,
                owner_id=self._owner_id,
                execution_count=self._execution.execution_count,
            )
            yield db

    def save(self, run):
        with self._claim_transaction(run.run_id) as db:
            self._repository.save_in_session(db, run)
        return copy.deepcopy(run)

    def save_if_unchanged(self, run, previous) -> bool:
        if previous.run_id != run.run_id:
            return False
        with self._claim_transaction(run.run_id) as db:
            return self._repository.save_if_unchanged_in_session(db, run, previous)

    def __getattr__(self, name):
        return getattr(self._repository, name)
