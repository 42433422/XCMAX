"""写入时抽取去重：把回合事实收敛进现有用户记忆快照。

存储复用 ``UserMemoryStore`` 的 JSON 快照（``user_memory/memory_store.json``），
记录落在 ``UserMemory.recall_facts``，键为 ``scope + owner_id + 归一化文本``，
不新增独立数据库。
"""

from __future__ import annotations

import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.application.user_memory.models import UserMemory

MAX_MEMORY_CHARS = 500
MAX_RECALL_FACTS = 500

# 结尾语气词：命中则循环剥离，让「我喜欢蓝色呢」与「我喜欢蓝色」归一为同一条记忆。
_END_PARTICLES = frozenset("呢吧啊哦嘛呀哈啦喔噢呐咯")

# 全角标点/空格转半角，保证相似文本归一结果一致。
_FULLWIDTH_TABLE = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "；": ";",
        "：": ":",
        "、": ",",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "「": '"',
        "」": '"',
        "『": "'",
        "』": "'",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "～": "~",
        "　": " ",
    }
)
_TRAILING_PUNCT = " ,;:.!?~"


class MemoryFactsStore(Protocol):
    """与 MemoryRepository 兼容的最小读写接口，便于测试注入内存库。"""

    def get_memory(self, user_id: str) -> Any | None: ...

    def save_memory(self, user_id: str, memory: Any) -> None: ...


def default_memory_store() -> MemoryFactsStore:
    """返回进程内共享的用户记忆存储（JSON 快照单例）。"""
    from app.domain.shared_services.user_memory_service import UserMemoryStore

    return UserMemoryStore()


def normalize_memory_text(text: str) -> str:
    """归一化记忆文本：全角标点转半角、合并连续空白、去掉结尾语气词。"""
    normalized = str(text or "").translate(_FULLWIDTH_TABLE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    while normalized:
        stripped = normalized.rstrip(_TRAILING_PUNCT)
        if stripped != normalized:
            normalized = stripped
            continue
        if stripped[-1:] in _END_PARTICLES and len(stripped) > 1:
            normalized = stripped[:-1].rstrip(_TRAILING_PUNCT)
            continue
        normalized = stripped
        break
    return normalized


def _truncate(text: str) -> tuple[str, bool]:
    """单条记忆上限 500 字；超长截断并返回 truncated 标记。"""
    if len(text) <= MAX_MEMORY_CHARS:
        return text, False
    return text[:MAX_MEMORY_CHARS], True


def _clamp_importance(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, number))


def _expires_at(now: datetime, ttl_days: int | float) -> str | None:
    try:
        days = float(ttl_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return (now + timedelta(days=days)).isoformat()


def remember(
    text: str,
    *,
    scope: str,
    owner_id: str,
    source: str = "chat",
    importance: float = 0.5,
    ttl_days: int | float | None = None,
    store: MemoryFactsStore | None = None,
) -> dict[str, Any]:
    """写入一条回合事实，相同 scope+owner_id+归一化文本合并为同一条记录。

    已存在时 ``hits += 1``、``importance = min(1.0, importance + 0.05)``、
    刷新 ``updated_at``，不新增重复行。
    """
    owner = str(owner_id or "").strip()
    normalized, truncated = _truncate(normalize_memory_text(text))
    if not owner or not normalized:
        return {
            "id": "",
            "created": False,
            "merged": False,
            "truncated": truncated,
            "reason": "missing_owner_id" if not owner else "empty_text",
        }
    scope_name = str(scope or "chat").strip() or "chat"
    now = datetime.now()
    now_iso = now.isoformat()
    facts_store = store or default_memory_store()
    # 读改写必须在同一事务内完成：仅靠原子替换只能避免半截文件，
    # 多 worker 并发仍会互相覆盖，跨进程锁需要覆盖整段读改写。
    transaction = getattr(facts_store, "transaction", None)
    with transaction() if callable(transaction) else nullcontext():
        memory = facts_store.get_memory(owner) or UserMemory(user_id=owner)
        facts = list(getattr(memory, "recall_facts", []) or [])
        for record in facts:
            if record.get("scope") == scope_name and record.get("normalized") == normalized:
                record["hits"] = int(record.get("hits") or 0) + 1
                record["importance"] = min(1.0, _clamp_importance(record.get("importance")) + 0.05)
                record["updated_at"] = now_iso
                record["source"] = str(source or record.get("source") or "chat")
                if ttl_days is not None:
                    record["expires_at"] = _expires_at(now, ttl_days)
                memory.recall_facts = facts
                facts_store.save_memory(owner, memory)
                return {
                    "id": str(record.get("id") or ""),
                    "created": False,
                    "merged": True,
                    "truncated": truncated,
                }
        record = {
            "id": f"rm_{uuid.uuid4().hex[:12]}",
            "scope": scope_name,
            "owner_id": owner,
            "text": normalized,
            "normalized": normalized,
            "source": str(source or "chat"),
            "importance": _clamp_importance(importance),
            "hits": 1,
            "created_at": now_iso,
            "updated_at": now_iso,
            "truncated": truncated,
            "expires_at": _expires_at(now, ttl_days) if ttl_days is not None else None,
        }
        facts.insert(0, record)
        memory.recall_facts = facts[:MAX_RECALL_FACTS]
        facts_store.save_memory(owner, memory)
    return {"id": record["id"], "created": True, "merged": False, "truncated": truncated}
