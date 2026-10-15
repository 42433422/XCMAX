"""Durable scheduling must survive leaving the request's Mod context."""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import inspect

import app.db as db_mod
from app.application.agent_orchestrator.approval_grant import _consumption_repository
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.models.agent_approval import AgentApprovalConsumption
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


def test_mod_request_task_is_claimable_by_fresh_host_worker(tmp_path, monkeypatch):
    host_url = f"sqlite:///{tmp_path / 'host.db'}"
    mod_url = f"sqlite:///{tmp_path / 'mod.db'}"
    monkeypatch.setenv("DATABASE_URL", host_url)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_MOD_DATABASE_URL_REVIEW_MOD", mod_url)
    monkeypatch.setattr(db_mod, "_get_test_db_manager", lambda: None)
    monkeypatch.setattr("app.http.request_context.get_current_http_request", lambda: None)
    AgentApprovalConsumption.__table__.create(db_mod.get_host_engine())
    run = AgentRun(user_id="owner", message="durable Mod task", status="queued")
    token = set_request_active_mod_id("review-mod")
    try:
        # Prove business sessions really select another database in this context.
        with db_mod.SessionLocal() as business_db:
            assert str(business_db.get_bind().url) == mod_url
        SQLAlchemyAgentRunRepository().save(run)
        SQLAlchemyTaskExecutionRepository().enqueue(run)
        assert _consumption_repository().consume(
            jti="one-approval", run_id=run.run_id, step_id="step"
        )
    finally:
        reset_request_active_mod_id(token)

    def claim_from_new_thread():
        assert get_request_active_mod_id() == ""
        queue = SQLAlchemyTaskExecutionRepository()
        claimed = queue.claim("fresh-worker", lease_seconds=60)
        assert claimed is not None
        persisted = SQLAlchemyAgentRunRepository().get(claimed.run_id)
        assert persisted is not None
        return claimed.run_id, persisted.message

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(claim_from_new_thread).result(timeout=20) == (
            run.run_id,
            run.message,
        )
    # Leaving the Mod must not turn a consumed approval into a fresh permission.
    assert not _consumption_repository().consume(
        jti="one-approval", run_id=run.run_id, step_id="step"
    )
    assert "agent_runs" in inspect(db_mod.get_host_engine()).get_table_names()
    assert "agent_runs" not in inspect(db_mod._get_engine_for_url(mod_url)).get_table_names()
    assert (
        "agent_approval_consumptions"
        not in inspect(db_mod._get_engine_for_url(mod_url)).get_table_names()
    )
    assert (
        "agent_task_executions"
        not in inspect(db_mod._get_engine_for_url(mod_url)).get_table_names()
    )
