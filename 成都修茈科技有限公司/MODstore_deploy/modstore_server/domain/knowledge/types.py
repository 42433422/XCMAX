from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeIndexRef:
    collection_id: int
    user_id: int
