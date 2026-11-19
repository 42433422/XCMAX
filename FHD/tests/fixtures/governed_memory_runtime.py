"""Real offline authority/projection stack shared by memory migration tests."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.application.agent_task_context import scoped_personal_memory_id
from app.application.user_memory_vector_app_service import (
    UserMemoryRagApplicationService,
    UserMemoryVectorIngestApplicationService,
)
from app.domain.shared_services import user_memory_service as authority_module
from app.infrastructure.llm.embedding_service import EmbeddingService
from app.infrastructure.memory import mem0_backend
from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore


def owner_id(actor: int = 7, *, tenant: int = 2, mod: str = "sales") -> str:
    return scoped_personal_memory_id({"local_user_id": actor, "tenant_id": tenant, "mod_id": mod})


@dataclass
class GovernedMemoryRuntime:
    directory: Path
    authority: authority_module.UserMemoryService
    store: SQLiteUserMemoryVectorStore
    ingest: UserMemoryVectorIngestApplicationService
    rag: UserMemoryRagApplicationService
    backend: mem0_backend.Mem0LongTermMemory

    def propose(self, text: str = "采购预算：50万元", *, owner: str | None = None, key="budget"):
        result = self.authority.propose_memory_candidate(
            owner or owner_id(),
            "entity",
            key,
            {"statement": text},
            source="user_explicit",
            confidence=0.9,
            evidence=[{"source": "user_message", "session_id": "first-session", "quote": text}],
        )
        assert result["success"]
        return result["candidate"]

    def confirm(self, candidate: dict, *, owner: str | None = None):
        result = self.authority.confirm_memory_candidate(
            owner or owner_id(), candidate["memory_id"]
        )
        assert result["success"]
        assert result["projection"] == {"user_vector": "current", "mem0": "current"}
        return result["memory"]

    def native_rows(self, owner: str | None = None):
        return self.backend._active().get_all(
            filters={"user_id": owner or owner_id()}, top_k=100, show_expired=True
        )["results"]

    def vector_rows(self, owner: str | None = None):
        # These cases retain at most one canonical projection per scoped owner.
        limit = 1
        with self.store._get_conn() as connection:
            rows = connection.execute(
                "SELECT chunk_id, content, metadata FROM user_memory_vector_chunks WHERE index_id = ?",
                (owner or owner_id(),),
            ).fetchmany(limit + 1)
        assert len(rows) <= limit, "Unexpected duplicate governed vector projection"
        return rows

    def restart(self) -> None:
        """Release Qdrant handles and reconstruct every cache from the same disk files."""
        mem0_backend.reset_long_term_memory_for_tests()
        EmbeddingService.reset_singleton_for_tests()
        authority_module.UserMemoryStore._instance = None
        authority_module.UserMemoryService._instance = None
        self.authority = authority_module.UserMemoryService(storage_type="json")
        self.store = SQLiteUserMemoryVectorStore(str(self.directory / "user-vectors.sqlite"))
        self.ingest = UserMemoryVectorIngestApplicationService(vector_store=self.store)
        self.rag = UserMemoryRagApplicationService(vector_store=self.store)
        self.backend = mem0_backend.get_long_term_memory()
        assert self.backend.enabled


@pytest.fixture
def governed_memory(tmp_path, monkeypatch):
    if (
        importlib.util.find_spec("mem0") is None
        or importlib.util.find_spec("qdrant_client") is None
    ):
        pytest.skip("native Mem0/Qdrant optional dependencies are not installed")
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "authority.json"))
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(tmp_path / "authority"))
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_DIR", str(tmp_path / "mem0"))
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_BACKEND", "mem0")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("FHD_EMBEDDING_MODE", "hash")
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_MIN_SCORE", "0")
    monkeypatch.setenv("XCAGI_MEMORY_RAG_MIN_SCORE", "0")
    monkeypatch.setenv("MEM0_TELEMETRY", "False")
    monkeypatch.setattr(authority_module.UserMemoryStore, "_instance", None)
    monkeypatch.setattr(authority_module.UserMemoryService, "_instance", None)
    EmbeddingService.reset_singleton_for_tests()
    mem0_backend.reset_long_term_memory_for_tests()
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "user-vectors.sqlite"))
    runtime = GovernedMemoryRuntime(
        tmp_path,
        authority_module.UserMemoryService(storage_type="json"),
        store,
        UserMemoryVectorIngestApplicationService(vector_store=store),
        UserMemoryRagApplicationService(vector_store=store),
        mem0_backend.get_long_term_memory(),
    )
    monkeypatch.setattr(authority_module, "get_user_memory_service", lambda: runtime.authority)
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: runtime.ingest,
    )
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_rag_app_service",
        lambda: runtime.rag,
    )
    assert runtime.backend.enabled
    try:
        yield runtime
    finally:
        mem0_backend.reset_long_term_memory_for_tests()
        EmbeddingService.reset_singleton_for_tests()
