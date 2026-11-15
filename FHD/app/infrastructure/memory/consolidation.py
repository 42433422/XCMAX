"""事实合并：借鉴 mem0 的 ADD / UPDATE / DELETE / NOOP 写入决策。

热路径只写原始轮次；本模块在后台把抽取到的事实与已有事实比对，决定：

- ``ADD``：没有同键活跃事实
- ``NOOP``：同键且值相同
- ``SUPERSEDE``：同键但值不同，旧事实置 ``valid_to`` 与 ``superseded_by``

存储通过 Protocol 注入，便于离线单测，也避免把 mem0 的 API 细节扩散到业务层。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.infrastructure.memory.memory_units import is_active, normalize_value, today_iso
from app.infrastructure.observability.metrics import observe_memory_consolidation
from app.utils.operational_errors import RECOVERABLE_ERRORS


class FactStore(Protocol):
    """合并所需的最小存储能力。"""

    def search_facts(
        self, user_id: str, fact: dict[str, Any], limit: int = 5
    ) -> list[dict[str, Any]]: ...

    def add_fact(
        self, user_id: str, fact: dict[str, Any], *, supersedes: str = ""
    ) -> str | None: ...

    def supersede_fact(
        self, user_id: str, memory_id: str, *, content: str, new_id: str, today: str
    ) -> bool: ...


def decide(
    fact: dict[str, Any], existing: list[dict[str, Any]]
) -> tuple[str, dict[str, Any] | None]:
    """返回 ``(action, target)``；action 为 ADD / NOOP / SUPERSEDE。"""
    key = str(fact.get("key") or "").strip()
    value = normalize_value(fact.get("value") or fact.get("text"))
    for item in existing:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}
        if str(meta.get("fact_key") or "").strip() != key:
            continue
        if not is_active(meta):
            continue
        old_value = normalize_value(meta.get("fact_value") or "")
        if old_value and old_value == value:
            return "NOOP", item
        return "SUPERSEDE", item
    return "ADD", None


def consolidate(
    store: FactStore,
    *,
    user_id: str,
    facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """逐个事实执行写入决策，返回每个事实的动作记录。"""
    results: list[dict[str, Any]] = []
    today = today_iso()
    for fact in facts:
        if not isinstance(fact, dict) or not str(fact.get("key") or "").strip():
            continue
        try:
            existing = store.search_facts(user_id, fact, limit=5)
        except RECOVERABLE_ERRORS:
            results.append({"key": fact.get("key"), "action": "SKIPPED", "reason": "search_failed"})
            continue
        action, target = decide(fact, existing)
        record: dict[str, Any] = {"key": str(fact.get("key")), "action": action}
        if action == "NOOP":
            results.append(record)
            continue
        old_id = str((target or {}).get("chunk_id") or "")
        supersedes = old_id if action == "SUPERSEDE" else ""
        try:
            new_id = store.add_fact(user_id, fact, supersedes=supersedes)
        except RECOVERABLE_ERRORS:
            results.append({**record, "action": "SKIPPED", "reason": "add_failed"})
            continue
        record["memory_id"] = new_id or ""
        if action == "SUPERSEDE" and old_id:
            old_content = str((target or {}).get("content") or "")
            try:
                store.supersede_fact(
                    user_id,
                    old_id,
                    content=old_content,
                    new_id=str(new_id or ""),
                    today=today,
                )
            except RECOVERABLE_ERRORS:
                record["supersede_failed"] = True
        results.append(record)
    for record in results:
        observe_memory_consolidation(str(record.get("action") or "SKIPPED"))
    return results


__all__ = ["FactStore", "consolidate", "decide"]
