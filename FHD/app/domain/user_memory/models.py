"""Legacy value constructors backed by the complete shared memory record."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from app.domain.user_memory.records import ActionPattern as ActionPattern
from app.domain.user_memory.records import ContextSummary as ContextSummary
from app.domain.user_memory.records import FeedbackRecord as FeedbackRecord
from app.domain.user_memory.records import UserMemory as MemoryRecord


@dataclass
class UserMemory(MemoryRecord):
    """Keep the six-argument constructor while round-tripping governed records."""

    memory_v2_records: list[dict[str, Any]] = field(default_factory=list, init=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserMemory:
        allowed = {item.name for item in fields(cls) if item.init}
        memory = cls(**{key: value for key, value in data.items() if key in allowed})
        memory.memory_v2_records = data.get("memory_v2_records", [])
        return memory
