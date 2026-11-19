"""Employee memories use explicit provenance and real, tenant-scoped storage."""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.employee_runtime.memory import EmployeeMemoryManager
from app.domain.employee.memory_scope import MemoryScope


def _manager(tenant=1, *, shared=False, employee="same-worker", **kwargs):
    scope = MemoryScope.from_config(
        employee,
        {"memory": {"scope": "tenant" if shared else "user"}},
        tenant_id=tenant,
    )
    kwargs.setdefault("provenance", {"run_id": "fixture-execution"})
    return EmployeeMemoryManager(scope, **kwargs)


@pytest.fixture
def vectors(tmp_path, monkeypatch):
    from app.application import user_memory_vector_app_service as service
    from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore

    store = SQLiteUserMemoryVectorStore(str(tmp_path / "memory.sqlite"))
    ingest = service.UserMemoryVectorIngestApplicationService(vector_store=store)
    monkeypatch.setattr(service, "get_user_memory_vector_store", lambda: store)
    monkeypatch.setattr(service, "get_user_memory_vector_ingest_app_service", lambda: ingest)
    monkeypatch.setenv("XCAGI_MEMORY_RAG_MIN_SCORE", "0")
    return ingest


def test_default_employee_memory_is_private_across_users_tenants_and_employees(vectors):
    manager = _manager(provenance={"run_id": "run-real-source", "pack_id": "same-worker"})
    manager.remember("invoice private account", "tenant-one owner-41 detail", user_id=41)

    own = manager.recall("invoice private account", user_id=41)
    assert len(own.hits) == 1
    assert own.hits[0]["metadata"]["run_id"] == "run-real-source"
    assert own.hits[0]["metadata"]["provenance_status"] == "linked_run"
    assert own.hits[0]["metadata"]["verified_business_result"] is False
    assert manager.recall("invoice private account", user_id=42).hits == []
    assert _manager(2).recall("invoice private account", user_id=41).hits == []
    assert (
        _manager(employee="different-worker").recall("invoice private account", user_id=41).hits
        == []
    )


def test_explicit_enterprise_sharing_is_confined_to_one_tenant(vectors):
    manager = _manager(shared=True)
    manager.remember("invoice shared workflow", "tenant-one-only", user_id=41)
    assert len(manager.recall("invoice shared workflow", user_id=42).hits) == 1
    assert _manager(2, shared=True).recall("invoice shared workflow", user_id=42).hits == []
    assert _manager().recall("invoice shared workflow", user_id=42).hits == []


def test_legacy_employee_index_is_not_adopted_by_any_user_or_tenant(vectors):
    from app.application.user_memory_vector_app_service import UserMemoryVectorChunk

    vectors.ingest_chunks(
        "emp:same-worker",
        [UserMemoryVectorChunk("legacy", "invoice legacy secret", {"employee_id": "same-worker"})],
    )
    for tenant in (1, 2):
        for shared in (False, True):
            assert (
                _manager(tenant, shared=shared).recall("invoice legacy secret", user_id=41).hits
                == []
            )


def test_scope_and_provenance_are_rechecked_for_each_vector_hit(vectors):
    from app.application.user_memory_vector_app_service import UserMemoryVectorChunk

    manager = _manager()
    metadata = {
        **manager._metadata(41),
        "execution_status": "completed",
    }
    contaminated = [
        {**metadata, "tenant_id": "2"},
        {**metadata, "user_id": "42"},
        {**metadata, "employee_id": "another"},
        {**metadata, "scope_version": 1},
        {**metadata, "source_component": "untrusted"},
        {**metadata, "execution_status": "processing"},
        {**metadata, "memory_scope": "tenant"},
        {},
    ]
    vectors.ingest_chunks(
        manager.scope.long_term_index(41),
        [
            UserMemoryVectorChunk(str(i), "invoice contaminated", meta)
            for i, meta in enumerate(contaminated)
        ],
    )
    assert manager.recall("invoice contaminated", user_id=41, top_k=20).hits == []


def test_failed_experience_retains_its_run_source_and_failure_label(vectors):
    manager = _manager()
    manager.remember("invoice export failed", "missing required field", user_id=41, success=False)
    recalled = manager.recall("invoice export failed", user_id=41)
    assert len(recalled.hits) == 1
    meta = recalled.hits[0]["metadata"]
    assert meta["execution_status"] == "failed"
    assert meta["evidence_kind"] == "execution_summary"
    assert meta["provenance_status"] == "linked_run"
    assert meta["run_id"] == "fixture-execution"
    assert "success=False" in recalled.long_term_prompt


@pytest.mark.parametrize(
    "provenance", [None, {}, {"run_id": ""}, {"run_id": " "}, {"run_id": 0}, {"run_id": True}]
)
def test_unlinked_execution_cannot_write_or_recall_long_term_experience(vectors, provenance):
    from app.application.user_memory_vector_app_service import UserMemoryVectorChunk

    manager = _manager(provenance=provenance)
    manager.remember("invoice unlinked", "do not promote", user_id=41)
    assert _manager().recall("invoice unlinked", user_id=41).hits == []
    # Old v2 rows and a forged linked_run flag both fail without a run source.
    metadata = {**manager._metadata(41), "execution_status": "completed"}
    vectors.ingest_chunks(
        manager.scope.long_term_index(41),
        [
            UserMemoryVectorChunk("unlinked", "invoice old unlinked", metadata),
            UserMemoryVectorChunk(
                "flag-only", "invoice forged flag", {**metadata, "provenance_status": "linked_run"}
            ),
        ],
    )
    assert _manager().recall("invoice", user_id=41).hits == []


@pytest.mark.parametrize("tenant, user", [(None, 41), (1, 0), (1, None), (1, True), (False, 41)])
def test_missing_identity_never_accesses_backends(monkeypatch, tenant, user):
    from app.application import user_memory_vector_app_service as service
    from app.domain.shared_services import conversation_service

    def forbidden(*args, **kwargs):
        raise AssertionError("unscoped memory backend access")

    monkeypatch.setattr(service, "get_user_memory_vector_ingest_app_service", forbidden)
    monkeypatch.setattr(service, "UserMemoryRagApplicationService", forbidden)
    monkeypatch.setattr(conversation_service, "ConversationService", forbidden)
    manager = _manager(tenant)
    manager.remember("task", "outcome", user_id=user, session_id="session")
    assert not manager.recall("task", user_id=user, session_id="session").has_content


def test_recent_sql_window_uses_latest_messages_and_enforces_owner_and_provenance(
    tmp_path, monkeypatch
):
    from app.db.models import AIConversation, AIConversationSession, User
    from app.domain.shared_services import conversation_service

    engine = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}")
    for model in (User, AIConversationSession, AIConversation):
        model.__table__.create(engine)

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(conversation_service, "get_db", database)
    manager = EmployeeMemoryManager(
        MemoryScope("same-worker", tenant_id=1, long_term_enabled=False)
    )
    meta = {**manager._metadata(41), "execution_status": "completed"}
    with Session(engine) as db:
        db.add(User(id=41, username="owner", password="unused", tenant_id=1))
        db.add(User(id=42, username="other", password="unused", tenant_id=2))
        db.add(AIConversationSession(session_id="private", user_id=41))
        db.flush()
        for i in range(1, 61):
            db.add(
                AIConversation(
                    session_id="private",
                    user_id="41",
                    role="user" if i % 2 else "assistant",
                    content=f"message-{i}",
                    conversation_metadata=json.dumps(meta),
                    # The latest pair deliberately ties; id is the stable tiebreaker.
                    created_at=datetime(2026, 1, 1) + timedelta(seconds=min(i, 59)),
                )
            )
        db.commit()
    try:
        assert [
            row["content"]
            for row in manager.recall("task", user_id=41, session_id="private").short_term_messages
        ] == [f"message-{i}" for i in range(53, 61)]
        assert manager.recall("task", user_id=42, session_id="private").short_term_messages == []
        other_tenant = EmployeeMemoryManager(
            MemoryScope("same-worker", tenant_id=2, long_term_enabled=False)
        )
        assert (
            other_tenant.recall("task", user_id=41, session_id="private").short_term_messages == []
        )
        assert (
            conversation_service.ConversationService().get_session_messages("private", limit=0)
            == []
        )
        assert (
            conversation_service.ConversationService().get_session_messages(
                "private", user_id="bad"
            )
            == []
        )
    finally:
        engine.dispose()
