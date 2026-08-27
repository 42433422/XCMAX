from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.dataset_rag_app_service import DatasetAccessContext
from app.application.persy_memory_app_service import (
    PersyMemoryApplicationService,
    extract_explicit_memories,
    merge_memory_graph,
)
from app.services.user_memory_service import UserMemoryService, UserMemoryStore


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


def test_capture_is_deduplicated_governed_and_carries_provenance() -> None:
    service = _service()

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
    assert listed["summary"] == {"total": 1, "active": 0, "pending": 1, "returned": 1}
    memory = listed["memories"][0]
    assert memory["status"] == "pending"
    assert memory["requires_user_confirmation"] is True
    assert memory["evidence"][0]["session_id"] == "chat-1"
    assert memory["statement"] == "用户的偏好是每周二下午沟通"


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

    assert {row["scope"] for row in alice_rows} == {"user", "tenant"}
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

    assert denied["error_code"] == "persy_memory_not_found"
    assert corrected["memory"]["statement"] == "用户的所在地是上海"
    assert deleted["memory"]["status"] == "deleted"


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


def test_completed_chat_turn_is_sent_to_vector_and_structured_memory() -> None:
    vector_service = MagicMock()
    vector_service.build_chat_turn_chunk.return_value = object()
    persy_service = MagicMock()
    context = {
        "session_id": "chat-9",
        "_dataset_access_context_trusted": True,
        "_dataset_access_context": {
            "actor_id": "7",
            "tenant_id": "2",
            "permissions": ["dataset.read", "dataset.write"],
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
            user_id="7",
            message="客户北辰科技的负责人是李明",
            source="smart-chat",
            context=context,
            response_data={"success": True, "response": "已记录。", "action": "answer"},
        )

    vector_service.ingest_chunks.assert_called_once()
    assert vector_service.build_chat_turn_chunk.call_args.kwargs["user_id"] == "2:7"
    assert vector_service.ingest_chunks.call_args.args[0] == "2:7"
    persy_service.capture_conversation_turn.assert_called_once_with(
        access_context=context["_dataset_access_context"],
        user_message="客户北辰科技的负责人是李明",
        assistant_message="已记录。",
        session_id="chat-9",
        source="smart-chat",
        scope="tenant",
    )


def test_structured_memory_capture_continues_when_vector_write_fails() -> None:
    vector_service = MagicMock()
    vector_service.build_chat_turn_chunk.return_value = object()
    vector_service.ingest_chunks.side_effect = OSError("vector store unavailable")
    persy_service = MagicMock()
    context = {
        "session_id": "chat-10",
        "_dataset_access_context_trusted": True,
        "_dataset_access_context": {
            "actor_id": "7",
            "tenant_id": "2",
            "permissions": ["dataset.read", "dataset.write"],
        },
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
            user_id="7",
            message="我偏好每周一上午沟通",
            source="smart-chat",
            context=context,
            response_data={"success": True, "response": "已记录。", "action": "answer"},
        )

    persy_service.capture_conversation_turn.assert_called_once()
