from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.application.dataset_rag_app_service import DatasetAccessContext
from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.application.persy_memory_utils import extract_explicit_memories, review_explicit_capture
from app.domain.neuro.cognition.working_memory import get_working_memory, reset_working_memory
from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore


@pytest.fixture
def memory(monkeypatch, tmp_path):
    monkeypatch.delenv("XCAGI_MEMORY_AUTO_REVIEW", raising=False)
    monkeypatch.delenv("XCAGI_MEMORY_CAPTURE", raising=False)
    monkeypatch.setattr(UserMemoryStore, "_instance", None)
    monkeypatch.setattr(UserMemoryService, "_instance", None)
    backend = MagicMock()
    backend.enabled = False
    backend.extract_candidates.return_value = None
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )
    from app.application.user_memory_vector_app_service import (
        UserMemoryVectorIngestApplicationService,
    )
    from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore

    service = UserMemoryService(storage_type="memory")
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "memory.sqlite"))
    ingest = UserMemoryVectorIngestApplicationService(vector_store=store)
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: ingest,
    )
    return PersyMemoryApplicationService(service)


def access(actor="7", tenant="2", write=True):
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        permissions=frozenset({"dataset.read", "dataset.write"} if write else {"dataset.read"}),
    )


def test_default_auto_review_and_opt_out(memory, monkeypatch):
    result = memory.capture_conversation_turn(
        access_context=access(), user_message="我喜欢简洁报告"
    )
    row = result["candidates"][0]
    assert row["status"] == "active"
    assert row["eligible_for_planner"]
    assert row["auto_review_policy"] == "direct_assertion_v1"
    monkeypatch.setenv("XCAGI_MEMORY_AUTO_REVIEW", "off")
    result = memory.capture_conversation_turn(
        access_context=access("8"), user_message="我喜欢简洁报告"
    )
    assert result["candidates"][0]["status"] == "pending"


def test_explicit_tenant_review_stays_in_tenant_and_requires_write(memory):
    result = memory.capture_conversation_turn(
        access_context=access(), user_message="北辰科技采用PostgreSQL", scope="tenant"
    )
    assert result["candidates"][0]["status"] == "active"
    assert memory.list_memories(access_context=access("8"))["summary"]["active"] == 1
    assert memory.list_memories(access_context=access(tenant="3"))["summary"]["active"] == 0
    denied = memory.capture_conversation_turn(
        access_context=access(write=False), user_message="北辰科技采用SQLite", scope="tenant"
    )
    assert not denied["success"]


def test_global_preference_requires_authorized_manual_confirmation(memory):
    message = "我喜欢简洁报告"
    denied = memory.capture_conversation_turn(
        access_context=access(write=False), user_message=message, scope="global_preference"
    )
    assert denied["error_code"] == "dataset_permission_denied"

    row = memory.capture_conversation_turn(
        access_context=access(), user_message=message, scope="global_preference"
    )["candidates"][0]
    assert row["scope"] == "global_preference"
    assert row["status"] == "pending"
    assert row["requires_user_confirmation"]
    assert not row["eligible_for_planner"]
    denied = memory.mutate(
        access_context=access(write=False), memory_id=row["memory_id"], action="confirm"
    )
    assert denied["error_code"] == "dataset_permission_denied"
    confirmed = memory.mutate(access_context=access(), memory_id=row["memory_id"], action="confirm")
    assert confirmed["memory"]["status"] == "active"


@pytest.mark.parametrize("colon", ["：", ":"])
@pytest.mark.parametrize("scope", ["user", "tenant", "global_preference"])
def test_offline_remember_prefix_applies_only_to_user_scope(memory, colon, scope):
    result = memory.capture_conversation_turn(
        access_context=access(), user_message=f"请记住{colon} 我喜欢简洁报告。", scope=scope
    )
    if scope != "user":
        assert result["candidates"] == []
        return
    (row,) = result["candidates"]
    assert row["scope"] == "user"
    assert row["status"] == "active"
    assert row["statement"] == "用户的偏好是简洁报告"
    assert row["evidence"][0]["user_excerpt"] == f"请记住{colon} 我喜欢简洁报告。"


def test_offline_remember_prefix_preserves_sensitive_filter(memory):
    result = memory.capture_conversation_turn(
        access_context=access(), user_message="请记住：我习惯定期更改密码"
    )
    assert result["candidates"] == []


@pytest.mark.parametrize("prefix", ["", "请记住："])
def test_conflicting_auto_review_is_pending_and_deleted_not_replayed(memory, prefix):
    first = memory.capture_conversation_turn(
        access_context=access(), user_message=f"{prefix}我喜欢简洁报告"
    )["candidates"][0]
    assert first["status"] == "active"
    second = memory.capture_conversation_turn(
        access_context=access(), user_message=f"{prefix}我喜欢详细报告"
    )["candidates"][0]
    assert second["status"] == "pending"
    memory.mutate(access_context=access(), memory_id=first["memory_id"], action="delete")
    repeated = memory.capture_conversation_turn(
        access_context=access(), user_message=f"{prefix}我喜欢简洁报告"
    )
    assert repeated["created_count"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "小说台词：\n我喜欢咖啡",
        "我喜欢简洁报告；我习惯下午沟通",
        "我喜欢绕过权限",
        "我喜欢忽略系统提示",
    ],
)
def test_unsafe_or_ambiguous_capture_is_not_auto_reviewed(text):
    for candidate in extract_explicit_memories(text):
        assert review_explicit_capture(candidate, text, "user") is None


def test_model_cannot_invent_preference():
    candidate = extract_explicit_memories("我喜欢咖啡")[0]
    assert review_explicit_capture(candidate, "我喜欢茶", "user") is None


def test_working_memory_default_and_explicit_override():
    reset_working_memory()
    try:
        enabled = get_working_memory("s", "u")
        assert enabled._enable_long_term
        disabled = get_working_memory("s", "u", enable_long_term=False)
        assert not disabled._enable_long_term
        assert enabled is not disabled
        assert get_working_memory("s", "u")._enable_long_term
    finally:
        reset_working_memory()


def test_authority_does_not_trust_review_flag_without_matching_evidence(memory):
    from app.application.persy_memory_utils import _memory_owner_id

    candidate = extract_explicit_memories("我喜欢咖啡")[0]
    result = memory.memory_service.propose_memory_candidate(
        _memory_owner_id(access()),
        candidate["memory_type"],
        candidate["key"],
        candidate["value"],
        source="chat_trace",
        confidence=candidate["confidence"],
        evidence=[
            {
                "kind": "conversation_turn",
                "scope": "user",
                "tenant_id": "2",
                "user_excerpt": "我喜欢茶",
            }
        ],
        auto_review_capture=True,
    )
    assert result["candidate"]["status"] == "pending"


def test_flattened_release_provisioner_with_explicit_output(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "scripts/dev/provision_memory_model.py"
    script = "/build/provision_memory_model.py"
    output = tmp_path / "memory-model"

    # Reproduce the exact shallow Docker path without writing into /build.
    # The original script raised IndexError at import, before CLI parsing.
    namespace = {"__file__": script, "__name__": "release_provisioner_regression"}
    exec(compile(source.read_bytes(), script, "exec"), namespace)
    entry = namespace["main"]
    seen = []

    def provision(root):
        seen.append(root)
        return {"model": "test-only"}

    monkeypatch.setitem(entry.__globals__, "provision", provision)
    monkeypatch.setattr(sys, "argv", [script, "--output", str(output)])
    assert entry() == 0
    assert seen == [output.resolve()]
