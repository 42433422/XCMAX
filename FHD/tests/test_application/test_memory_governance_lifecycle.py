"""Memory governance must survive every recall path and legal scope changes."""

from unittest.mock import MagicMock

import pytest

from app.application.ai_chat.chat_evidence import prepare_chat_evidence
from app.application.dataset_rag_app_service import DatasetAccessContext
from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def access(tenant="2", **extra):
    return DatasetAccessContext(
        actor_id="7",
        tenant_id=tenant,
        permissions=frozenset({"dataset.read", "dataset.write"}),
        **extra,
    )


@pytest.fixture
def memory(monkeypatch, tmp_path):
    from app.application.user_memory_vector_app_service import (
        UserMemoryRagApplicationService,
        UserMemoryVectorIngestApplicationService,
    )
    from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore

    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_BACKEND", "legacy")
    UserMemoryStore._instance = None
    UserMemoryService._instance = None
    service = UserMemoryService(storage_type="memory")
    monkeypatch.setattr(
        "app.domain.shared_services.user_memory_service.get_user_memory_service", lambda: service
    )
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "governed.sqlite"))
    ingest = UserMemoryVectorIngestApplicationService(vector_store=store)
    rag = UserMemoryRagApplicationService(vector_store=store)
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: ingest,
    )
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_rag_app_service",
        lambda: rag,
    )
    monkeypatch.setattr("app.application.get_user_memory_rag_app_service", lambda: rag)
    return PersyMemoryApplicationService(service)


def namespace(principal=None):
    from app.application.persy_memory_utils import _memory_owner_id

    return _memory_owner_id(principal or access())


def capture(memory, principal=None, scope="user"):
    return memory.capture_conversation_turn(
        access_context=principal or access(),
        user_message="客户北辰科技的负责人是李明",
        session_id="first-session",
        scope=scope,
    )["candidates"][0]


def test_pending_is_visible_for_review_but_never_recallable(memory):
    capture(memory)
    assert memory.list_memories(access_context=access())["memories"][0]["status"] == "pending"
    assert memory.query(access_context=access(), query="北辰科技负责人")["memories"] == []


def test_legal_same_actor_tenant_change_cannot_read_old_business_facts(memory):
    row = capture(memory)
    memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    assert memory.query(access_context=access(), query="北辰科技")["memories"]
    assert memory.list_memories(access_context=access("3"))["memories"] == []
    assert memory.query(access_context=access("3"), query="北辰科技")["memories"] == []


@pytest.mark.parametrize("state", ["pending", "active_ineligible", "blocked"])
@pytest.mark.parametrize("question", ["记得北辰科技负责人吗", "查询北辰科技负责人？"])
def test_actual_chat_evidence_rechecks_governance(memory, monkeypatch, state, question):
    row = capture(memory)
    row.update(
        status="active" if state != "pending" else "pending",
        eligible_for_planner=state != "active_ineligible",
        source_policy="blocked" if state == "blocked" else "observed",
    )
    fake_persy = MagicMock()
    fake_persy.query.return_value = {"success": True, "memories": [row]}
    monkeypatch.setattr(
        "app.application.persy_memory_app_service.get_persy_memory_app_service", lambda: fake_persy
    )
    monkeypatch.setattr(
        "app.fastapi_routes.dataset_access.dataset_access_context_from_request", lambda _: access()
    )
    dataset = MagicMock()
    dataset.status.return_value = {"success": True, "datasets": {}}
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: dataset
    )
    result = prepare_chat_evidence(object(), {"local_user_id": 7, "tenant_id": "2"}, question)
    assert "李明" not in str(result.get("chat_memory_evidence") or "")
    assert "李明" not in str(result.get("chat_knowledge_evidence") or "")


@pytest.mark.parametrize("scope", ["user", "tenant"])
def test_same_actor_in_another_mod_cannot_list_or_mutate(memory, scope):
    first = access(mod_id="crm")
    other = access(mod_id="finance")
    row = capture(memory, first, scope)
    memory.mutate(access_context=first, memory_id=row["memory_id"], action="confirm")
    assert memory.query(access_context=first, query="北辰科技")["memories"]
    assert memory.list_memories(access_context=other)["memories"] == []
    assert not memory.mutate(access_context=other, memory_id=row["memory_id"], action="delete")[
        "success"
    ]


def test_legacy_bare_actor_is_not_implicitly_global(memory):
    service = memory.memory_service
    row = service.propose_memory_candidate("7", "entity", "customer", "前企业客户秘密")["candidate"]
    service.confirm_memory_candidate("7", row["memory_id"])
    assert memory.list_memories(access_context=access())["memories"] == []
    assert (
        service.list_memories("7")[0]["status"] == "active"
    )  # audit remains accessible to migration tooling


@pytest.mark.parametrize("extraction_backend", ["fallback", "mem0"])
def test_only_explicit_personal_global_preferences_cross_tenants(
    memory, monkeypatch, extraction_backend
):
    if extraction_backend == "mem0":
        backend = MagicMock()
        backend.enabled = False
        backend.extract_candidates.return_value = [
            {
                "memory_type": "preference",
                "key": "report",
                "confidence": 0.7,
                "value": {"subject": "user", "statement": "用户偏好简洁报告"},
            },
            {
                "memory_type": "preference",
                "key": "business",
                "confidence": 0.7,
                "value": {"subject": "北辰科技", "statement": "北辰科技偏好旧企业价格"},
            },
        ]
        monkeypatch.setattr(
            "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
        )
    result = memory.capture_conversation_turn(
        access_context=access(),
        user_message="我喜欢简洁报告；客户北辰科技的偏好是旧企业价格",
        scope="global_preference",
    )
    assert len(result["candidates"]) == 1
    row = result["candidates"][0]
    assert not memory.query(access_context=access("3"), query="报告")["memories"]
    memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    assert memory.query(access_context=access("3", mod_id="finance"), query="简洁报告")["memories"]
    denied = memory.mutate(
        access_context=access(),
        memory_id=row["memory_id"],
        action="correct",
        patch={"value": {"subject": "北辰科技", "statement": "北辰科技旧企业价格"}},
    )
    assert denied["error_code"] == "global_preference_only"


def test_correction_and_revocation_fence_failed_vector_projection(memory, monkeypatch):
    from app.application.user_memory.retrieve import filter_recalled_memories
    from app.application.user_memory_vector_app_service import get_user_memory_rag_app_service

    row = capture(memory)
    confirmed = memory.mutate(
        access_context=access(), memory_id=row["memory_id"], action="confirm"
    )["memory"]
    rag = get_user_memory_rag_app_service()
    hits = rag.query(namespace(), "北辰科技")["hits"]
    assert hits and "李明" in hits[0]["content"]
    assert hits[0]["metadata"]["source_revision"] == confirmed["revision"]

    def unavailable(**kwargs):
        raise OSError("projection storage unavailable")

    monkeypatch.setattr(rag._vector_store, "upsert_chunks", unavailable)
    corrected = memory.mutate(
        access_context=access(),
        memory_id=row["memory_id"],
        action="correct",
        patch={"value": {"statement": "北辰科技的负责人是王敏"}},
    )
    assert corrected["projection"]["user_vector"] == "retry_required"
    assert corrected["memory"]["revision"] > confirmed["revision"]
    assert filter_recalled_memories(namespace(), hits) == []
    current = rag.query(namespace(), "北辰科技")["hits"]
    assert current and "王敏" in current[0]["content"] and "李明" not in str(current)
    assert "李明" in str(corrected["memory"]["history"])

    monkeypatch.setattr(rag._vector_store, "delete_source", unavailable)
    deleted = memory.mutate(access_context=access(), memory_id=row["memory_id"], action="delete")
    assert deleted["projection"]["user_vector"] == "retry_required"
    assert rag.query(namespace(), "北辰科技")["hits"] == []
    assert "未召回" in rag.format_for_prompt(namespace(), "北辰科技", current)
    assert memory.list_memories(access_context=access(), status="deleted")["memories"][0]["history"]


def test_confirmed_memory_rebuilds_without_new_confirmation(memory):
    from app.application.user_memory.projections import rebuild_memory_projections
    from app.application.user_memory_vector_app_service import get_user_memory_rag_app_service

    row = capture(memory)
    memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    rag = get_user_memory_rag_app_service()
    assert rag._vector_store.delete_index(namespace())
    assert rebuild_memory_projections(namespace()) == {
        "total": 1,
        "current": 1,
        "retry_required": 0,
    }
    with rag._vector_store._get_conn() as connection:
        assert (
            connection.execute("SELECT count(*) FROM user_memory_vector_chunks").fetchone()[0] == 1
        )
    assert "李明" in rag.query(namespace(), "北辰科技")["hits"][0]["content"]


def test_model_empty_extraction_does_not_fall_back_and_questions_never_capture(memory, monkeypatch):
    backend = MagicMock()
    backend.extract_candidates.return_value = []
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )
    assert (
        memory.capture_conversation_turn(access_context=access(), user_message="我喜欢简洁报告")[
            "candidates"
        ]
        == []
    )
    backend.extract_candidates.return_value = None
    for message in (
        "客户北辰科技的负责人是李明吗？",
        "假如客户北辰科技的负责人是李明",
        "我喜欢的报告是什么？",
    ):
        assert (
            memory.capture_conversation_turn(access_context=access(), user_message=message)[
                "candidates"
            ]
            == []
        )


def test_trusted_http_and_agent_mod_scope_match(memory, trusted_actor):
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request
    from app.infrastructure.auth.agent_mod_scope import agent_dataset_access_context

    actor = trusted_actor(
        user_id=7, tenant_id=2, mod_id="crm", permissions=["dataset.read", "dataset.write"]
    )
    request_access = dataset_access_context_from_request(actor.request)
    agent_access = agent_dataset_access_context(actor.context)
    assert request_access.mod_id == agent_access.mod_id == "crm"
    assert namespace(request_access) == namespace(agent_access)


def test_confirmed_fact_crosses_sessions_but_correction_and_delete_reach_chat(
    memory, trusted_actor, monkeypatch
):
    actor = trusted_actor(user_id=7, tenant_id=2, permissions=["dataset.read", "dataset.write"])
    context = {**actor.context, "local_user_id": 7, "session_id": "later-session"}
    monkeypatch.setattr(
        "app.application.persy_memory_app_service.get_persy_memory_app_service", lambda: memory
    )
    dataset = MagicMock()
    dataset.status.return_value = {"success": True, "datasets": {}}
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: dataset
    )
    row = capture(memory)

    def evidence():
        prepared = prepare_chat_evidence(actor.request, context, "查询北辰科技负责人？")
        return str(prepared.get("chat_memory_evidence", "")) + str(
            prepared.get("chat_knowledge_evidence", "")
        )

    assert "李明" not in evidence()
    memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    assert "李明" in evidence()
    memory.mutate(
        access_context=access(),
        memory_id=row["memory_id"],
        action="correct",
        patch={"value": {"statement": "北辰科技的负责人是王敏"}},
    )
    current = evidence()
    assert "王敏" in current and "李明" not in current
    memory.mutate(access_context=access(), memory_id=row["memory_id"], action="delete")
    removed = evidence()
    assert "李明" not in removed and "王敏" not in removed


def test_revoked_projection_is_replayed_on_rebuild(memory, monkeypatch):
    from app.application.user_memory.projections import rebuild_memory_projections
    from app.application.user_memory_vector_app_service import get_user_memory_rag_app_service

    row = capture(memory)
    memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    store = get_user_memory_rag_app_service()._vector_store
    delete = store.delete_source
    monkeypatch.setattr(store, "delete_source", lambda **_: -1)
    result = memory.mutate(access_context=access(), memory_id=row["memory_id"], action="delete")
    assert result["projection"]["user_vector"] == "retry_required"
    with store._get_conn() as connection:
        assert (
            connection.execute("SELECT count(*) FROM user_memory_vector_chunks").fetchone()[0] == 1
        )
    monkeypatch.setattr(store, "delete_source", delete)
    assert rebuild_memory_projections(namespace())["retry_required"] == 0
    with store._get_conn() as connection:
        assert (
            connection.execute("SELECT count(*) FROM user_memory_vector_chunks").fetchone()[0] == 0
        )


@pytest.mark.parametrize("changed", ["tenant", "mod"])
def test_legitimate_scope_rebinding_does_not_reuse_old_private_facts(
    memory, trusted_actor, changed
):
    from app.db.models.user import User
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    original = trusted_actor(
        user_id=7, tenant_id=2, mod_id="crm", permissions=["dataset.read", "dataset.write"]
    )
    principal = dataset_access_context_from_request(original.request)
    row = capture(memory, principal)
    memory.mutate(access_context=principal, memory_id=row["memory_id"], action="confirm")
    if changed == "tenant":
        with original.factory.begin() as db:
            db.get(User, 7).tenant_id = 3
    current = trusted_actor(
        user_id=7,
        tenant_id=3 if changed == "tenant" else 2,
        mod_id="finance" if changed == "mod" else "crm",
    )
    assert validate_actor_context(current.context) is None
    current_access = dataset_access_context_from_request(current.request)
    assert namespace(current_access) != namespace(principal)
    assert memory.query(access_context=current_access, query="北辰科技")["memories"] == []
    assert not memory.mutate(
        access_context=current_access, memory_id=row["memory_id"], action="delete"
    )["success"]


def test_vector_only_failure_invalidates_shared_replay_and_recovers(memory, monkeypatch):
    from app.application.user_memory_vector_app_service import get_user_memory_rag_app_service

    row = capture(memory)
    store = get_user_memory_rag_app_service()._vector_store
    backend = MagicMock()
    backend.enabled = True
    backend.upsert_governed.return_value = True
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )
    upsert = store.upsert_chunks
    monkeypatch.setattr(store, "upsert_chunks", lambda **_: 0)
    result = memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    assert result["projection"] == {"user_vector": "retry_required", "mem0": "current"}
    backend.invalidate_projection.assert_called_once_with(namespace())
    monkeypatch.setattr(store, "upsert_chunks", upsert)
    rebuilt = memory.memory_service.rebuild_memory_projections(namespace())
    assert rebuilt == {"total": 1, "current": 1, "retry_required": 0}
    with store._get_conn() as connection:
        assert (
            connection.execute("SELECT count(*) FROM user_memory_vector_chunks").fetchone()[0] == 1
        )


def test_vector_projection_does_not_replace_new_revision_with_late_old_write(memory):
    from app.application.user_memory_vector_app_service import (
        get_user_memory_vector_ingest_app_service,
    )

    ingest = get_user_memory_vector_ingest_app_service()
    assert ingest.upsert_governed(
        user_id=namespace(),
        source_memory_id="test-source",
        revision=3,
        text="new revision",
        metadata={},
    )
    assert not ingest.upsert_governed(
        user_id=namespace(),
        source_memory_id="test-source",
        revision=2,
        text="stale revision",
        metadata={},
    )
    with ingest._vector_store._get_conn() as connection:
        assert connection.execute("SELECT content FROM user_memory_vector_chunks").fetchmany(2) == [
            ("new revision",)
        ]


def test_private_capture_does_not_need_dataset_write_but_cannot_write_tenant(
    memory, trusted_actor, monkeypatch
):
    from app.application.agent_task_context import scoped_conversation_user_id
    from app.application.ai_chat.conversation_history import persist_recallable_chat_turn

    actor = trusted_actor(user_id=7, tenant_id=2, permissions=["memory_v2.read", "memory_v2.write"])
    context = {
        **actor.context,
        "local_user_id": 7,
        "session_id": "personal-only",
        "_dataset_access_context_trusted": True,
        "_dataset_access_context": {"permissions": []},
    }
    monkeypatch.setattr(
        "app.application.persy_memory_app_service.get_persy_memory_app_service", lambda: memory
    )
    kwargs = {
        "user_id": scoped_conversation_user_id("7", context),
        "message": "我喜欢简洁报告",
        "source": "chat",
        "response_data": {"success": True, "response": "收到", "action": "answer"},
    }
    persist_recallable_chat_turn(context={**context, "persy_memory_scope": "tenant"}, **kwargs)
    assert memory.memory_service.list_memories(namespace()) == []
    persist_recallable_chat_turn(context=context, **kwargs)
    rows = memory.memory_service.list_memories(namespace())
    assert len(rows) == 1 and rows[0]["status"] == "pending"
