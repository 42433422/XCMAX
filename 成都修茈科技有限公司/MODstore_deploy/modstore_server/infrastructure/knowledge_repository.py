"""Knowledge index adapter (占位，可接 ``knowledge_vector_store_redis``)."""

from __future__ import annotations

from modstore_server.domain.knowledge.types import KnowledgeIndexRef


class InMemoryKnowledgeIndexRepository:
    def describe(self, ref: KnowledgeIndexRef) -> dict:
        return {"collection_id": ref.collection_id, "user_id": ref.user_id, "backend": "memory"}


__all__ = ["InMemoryKnowledgeIndexRepository"]
