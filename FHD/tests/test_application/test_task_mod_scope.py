import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_mod_scope import (
    capture_task_mod_scope,
    task_mod_execution_scope,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.customer_app_service import CustomerApplicationService
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.user import Session, User
from app.infrastructure.auth.agent_principal import AgentPrincipal, bind_agent_runtime_context
from app.infrastructure.tenant_scope import tenant_scope
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    engines = {
        key: create_engine(f"sqlite:///{tmp_path / (key + '.sqlite')}")
        for key in ("host", "mod-a", "mod-b")
    }
    factories = {key: sessionmaker(bind=engine) for key, engine in engines.items()}
    User.__table__.create(engines["host"])
    Session.__table__.create(engines["host"])
    with factories["host"].begin() as db:
        db.add(
            User(
                id=17,
                username="owner",
                password="test-hash",
                tenant_id=7,
                is_active=True,
                tier="enterprise",
            )
        )
        db.add(
            Session(
                id=71,
                session_id="local-session-secret",
                user_id=17,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                entitled_mod_ids_json='["mod-a"]',
            )
        )
    for key in engines:
        PurchaseUnit.__table__.create(engines[key])
        with tenant_scope(7), factories[key].begin() as db:
            db.add(PurchaseUnit(unit_name=f"{key}客户", is_active=True))
    monkeypatch.setattr("app.db.HostSessionLocal", factories["host"])
    monkeypatch.setattr("app.db.get_host_engine", lambda: engines["host"])
    monkeypatch.setattr(
        "app.db.get_runtime_engine", lambda: engines[get_request_active_mod_id() or "host"]
    )
    # Exercise actual business repositories with the same selection boundary as
    # SessionLocal; task/auth ledgers must never use this factory.
    business_factory = lambda: factories[get_request_active_mod_id() or "host"]()
    monkeypatch.setattr("app.db.SessionLocal", business_factory)
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", business_factory)
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: service)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/agent/tasks",
            "headers": [(b"x-session-id", b"local-session-secret")],
            "query_string": b"",
        }
    )
    monkeypatch.setattr("app.infrastructure.request_context.get_current_request", lambda: request)
    yield factories
    for engine in engines.values():
        engine.dispose()


def _scope():
    return capture_task_mod_scope("17", "7", mod_id="mod-a")


def test_mod_receipt_restores_business_store_and_preserves_other_mod(stores):
    scope = _scope()
    assert "local-session-secret" not in json.dumps(scope)
    token = set_request_active_mod_id("mod-b")
    try:
        result = AgentToolExecutor().execute(
            AgentStep(node_id="query", tool_id="customers", action="query", params={}),
            runtime_context={"user_id": "17", "tenant_id": "7", "mod_scope": scope},
        )
        assert result["success"]
        assert [row["customer_name"] for row in result["data"]] == ["mod-a客户"]
        updated = AgentToolExecutor().execute(
            AgentStep(
                node_id="update",
                tool_id="customers",
                action="update",
                params={"id": 1, "contact_person": "模块任务更新"},
            ),
            runtime_context={"user_id": "17", "tenant_id": "7", "mod_scope": scope},
        )
        assert updated["success"]
        with tenant_scope(7), stores["mod-a"]() as db:
            assert db.query(PurchaseUnit).one().contact_person == "模块任务更新"
        with tenant_scope(7), stores["mod-b"]() as db:
            assert db.query(PurchaseUnit).one().contact_person is None
        assert get_request_active_mod_id() == "mod-b"
        with task_mod_execution_scope({"user_id": "17", "tenant_id": "7", "mod_scope": None}):
            assert get_request_active_mod_id() == ""
        assert get_request_active_mod_id() == "mod-b"
    finally:
        reset_request_active_mod_id(token)


@pytest.mark.parametrize("change", ["revoked", "expired", "disabled", "tenant", "forged"])
def test_mod_task_denied_after_scope_change_without_writing_business_data(stores, change):
    scope = _scope()
    with stores["host"].begin() as db:
        if change == "revoked":
            db.get(Session, 71).entitled_mod_ids_json = "[]"
        if change == "expired":
            db.get(Session, 71).expires_at = datetime.now(UTC) - timedelta(days=1)
        if change == "disabled":
            db.get(User, 17).is_active = False
        if change == "tenant":
            db.get(User, 17).tenant_id = 8
    if change == "forged":
        scope["owner_id"] = "18"
    result = AgentToolExecutor().execute(
        AgentStep(
            node_id="update",
            tool_id="customers",
            action="update",
            params={"id": 1, "contact_person": "wrong"},
        ),
        runtime_context={"user_id": "17", "tenant_id": "7", "mod_scope": scope},
    )
    assert result["error_code"] == "task_mod_scope_denied"
    with tenant_scope(7), stores["mod-a"]() as db:
        assert db.query(PurchaseUnit).one().contact_person is None


def test_public_context_cannot_replace_mod_scope_and_task_ledger_is_host_owned(stores):
    token = set_request_active_mod_id("mod-a")
    try:
        context = bind_agent_runtime_context(
            {"mod_scope": {"mod_id": "mod-b"}, "active_mod_id": "mod-b"},
            AgentPrincipal(user_id="17", tenant_id="7"),
        )
        assert context["mod_scope"]["mod_id"] == "mod-a"
        assert "active_mod_id" not in context
        run = AgentRun(user_id="17", message="mod task", status="queued")
        run.metadata["runtime_context"] = context
        run.metadata["task_context"] = {"task_id": "mod-task"}
        SQLAlchemyAgentRunRepository().save(run)
        SQLAlchemyTaskExecutionRepository().enqueue(run)
    finally:
        reset_request_active_mod_id(token)
    assert (
        SQLAlchemyAgentRunRepository().get(run.run_id).metadata["runtime_context"]["mod_scope"]
        == context["mod_scope"]
    )
    assert (
        SQLAlchemyTaskExecutionRepository().claim("host-worker", lease_seconds=30).run_id
        == run.run_id
    )


@pytest.mark.parametrize("claimed", [False, True])
def test_legacy_mod_history_is_copied_without_replaying_or_deleting_it(stores, claimed):
    from app.application.agent_orchestrator.mod_journal_migration import copy_legacy_journal

    legacy = SQLAlchemyAgentRunRepository(session_factory=stores["mod-a"])
    queue = SQLAlchemyTaskExecutionRepository(session_factory=stores["mod-a"])
    run = AgentRun(user_id="17", message="旧模块任务", status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "7"}
    run.metadata["task_context"] = {"task_id": "legacy-task"}
    run.steps = [
        AgentStep(node_id="query", tool_id="customers", action="query", params={}, status="pending")
    ]
    legacy.save(run)
    queue.enqueue(run)
    if claimed:
        queue.claim("old-worker", lease_seconds=30)
    token = set_request_active_mod_id("mod-a")
    try:
        copied = SQLAlchemyAgentRunRepository().get(run.run_id)
    finally:
        reset_request_active_mod_id(token)
    assert copied.status == ("blocked" if claimed else "paused")
    assert copied.metadata["legacy_mod_scope_required"] == "mod-a"
    assert legacy.get(run.run_id).status == "queued"
    assert SQLAlchemyTaskExecutionRepository().claim("new-worker", lease_seconds=30) is None
    with stores["mod-a"]() as source, stores["host"]() as target:
        assert copy_legacy_journal(source.get_bind(), target.get_bind(), "mod-a")["runs"] == 0
    if claimed:
        assert copied.metadata["non_retryable"]
        assert all(step.status != "waiting_user" for step in copied.steps)
    else:
        refreshed = bind_agent_runtime_context(
            {}, AgentPrincipal(user_id="17", tenant_id="7"), run=copied
        )
        assert refreshed["mod_scope"]["mod_id"] == "mod-a"


def test_migration_conflict_does_not_fall_back_to_empty_memory_store(monkeypatch):
    from app.application.agent_orchestrator import run_repository, task_execution_repository
    from app.application.agent_orchestrator.mod_journal_migration import LegacyJournalMigrationError

    def fail(*args, **kwargs):
        raise LegacyJournalMigrationError("legacy identity collision")

    monkeypatch.setattr(run_repository, "_agent_run_repository", None)
    monkeypatch.setattr(task_execution_repository, "_task_execution_repository", None)
    monkeypatch.setattr(SQLAlchemyAgentRunRepository, "list_recent", fail)
    monkeypatch.setattr(SQLAlchemyTaskExecutionRepository, "get", fail)
    with pytest.raises(LegacyJournalMigrationError):
        run_repository.get_agent_run_repository()
    with pytest.raises(LegacyJournalMigrationError):
        task_execution_repository.get_task_execution_repository()
    assert run_repository._agent_run_repository is None
    assert task_execution_repository._task_execution_repository is None
