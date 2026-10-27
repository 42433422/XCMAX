"""Hold durable ownership through a business transaction, preserving Mod database routing."""

import copy
from contextlib import contextmanager
from contextvars import ContextVar

from app.application.agent_orchestrator.worker_repository import (
    WorkerLeaseLost as WorkerLeaseLost,
)
from app.application.agent_orchestrator.worker_repository import lock_execution_claim

_claim = ContextVar("agent_business_write_claim", default=None)


@contextmanager
def worker_claim_scope(repository, execution, owner_id):
    token = _claim.set((repository, copy.deepcopy(execution), owner_id))
    try:
        yield
    finally:
        _claim.reset(token)


def _lock_claim(db, execution, owner_id):
    lock_execution_claim(
        db,
        run_id=execution.run_id,
        owner_id=owner_id,
        execution_count=execution.execution_count,
    )


def capture_worker_claim():
    """Pass only the server-held fence across spawn, never caller runtime fields."""
    claim = _claim.get()
    if claim is None:
        return None
    _, execution, owner_id = claim
    return (execution.run_id, owner_id, execution.execution_count)


@contextmanager
def restore_worker_claim(reference):
    if reference is None:
        yield
        return
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )
    from app.application.agent_orchestrator.task_execution_models import (
        AgentTaskExecution,
    )

    run_id, owner_id, count = reference
    execution = AgentTaskExecution(
        run_id=run_id, task_id="", user_id="", execution_count=count
    )
    with worker_claim_scope(SQLAlchemyAgentRunRepository(), execution, owner_id):
        yield


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
