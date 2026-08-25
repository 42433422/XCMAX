from __future__ import annotations

from app.application.user_memory_vector_app_service import (
    UserMemoryRagApplicationService,
    UserMemoryVectorIngestApplicationService,
)
from app.infrastructure.persistence.user_memory_vector_store import (
    SQLiteUserMemoryVectorStore,
)


def test_chat_turn_is_persisted_and_recalled_from_sqlite(tmp_path) -> None:
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "user-memory.db"))
    ingest = UserMemoryVectorIngestApplicationService(vector_store=store)
    recall = UserMemoryRagApplicationService(vector_store=store)
    chunk = ingest.build_chat_turn_chunk(
        user_id="user-7",
        user_message="客户北辰科技的负责人是李明",
        assistant_message="已记录北辰科技的负责人信息。",
        session_id="conversation-1",
        source="smart-chat",
    )

    written = ingest.ingest_chunks("user-7", [chunk])
    result = recall.query("user-7", "北辰科技负责人是谁", top_k=3)

    assert written["success"] is True
    assert written["written"] == 1
    assert result["success"] is True
    assert result["hits"]
    assert "负责人是李明" in result["hits"][0]["content"]
    assert result["hits"][0]["metadata"]["session_id"] == "conversation-1"
