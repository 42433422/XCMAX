from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.application.ai_chat.dialogue_memory import conversation_key
from app.application.dataset_rag_app_service import DatasetAccessContext
from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore


@pytest.fixture
def memory(monkeypatch, tmp_path):
    from app.application.user_memory_vector_app_service import (
        UserMemoryVectorIngestApplicationService,
    )
    from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore

    monkeypatch.setenv("XCAGI_MEMORY_AUTO_REVIEW", "off")
    monkeypatch.setattr(UserMemoryStore, "_instance", None)
    monkeypatch.setattr(UserMemoryService, "_instance", None)
    authority = UserMemoryService(storage_type="memory")
    backend = MagicMock()
    backend.enabled = False
    backend.extract_candidates.return_value = None
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )
    ingest = UserMemoryVectorIngestApplicationService(
        vector_store=SQLiteUserMemoryVectorStore(str(tmp_path / "memory.sqlite"))
    )
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: ingest,
    )
    return PersyMemoryApplicationService(authority)


def access(actor="7", tenant="2", mod="crm", write=True):
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        mod_id=mod,
        permissions=frozenset({"dataset.read", "dataset.write"} if write else {"dataset.read"}),
    )


def capture(memory, message, session="history-session"):
    return memory.capture_conversation_turn(
        access_context=access(), user_message=message, session_id=session
    )["candidates"][0]


def receipt(message, *, tenant="2", mod="crm", actor="7", session="history-session"):
    key = conversation_key(
        {"actor_id": actor, "tenant_id": tenant, "mod_id": mod, "session_id": session}
    )
    return (
        31, session, actor, "user", message, "",
        json.dumps({"business_harness": {"conversation_key": key, "recall_bound": True}}),
        "",
    )


def test_verified_history_preserves_id_and_advances_revision(memory, monkeypatch):
    row = capture(memory, "我喜欢简洁报告")
    assert row["status"] == "pending"
    monkeypatch.setenv("XCAGI_MEMORY_AUTO_REVIEW", "1")
    reader = MagicMock(return_value=[receipt("我喜欢简洁报告")])
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.ConversationService.get_session_messages",
        reader,
    )
    outcome = memory.auto_review_pending(access_context=access(), limit=1)
    assert outcome["activated"] == 1
    updated = memory.list_memories(access_context=access())["memories"][0]
    assert updated["memory_id"] == row["memory_id"]
    assert updated["revision"] == row["revision"] + 1
    assert updated["auto_review_receipt"]["message_id"] == "31"
    assert updated["status"] == "active"
    assert memory.auto_review_pending(access_context=access())["activated"] == 0
    reader.assert_called_once_with("history-session", limit=1000, user_id="7")


@pytest.mark.parametrize("kind", ["wrong_tenant", "wrong_mod", "wrong_message", "no_receipt"])
def test_unverified_history_never_activates(memory, monkeypatch, kind):
    row = capture(memory, "我喜欢简洁报告")
    monkeypatch.setenv("XCAGI_MEMORY_AUTO_REVIEW", "1")
    receipts = {
        "wrong_tenant": [receipt("我喜欢简洁报告", tenant="3")],
        "wrong_mod": [receipt("我喜欢简洁报告", mod="finance")],
        "wrong_message": [receipt("我喜欢详细报告")],
        "no_receipt": [],
    }
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.ConversationService.get_session_messages",
        lambda *args, **kwargs: receipts[kind],
    )
    assert memory.auto_review_pending(access_context=access())["activated"] == 0
    assert memory.list_memories(access_context=access())["memories"][0]["status"] == "pending"
    assert row["memory_id"]


def test_historical_review_obeys_scope_permissions_and_cursor(memory, monkeypatch):
    capture(memory, "我喜欢简洁报告")
    capture(memory, "我习惯下午沟通")
    monkeypatch.setenv("XCAGI_MEMORY_AUTO_REVIEW", "1")
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.ConversationService.get_session_messages",
        lambda *args, **kwargs: [],
    )
    assert not memory.auto_review_pending(access_context=access(write=False))["success"]
    assert memory.auto_review_pending(access_context=access(tenant="3"))["examined"] == 0
    first = memory.auto_review_pending(access_context=access(), limit=1)
    assert first["examined"] == 1 and first["next_cursor"]
    second = memory.auto_review_pending(
        access_context=access(), limit=1, after=first["next_cursor"]
    )
    assert second["examined"] == 1 and second["next_cursor"] is None


def test_revoked_candidate_is_not_reactivated(memory, monkeypatch):
    row = capture(memory, "我喜欢简洁报告")
    assert memory.mutate(access_context=access(), memory_id=row["memory_id"], action="delete")["success"]
    monkeypatch.setenv("XCAGI_MEMORY_AUTO_REVIEW", "1")
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.ConversationService.get_session_messages",
        lambda *args, **kwargs: [receipt("我喜欢简洁报告")],
    )
    assert memory.auto_review_pending(access_context=access())["activated"] == 0
