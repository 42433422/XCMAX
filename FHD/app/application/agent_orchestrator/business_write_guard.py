"""Hold durable ownership through a business transaction, preserving Mod database routing."""

import copy
from contextlib import contextmanager
from contextvars import ContextVar

from app.application.agent_orchestrator.worker_repository import (
    WorkerLeaseLost as WorkerLeaseLost,
)
from app.application.agent_orchestrator.worker_repository import lock_execution_claim

_claim = ContextVar("agent_business_write_claim", default=None)
_elt_step = ContextVar("agent_elt_checkpoint_step", default="")


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


@contextmanager
def worker_claim_guard():
    """Hold the current server-owned queue generation through a receipt CAS."""
    claim = _claim.get()
    if claim is None:
        yield None
        return
    repository, execution, owner_id = claim
    with repository.transaction() as db:
        _lock_claim(db, execution, owner_id)
        yield (execution.run_id, owner_id, execution.execution_count)


def recheck_worker_claim():
    """Fence live ownership again after a server-side lock wait, without holding HOST."""
    with worker_claim_guard():
        pass


def capture_worker_claim():
    """Pass only the server-held fence across spawn, never caller runtime fields."""
    claim = _claim.get()
    if claim is None:
        return None
    _, execution, owner_id = claim
    return (execution.run_id, owner_id, execution.execution_count)


def worker_claim_owns_run(run_id):
    """Accept a child only through the queued Codex parent's durable call binding."""
    claim = _claim.get()
    if claim is None:
        return False
    repository, execution, _ = claim
    if run_id == execution.run_id:
        return True
    from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run

    parent, child = repository.get(execution.run_id), repository.get(run_id)
    if parent is None or child is None:
        return False
    if (
        parent.intent != "codex.runtime"
        or parent.metadata.get("runtime_type") != "codex"
        or child.user_id != parent.user_id
        or tenant_id_of_run(child) != tenant_id_of_run(parent)
        or mod_id_of_run(child) != mod_id_of_run(parent)
        or (child.metadata.get("runtime_context") or {}).get("parent_run_id") != parent.run_id
    ):
        return False
    calls = (parent.metadata.get("codex_runtime") or {}).get("calls") or {}
    return any(
        isinstance(call, dict) and call.get("child_run_id") == child.run_id
        for call in calls.values()
    )


def capture_elt_worker_claim(step, context):
    """Capture the approved stored step from the host, never a client marker."""
    claim = _claim.get()
    if claim is None or (step.tool_id, step.action) != ("elt_import", "execute"):
        return None
    repository, execution, _ = claim
    run = repository.get(execution.run_id)
    from app.application.agent_orchestrator.elt_checkpoint_recovery import (
        ELT_CHECKPOINT_PROTOCOL,
        checkpoint_step,
    )
    from app.application.agent_orchestrator.task_background import task_execution_context

    dispatch = run.metadata.get("dispatch") if run else None
    if (
        not isinstance(dispatch, dict)
        or dispatch.get("elt_checkpoint_protocol") != ELT_CHECKPOINT_PROTOCOL
    ):
        return None
    approved = checkpoint_step(run)
    if (
        approved is None
        or (step.step_id, step.node_id, step.params)
        != (approved.step_id, approved.node_id, approved.params)
        or approved.step_id != context.get("step_id")
        or str(context.get("run_id") or "") != execution.run_id
        or str(context.get("tenant_id") or "") != str(execution.tenant_id or "")
        or context.get("idempotency_key")
        != task_execution_context(run, approved)["idempotency_key"]
    ):
        raise WorkerLeaseLost("ELT checkpoint scope does not match the current approved claim")
    recheck_worker_claim()
    return capture_worker_claim()


def owns_elt_step(context):
    claim = capture_worker_claim()
    return bool(
        _elt_step.get()
        and _elt_step.get() == context.get("step_id")
        and claim
        and claim[0] == context.get("run_id")
    )


@contextmanager
def restore_worker_claim(reference, *, elt_step_id=""):
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
    execution = AgentTaskExecution(run_id=run_id, task_id="", user_id="", execution_count=count)
    with worker_claim_scope(SQLAlchemyAgentRunRepository(), execution, owner_id):
        token = _elt_step.set(elt_step_id)
        try:
            if elt_step_id:
                recheck_worker_claim()
            yield
        finally:
            _elt_step.reset(token)


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
