from __future__ import annotations

from typing import Protocol

from modstore_server.domain.knowledge.knowledge_types import KnowledgeIndexRef


class KnowledgeIndexRepository(Protocol):
    def describe(self, ref: KnowledgeIndexRef) -> dict: ...


__all__ = ["KnowledgeIndexRepository"]
