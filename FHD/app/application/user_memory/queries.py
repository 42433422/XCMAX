"""Read-only filtering, summaries and planner context of governed memory."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.application.user_memory.ports import (
    MemoryAccess,
    MemoryListing,
)
from app.domain.user_memory.analysis import memory_summary


@dataclass(frozen=True)
class QueryPorts:
    normalize_type: Callable[[str], str]
    normalize_status: Callable[[str], str]
    list_memories: MemoryListing


class MemoryQueries:
    def __init__(self, access: MemoryAccess, ports: QueryPorts) -> None:
        self.access = access
        self.ports = ports

    def list_memories(
        self, user_id: str, *, status: str | None = None, memory_type: str | None = None
    ) -> list[dict[str, Any]]:
        memory = self.access.get_memory(user_id)
        if memory is None:
            return []
        normalized_status = self.ports.normalize_status(status) if status else None
        normalized_type = self.ports.normalize_type(memory_type) if memory_type else None
        records = []
        for record in memory.memory_v2_records:
            if normalized_status and record.get("status") != normalized_status:
                continue
            if normalized_type and record.get("memory_type") != normalized_type:
                continue
            records.append(dict(record))
        return records

    def get_memory_v2_summary(self, user_id: str) -> dict[str, Any]:
        memory = self.access.get_memory(user_id)
        if memory is None:
            return {"total": 0, "by_status": {}, "by_type": {}}
        by_status: dict[str, int] = defaultdict(int)
        by_type: dict[str, int] = defaultdict(int)
        by_source_policy: dict[str, int] = defaultdict(int)
        for record in memory.memory_v2_records:
            by_status[str(record.get("status") or "unknown")] += 1
            by_type[str(record.get("memory_type") or "unknown")] += 1
            by_source_policy[str(record.get("source_policy") or "unknown")] += 1
        return {
            "total": len(memory.memory_v2_records),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "by_source_policy": dict(by_source_policy),
        }

    def format_memory_v2_for_prompt(
        self, user_id: str, *, max_items: int = 6, memory_type: str | None = None
    ) -> str:
        """Format confirmed Memory v2 records as compact planner context."""
        active = [
            record
            for record in self.ports.list_memories(
                user_id, status="active", memory_type=memory_type
            )
            if record.get("source_policy") != "blocked"
            and record.get("eligible_for_planner", True) is not False
        ]
        if not active:
            return "【MemoryV2】无已确认记忆。"
        type_order = {"preference": 0, "entity": 1, "episodic": 2}
        active.sort(
            key=lambda item: (
                type_order.get(str(item.get("memory_type") or ""), 99),
                str(item.get("updated_at") or ""),
            ),
            reverse=False,
        )
        lines = ["【MemoryV2】已确认记忆（仅供 planner 补全偏好/实体/任务上下文，不得编造）:"]
        for idx, record in enumerate(active[: max(1, int(max_items))], start=1):
            memory_kind = str(record.get("memory_type") or "unknown")
            key = str(record.get("key") or "-")
            value = json.dumps(record.get("value"), ensure_ascii=False, default=str)
            confidence = float(record.get("confidence") or 0.0)
            source = str(record.get("source") or "-")
            updated_at = str(record.get("updated_at") or "-")
            lines.append(
                f"{idx}. type={memory_kind}; key={key}; value={value}; confidence={confidence:.2f}; source={source}; updated_at={updated_at}"
            )
        return "\n".join(lines)

    def get_memory_summary(self, user_id: str) -> dict[str, Any]:
        """获取用户记忆摘要"""
        memory = self.access.get_memory(user_id)
        if not memory:
            return {"has_memory": False}
        return {
            **memory_summary(memory),
            "memory_v2_count": len(memory.memory_v2_records),
            "memory_v2_pending_count": len(
                [m for m in memory.memory_v2_records if m.get("status") == "pending"]
            ),
            "memory_v2_active_count": len(
                [m for m in memory.memory_v2_records if m.get("status") == "active"]
            ),
        }
