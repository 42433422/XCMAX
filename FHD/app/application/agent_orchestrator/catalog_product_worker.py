"""Spawn handoff of expected identities, never authority from a caller's payload."""

from contextlib import contextmanager

TOOL = "catalog_products_v1"


def capture_catalog_worker_profile(step):
    if step.tool_id != TOOL:
        return None
    from app.desktop_runtime import database_generation_registry as registry

    registry.require_owned_source_profile()
    root, identity = registry._owned_profile
    return str(root), tuple(identity)


def restore_catalog_worker_profile(expected):
    if expected is None:
        return
    from app.config import Config
    from app.desktop_runtime import database_generation_registry as registry

    # Re-run the real factory checks against this child's server configuration,
    # migrated host schema, physical identity, WAL mode and authority anchor.
    # The expectation is a separate parent-only spawn argument, not runtime_context.
    registry.configure_owned_source_profile(Config)
    registry.require_owned_source_profile()
    root, identity = registry._owned_profile
    if (str(root), tuple(identity)) != expected:
        registry._owned_profile = None
        raise registry.GenerationObservationError("spawned catalog host identity changed")


@contextmanager
def restore_catalog_claim(reference):
    if reference is None:
        yield
        return
    from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution

    run_id, owner_id, count = reference
    execution = AgentTaskExecution(run_id=run_id, task_id="", user_id="", execution_count=count)
    with worker_claim_scope(SQLAlchemyAgentRunRepository(auto_create=False), execution, owner_id):
        yield
