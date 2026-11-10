"""Real session provenance and SQLite persistence boundaries for chat memory."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from app.application.agent_task_context import (
    scoped_conversation_user_id,
    scoped_personal_memory_id,
)
from app.application.ai_chat.conversation_history import (
    authorized_memory_context,
    persist_recallable_chat_turn,
)
from app.application.user_memory_vector_app_service import (
    UserMemoryRagApplicationService,
    UserMemoryVectorIngestApplicationService,
)
from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def memory(tmp_path, monkeypatch, trusted_actor):
    actor = trusted_actor(user_id=7, tenant_id=2, permissions=["dataset.read", "dataset.write"])
    ctx = {**actor.context, "session_id": "memory-session", "local_user_id": 7}
    namespace = scoped_conversation_user_id("7", ctx)
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "memory.sqlite"))
    ingest = UserMemoryVectorIngestApplicationService(vector_store=store)
    rag = UserMemoryRagApplicationService(vector_store=store)
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: ingest,
    )
    monkeypatch.setattr("app.application.get_user_memory_rag_app_service", lambda: rag)
    return actor, ctx, namespace, store, rag


def capture(namespace, ctx):
    reply = {"success": True, "response": "A synthetic answer", "action": "answer"}
    before = deepcopy(reply)
    persist_recallable_chat_turn(
        user_id=namespace,
        message="A synthetic question",
        source="chat",
        context=ctx,
        response_data=reply,
    )
    assert reply == before


def count(store):
    with store._get_conn() as conn:
        return conn.execute("SELECT count(*) FROM user_memory_vector_chunks").fetchone()[0]


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "alias-only",
        "conflicting",
        "forged",
        "wrong-namespace",
        "read-only-claim",
        "changed-tenant",
        "mod-mismatch",
        "cross-conversation",
    ],
)
def test_rejects_unauthorized_real_sqlite_write(memory, bad, monkeypatch):
    _, ctx, namespace, store, _ = memory
    ctx = deepcopy(ctx)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    if bad == "missing":
        ctx = {}
    elif bad == "alias-only":
        ctx.pop("_actor_authorization")
    elif bad == "conflicting":
        ctx["local_user_id"] = 8
    elif bad == "forged":
        ctx["_actor_authorization"]["proof"] = "forged"
    elif bad == "wrong-namespace":
        namespace = "7"
    elif bad == "changed-tenant":
        ctx["tenant_id"] = "999"
    elif bad == "mod-mismatch":
        ctx["mod_id"] = "other-mod"
    elif bad == "cross-conversation":
        ctx["session_id"] = "other-session"
    else:
        ctx = {
            "_dataset_access_context_trusted": True,
            "_dataset_access_context": {
                "actor_id": "local-desktop",
                "tenant_id": "default",
                "permissions": ["dataset.read"],
            },
        }
    assert authorized_memory_context(namespace, ctx) is None
    capture(namespace, ctx)
    assert count(store) == 0


def test_authenticated_existing_namespace_persists_and_recalls(memory):
    _, ctx, namespace, store, rag = memory
    memory_namespace = scoped_personal_memory_id(ctx)
    assert authorized_memory_context(namespace, ctx) == (memory_namespace, None)
    capture(namespace, ctx)
    assert count(store) == 1
    assert rag.query(memory_namespace, "synthetic question")["hits"]
    with store._get_conn() as conn:
        assert conn.execute(
            "SELECT index_id,user_id FROM user_memory_vector_indexes"
        ).fetchall() == [(memory_namespace, memory_namespace)]


def test_authenticated_memory_is_available_in_a_new_session(memory):
    _, ctx, namespace, _store, rag = memory
    capture(namespace, ctx)
    next_session = {**ctx, "session_id": "next-session", "conversation_id": "next-session"}
    next_namespace = scoped_conversation_user_id("7", next_session)
    memory_namespace = scoped_personal_memory_id(next_session)
    assert next_namespace != namespace
    assert authorized_memory_context(next_namespace, next_session) == (memory_namespace, None)
    assert rag.query(memory_namespace, "synthetic question")["hits"]


def test_live_session_revocation_blocks_memory(memory):
    actor, ctx, namespace, store, _ = memory
    from app.db.models.user import Session

    with actor.factory.begin() as db:
        db.delete(db.get(Session, actor.session_row_id))
    capture(namespace, ctx)
    assert count(store) == 0


@pytest.mark.parametrize("authenticated", [False, True])
def test_planner_cannot_recall_existing_namespace_anonymously(memory, monkeypatch, authenticated):
    _, ctx, namespace, _, rag = memory
    memory_namespace = scoped_personal_memory_id(ctx)
    capture(namespace, ctx)
    from app.application.workflow.planner import LLMWorkflowPlanner

    calls = []
    original = rag.query

    def query(**kwargs):
        result = original(**kwargs)
        calls.append((kwargs, result))
        return result

    monkeypatch.setattr(rag, "query", query)
    v2 = MagicMock()
    v2.format_memory_v2_for_prompt.return_value = "无已确认记忆"
    monkeypatch.setattr(
        "app.domain.shared_services.user_memory_service.get_user_memory_service", lambda: v2
    )

    class AfterMemory(Exception):
        pass

    def stop(*args, **kwargs):
        raise AfterMemory

    planner = LLMWorkflowPlanner(ai_service=MagicMock())
    monkeypatch.setattr(planner, "_plan_with_llm", stop)
    with pytest.raises(AfterMemory):
        planner.plan(
            namespace, "hello synthetic question", {}, context=ctx if authenticated else {}
        )
    assert len(calls) == int(authenticated) * 2
    assert v2.format_memory_v2_for_prompt.call_count == int(authenticated)
    if authenticated:
        assert calls[0][0]["user_id"] == memory_namespace
        assert calls[1][0]["user_id"] == namespace
        assert calls[0][1]["hits"]
        assert v2.format_memory_v2_for_prompt.call_args.kwargs["user_id"] == "7"


def test_dataset_permissions_rederived_not_body_claims(memory, monkeypatch):
    actor, ctx, namespace, store, _ = memory
    from app.db.models.permission import Permission, Role

    with actor.factory.begin() as db:
        role = db.query(Role).filter_by(name="user").one()
        role.permissions = [db.query(Permission).filter_by(code="dataset.read").one()]
    ctx.update(
        _dataset_access_context_trusted=True,
        _dataset_access_context={
            "actor_id": "7",
            "tenant_id": "2",
            "permissions": ["dataset.write"],
            "is_admin": True,
        },
    )
    capture(namespace, ctx)
    assert count(store) == 0


def test_authenticated_dataset_writer_keeps_namespace_and_derived_access(memory, monkeypatch):
    _, ctx, namespace, store, _ = memory
    ctx.update(
        _dataset_access_context_trusted=True,
        _dataset_access_context={"actor_id": "999", "tenant_id": "999", "permissions": []},
    )
    persy = MagicMock()
    monkeypatch.setattr(
        "app.application.persy_memory_app_service.get_persy_memory_app_service", lambda: persy
    )
    capture(namespace, ctx)
    assert count(store) == 1
    kwargs = persy.capture_conversation_turn.call_args.kwargs
    assert kwargs["access_context"]["actor_id"] == "7"
    assert kwargs["access_context"]["tenant_id"] == "2"
    assert "dataset.write" in kwargs["access_context"]["permissions"]


def test_anonymous_app_service_reply_does_not_persist_memory(memory, monkeypatch):
    _, _, namespace, store, _ = memory
    from app.application.ai_chat_app_service import AIChatApplicationService

    service = AIChatApplicationService.__new__(AIChatApplicationService)
    reply = {"success": True, "response": "synthetic completed response"}
    monkeypatch.setattr(service, "_process_chat_impl", lambda *args: reply)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    result = service.process_chat(namespace, "确认", context={"session_id": "anonymous"})
    assert result == reply
    assert count(store) == 0
