"""Hold durable ownership through a business transaction, preserving Mod database routing."""

from contextlib import contextmanager
from contextvars import ContextVar

from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
from app.db.models.agent import AgentTaskExecutionRecord

_claim = ContextVar("agent_business_write_claim", default=None)


@contextmanager
def worker_claim_scope(repository, execution, owner_id):
    token = _claim.set((repository, execution, owner_id))
    try:
        yield
    finally:
        _claim.reset(token)


def _lock_claim(db, execution, owner_id):
    owned = (
        db.query(AgentTaskExecutionRecord)
        .filter(
            AgentTaskExecutionRecord.run_id == execution.run_id,
            AgentTaskExecutionRecord.state == "claimed",
            AgentTaskExecutionRecord.lease_owner == owner_id,
            AgentTaskExecutionRecord.execution_count == execution.execution_count,
            AgentTaskExecutionRecord.lease_expires_at > utc_now_iso(),
        )
        .update({AgentTaskExecutionRecord.lease_owner: owner_id}, synchronize_session=False)
    )
    if owned != 1:
        raise WorkerLeaseLost("worker lease expired or replaced before business write")


@contextmanager
def worker_write_guard(business_db):
    claim = _claim.get()
    if claim is None:
        yield
        return
    repository, execution, owner_id = claim
    with repository.transaction() as ownership_db:
        if ownership_db.get_bind() is business_db.get_bind():
            # Same database: acquire the lock on the business session itself.
            # A second SQLite writer connection would deadlock against it.
            _lock_claim(business_db, execution, owner_id)
            yield
        else:
            # Separate Mod database: keep the ownership lock until the caller
            # commits/rolls back its business transaction. Never reroute its data.
            _lock_claim(ownership_db, execution, owner_id)
            yield
