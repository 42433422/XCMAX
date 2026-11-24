from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.dataset_rag_app_service import DatasetAccessContext
from app.application.persy_memory_app_service import (
    PersyMemoryApplicationService,
    extract_explicit_memories,
    merge_memory_graph,
)
from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _access(actor: str = "7", tenant: str = "2") -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )


def _service() -> PersyMemoryApplicationService:
    UserMemoryStore._instance = None
    UserMemoryService._instance = None
    return PersyMemoryApplicationService(UserMemoryService(storage_type="memory"))


def test_extracts_explicit_people_preferences_and_enterprise_facts() -> None:
    rows = extract_explicit_memories(
        "我叫王敏；我偏好下午沟通；客户北辰科技的负责人是李明；北辰科技位于苏州"
    )

    statements = {row["value"]["statement"] for row in rows}
    assert statements == {
        "用户的姓名是王敏",
        "用户的偏好是下午沟通",
        "北辰科技的负责人是李明",
        "北辰科技位于苏州",
    }
    assert all(len(row["value"]["entities"]) == 2 for row in rows)

    comma_rows = extract_explicit_memories("我叫王敏，我偏好下午沟通")
    assert [row["value"]["statement"] for row in comma_rows] == [
        "用户的姓名是王敏",
        "用户的偏好是下午沟通",
    ]


@pytest.mark.parametrize("model_verified", [False, True])
def test_capture_is_deduplicated_governed_and_carries_provenance(
    monkeypatch, model_verified
) -> None:
    service = _service()
    backend = MagicMock()
    backend.enabled = False
    backend.extract_candidates.return_value = (
        extract_explicit_memories("我偏好每周二下午沟通") if model_verified else None
    )
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )

    first = service.capture_conversation_turn(
        access_context=_access(),
        user_message="我偏好每周二下午沟通",
        assistant_message="我会记住。",
        session_id="chat-1",
        source="smart-chat",
    )
    second = service.capture_conversation_turn(
        access_context=_access(),
        user_message="我偏好每周二下午沟通",
        assistant_message="收到。",
        session_id="chat-2",
        source="smart-chat",
    )
    listed = service.list_memories(access_context=_access())

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert listed["summary"] == {
        "total": 1,
        "active": int(model_verified),
        "pending": int(not model_verified),
        "returned": 1,
    }
    memory = listed["memories"][0]
    assert memory["status"] == ("active" if model_verified else "pending")
    assert memory["requires_user_confirmation"] is not model_verified
    assert memory["evidence"][0]["session_id"] == "chat-1"
    assert memory["statement"] == "用户的偏好是每周二下午沟通"

    service.mutate(access_context=_access(), memory_id=memory["memory_id"], action="delete")
    repeated = service.capture_conversation_turn(
        access_context=_access(), user_message="我偏好每周二下午沟通"
    )
    assert repeated["created_count"] == 0
    assert service.list_memories(access_context=_access(), status="active")["memories"] == []


def test_memory_candidate_deduplication_is_thread_safe() -> None:
    service = _service().memory_service

    def propose(_: int) -> dict:
        return service.propose_memory_candidate(
            "concurrent-user",
            "preference",
            "用户.偏好",
            {"statement": "用户的偏好是下午沟通"},
            source="chat_trace",
            evidence=[{"source": "concurrency-test"}],
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(propose, range(40)))

    assert sum(result.get("created") is True for result in results) == 1
    assert len(service.list_memories("concurrent-user")) == 1


def test_confirm_query_reinforces_and_projects_entity_graph() -> None:
    service = _service()
    captured = service.capture_conversation_turn(
        access_context=_access(),
        user_message="客户北辰科技的负责人是李明",
        session_id="chat-1",
    )
    memory_id = captured["candidates"][0]["memory_id"]

    confirmed = service.mutate(
        access_context=_access(),
        memory_id=memory_id,
        action="confirm",
    )
    queried = service.query(
        access_context=_access(),
        query="北辰科技负责人",
        top_k=3,
    )
    listed = service.list_memories(access_context=_access(), status="active")
    graph = service.graph(access_context=_access())

    assert confirmed["success"] is True
    assert queried["chunks"][0]["metadata"]["memory_id"] == memory_id
    assert listed["memories"][0]["recall_count"] == 1
    assert listed["memories"][0]["last_recalled_at"]
    assert any(node["id"] == f"memory:{memory_id}" for node in graph["nodes"])
    assert any(node["metadata"].get("entity_name") == "北辰科技" for node in graph["nodes"])
    assert any(edge["label"] == "主体" for edge in graph["edges"])


def test_query_excludes_pending_memories_shown_for_review() -> None:
    service = _service()
    service.capture_conversation_turn(
        access_context=_access(),
        user_message="客户北辰科技的负责人是李明",
        session_id="chat-1",
    )

    queried = service.query(access_context=_access(), query="北辰科技负责人", top_k=3)

    assert queried["success"] is True
    assert queried["chunks"] == []
    assert service.list_memories(access_context=_access())["memories"][0]["status"] == "pending"


def test_clear_memories_removes_all_visible_records() -> None:
    service = _service()
    service.capture_conversation_turn(
        access_context=_access(),
        user_message="客户北辰科技的负责人是李明",
        session_id="chat-1",
    )

    cleared = service.clear_memories(
        access_context=DatasetAccessContext(
            actor_id="7", tenant_id="2", permissions=frozenset({"dataset.write"})
        )
    )

    assert cleared["success"] is True
    assert cleared["deleted_memories"] == 1
    remaining = service.list_memories(access_context=_access())["memories"]
    assert [row for row in remaining if row.get("status") in {"pending", "active"}] == []


def test_user_memory_is_private_while_tenant_memory_is_shared() -> None:
    service = _service()
    alice = _access(actor="alice", tenant="2")
    bob = _access(actor="bob", tenant="2")
    other_tenant = _access(actor="carol", tenant="3")

    service.capture_conversation_turn(
        access_context=alice,
        user_message="我喜欢简洁报告",
        scope="user",
    )
    service.capture_conversation_turn(
        access_context=alice,
        user_message="客户北辰科技的沟通时间是周二下午",
        scope="tenant",
    )

    alice_rows = service.list_memories(access_context=alice)["memories"]
    bob_rows = service.list_memories(access_context=bob)["memories"]
    other_rows = service.list_memories(access_context=other_tenant)["memories"]

    assert {(row["scope"], row["status"]) for row in alice_rows} == {
        ("user", "pending"),
        ("tenant", "pending"),
    }
    assert [row["scope"] for row in bob_rows] == ["tenant"]
    assert other_rows == []


def test_mutation_is_limited_to_current_user_and_tenant_owners() -> None:
    service = _service()
    captured = service.capture_conversation_turn(
        access_context=_access(actor="alice"),
        user_message="我住在杭州",
    )
    memory_id = captured["candidates"][0]["memory_id"]

    denied = service.mutate(
        access_context=_access(actor="bob"),
        memory_id=memory_id,
        action="confirm",
    )
    corrected = service.mutate(
        access_context=_access(actor="alice"),
        memory_id=memory_id,
        action="correct",
        patch={
            "key": "用户.所在地",
            "value": {
                "statement": "用户的所在地是上海",
                "subject": "用户",
                "predicate": "所在地",
                "object": "上海",
                "entities": [],
            },
        },
        reason="用户纠正",
    )
    deleted = service.mutate(
        access_context=_access(actor="alice"),
        memory_id=memory_id,
        action="delete",
        reason="不再保留",
    )

    assert captured["candidates"][0]["status"] == "pending"
    assert denied["error_code"] == "persy_memory_not_found"
    assert corrected["memory"]["statement"] == "用户的所在地是上海"
    assert deleted["memory"]["status"] == "deleted"
    assert (
        service.capture_conversation_turn(
            access_context=_access(actor="alice"), user_message="我住在杭州"
        )["created_count"]
        == 0
    )


def test_merge_memory_graph_preserves_bounds_and_updates_stats() -> None:
    base = {
        "success": True,
        "dataset_id": "persy-knowledge",
        "nodes": [{"id": "persy:persy-knowledge", "label": "Persy", "type": "core"}],
        "edges": [],
        "stats": {"document_count": 0},
    }
    memory = {
        "success": True,
        "nodes": [
            {"id": "memory:m1", "label": "记忆一", "type": "memory"},
            {"id": "memory-topic:entity", "label": "人物与事实", "type": "topic"},
        ],
        "edges": [
            {
                "id": "edge:persy:topic",
                "source": "persy:persy-knowledge",
                "target": "memory-topic:entity",
            },
            {
                "id": "edge:topic:memory",
                "source": "memory-topic:entity",
                "target": "memory:m1",
            },
        ],
        "stats": {"memory_count": 1},
    }

    merged = merge_memory_graph(base, memory, limit=20)

    assert len(merged["nodes"]) == 3
    assert len(merged["edges"]) == 2
    assert merged["stats"]["memory_count"] == 1
    assert merged["stats"]["categories"] == {"core": 1, "memory": 1, "topic": 1}


def test_missing_trusted_scope_fails_closed() -> None:
    service = _service()

    result = service.capture_conversation_turn(
        access_context=None,
        user_message="我喜欢下午沟通",
    )

    assert result["success"] is False
    assert result["error_code"] == "persy_memory_scope_missing"


def test_completed_chat_turn_only_proposes_governed_candidates(trusted_actor) -> None:
    from app.application.agent_task_context import scoped_conversation_user_id

    actor = trusted_actor(user_id=7, tenant_id=2, permissions=["dataset.read", "dataset.write"])
    vector_service = MagicMock()
    persy_service = MagicMock()
    context = {
        **actor.context,
        "local_user_id": 7,
        "session_id": "chat-9",
        "_dataset_access_context_trusted": True,
        "_dataset_access_context": {
            "actor_id": "7",
            "tenant_id": "2",
            "permissions": ["dataset.read", "dataset.write"],
            "is_admin": False,
        },
        "persy_memory_scope": "tenant",
    }

    with (
        patch(
            "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
            return_value=vector_service,
        ),
        patch(
            "app.application.persy_memory_app_service.get_persy_memory_app_service",
            return_value=persy_service,
        ),
    ):
        AIChatApplicationService._persist_recallable_chat_turn(
            user_id=scoped_conversation_user_id("7", context),
            message="客户北辰科技的负责人是李明",
            source="smart-chat",
            context=context,
            response_data={"success": True, "response": "已记录。", "action": "answer"},
        )

    vector_service.ingest_chunks.assert_not_called()
    persy_service.capture_conversation_turn.assert_called_once_with(
        access_context={**context["_dataset_access_context"], "mod_id": ""},
        user_message="客户北辰科技的负责人是李明",
        assistant_message="已记录。",
        session_id="chat-9",
        source="smart-chat",
        scope="tenant",
    )


@pytest.mark.parametrize("memories", [None, {}, "invalid", [None, 7]])
def test_invalid_memory_listing_never_deletes_or_returns_records(memories):
    service = _service()
    with (
        patch.object(
            service, "list_memories", return_value={"success": True, "memories": memories}
        ),
        patch.object(service, "mutate") as mutate,
    ):
        assert service.clear_memories(access_context=_access())["deleted_memories"] == 0
        assert service.query(access_context=_access(), query="missing")["memories"] == []
        mutate.assert_not_called()


def test_graph_recall_and_historical_review_use_existing_authority() -> None:
    from app.application.persy_memory_utils import _memory_owner_id

    service = _service()
    access = _access()
    owner = _memory_owner_id(access, "user")

    def fact(subject, object_text, subject_type, object_type, predicate):
        return {
            "subject": subject,
            "predicate": predicate,
            "object": object_text,
            "statement": f"{subject} {predicate} {object_text}",
            "entities": [
                {"name": subject, "type": subject_type, "role": "subject"},
                {"name": object_text, "type": object_type, "role": "object"},
            ],
        }

    def add(value, *, scope="user", confirm=True):
        target = owner if scope == "user" else _memory_owner_id(access, scope)
        proposed = service.memory_service.propose_memory_candidate(
            target,
            "entity",
            value["statement"],
            value,
            source="chat_trace",
            evidence=[{"kind": "conversation_turn"}],
        )
        memory_id = proposed["candidate"]["memory_id"]
        if confirm:
            assert service.mutate(
                access_context=access,
                memory_id=memory_id,
                action="confirm",
            )["success"]
        return memory_id

    first = add(fact("Acme Corp", "Alice Example", "organization", "person", "employs"))
    second = add(fact("Alice Example", "Phoenix Project", "person", "project", "leads"))
    pending = add(
        fact("Alice Example", "Hidden Project", "person", "project", "reviews"), confirm=False
    )
    other_scope = add(
        fact("Alice Example", "Tenant Project", "person", "project", "reviews"), scope="tenant"
    )
    one = service.query(access_context=access, query="Acme Corp", max_hops=1, reinforce=False)
    two = service.query(access_context=access, query="Acme Corp", max_hops=2, reinforce=False)
    assert second not in {row["memory_id"] for row in one["memories"]}
    assert {first, second} <= {row["memory_id"] for row in two["memories"]}
    assert not {pending, other_scope} & {row["memory_id"] for row in two["memories"]}
    related = next(row for row in two["memories"] if row["memory_id"] == second)
    assert [step["memory_id"] for step in related["relation_path"]] == [first, second]

    active = next(row for row in two["memories"] if row["memory_id"] == first)
    instant = active["recorded_at_utc"]
    changed = service.mutate(
        access_context=access,
        memory_id=first,
        action="correct",
        patch={"value": fact("Acme Corp", "Bob Example", "organization", "person", "employs")},
    )
    assert changed["success"]
    historical = service.query(access_context=access, query="Acme Corp", as_of=instant)
    old = next(row for row in historical["memories"] if row["memory_id"] == first)
    assert old["value"]["object"] == "Alice Example"
    assert old["historical"] and not old["eligible_for_planner"]
    assert historical["chunks"] == []
    assert service.mutate(access_context=access, memory_id=first, action="delete")["success"]
    after_delete = service.query(access_context=access, query="Acme Corp", as_of=instant)
    assert first not in {row["memory_id"] for row in after_delete["memories"]}
    assert not service.query(
        access_context=access,
        query="Acme Corp",
        as_of="2026-01-01T12:00:00",
    )["success"]


def test_shared_memory_lifecycle_is_governed_across_actors_and_mods(monkeypatch) -> None:
    service = _service()
    backend = MagicMock()
    backend.extract_candidates.return_value = None
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )

    def access(actor, tenant="2", mod="sales", write=True):
        return DatasetAccessContext(
            actor_id=actor,
            tenant_id=tenant,
            mod_id=mod,
            permissions=frozenset(
                {"dataset.read", "dataset.write"} if write else {"dataset.read"}
            ),
        )

    alice = access("alice")
    bob = access("bob")
    reader = access("reader", write=False)
    foreign = access("carol", tenant="3")
    other_mod = access("alice", mod="finance")
    statement = "客户北辰科技的负责人是李明"

    def capture(actor, text=statement, scope="tenant"):
        return service.capture_conversation_turn(
            access_context=actor, user_message=text, scope=scope
        )

    def recall(actor):
        return service.query(
            access_context=actor, query="北辰科技负责人", reinforce=False, max_hops=0
        )["memories"]

    private = capture(alice, "客户北辰科技的沟通时间是周二下午", "user")
    private_id = private["candidates"][0]["memory_id"]
    assert service.mutate(
        access_context=alice, memory_id=private_id, action="confirm"
    )["success"]
    created = capture(alice)
    mid = created["candidates"][0]["memory_id"]
    assert not recall(bob)
    assert not service.mutate(
        access_context=reader, memory_id=mid, action="confirm"
    )["success"]
    assert service.mutate(access_context=alice, memory_id=mid, action="confirm")["success"]
    assert {row["memory_id"] for row in recall(bob)} == {mid}
    assert {row["memory_id"] for row in recall(reader)} == {mid}
    assert not recall(foreign)
    assert not recall(other_mod)
    assert not service.mutate(access_context=foreign, memory_id=mid, action="delete")[
        "success"
    ]

    replacement = extract_explicit_memories("客户北辰科技的负责人是王明")[0]
    assert service.mutate(
        access_context=alice, memory_id=mid, action="correct",
        patch={"key": replacement["key"], "value": replacement["value"]},
    )["success"]
    assert recall(bob)[0]["value"]["object"] == "王明"
    assert capture(bob)["created_count"] == 0
    assert service.mutate(access_context=alice, memory_id=mid, action="delete")["success"]
    assert not recall(bob)
    assert capture(bob, "客户北辰科技的负责人是王明")["created_count"] == 0
    assert not recall(reader)


def test_lexical_recall_revalidates_revision_without_graph_path(monkeypatch) -> None:
    service = _service()
    access = _access()
    backend = MagicMock()
    backend.extract_candidates.return_value = None
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )
    created = service.capture_conversation_turn(
        access_context=access, user_message="客户北辰科技的负责人是李明"
    )
    mid = created["candidates"][0]["memory_id"]
    assert service.mutate(access_context=access, memory_id=mid, action="confirm")["success"]
    original = service.list_memories
    reads = 0

    def revoke_between_reads(**kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            assert service.mutate(
                access_context=access, memory_id=mid, action="delete"
            )["success"]
        return original(**kwargs)

    monkeypatch.setattr(service, "list_memories", revoke_between_reads)
    result = service.query(
        access_context=access, query="北辰科技负责人", max_hops=0, reinforce=False
    )
    assert result["memories"] == []
    assert result["chunks"] == []
    assert result["revalidation_dropped"] == 1
    assert result["coverage_complete"] is False
