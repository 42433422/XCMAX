"""Compatibility adapters for proposing governed MemoryV2 candidates."""

from __future__ import annotations

import re
from typing import Any, Protocol

MAX_MEMORY_CHARS = 500

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
    """Compatibility entry: propose an audited candidate in the scoped authority.

    The old recall_facts collection is retained for audit but never updated or
    promoted into model evidence. Confirmation is performed through MemoryV2.
    """
    import hashlib

    from app.domain.shared_services.user_memory_service import get_user_memory_service

    owner = str(owner_id or "").strip()
    normalized = normalize_memory_text(text)
    truncated = len(normalized) > MAX_MEMORY_CHARS
    normalized = normalized[:MAX_MEMORY_CHARS]
    if not owner.startswith(("personal-memory:v1:", "enterprise-memory:v1:")) or not normalized:
        return {
            "id": "",
            "created": False,
            "merged": False,
            "truncated": truncated,
            "reason": "scoped_owner_required" if normalized else "empty_text",
        }
    service = get_user_memory_service()
    if store is not None and store is not service._store:
        return {"id": "", "created": False, "merged": False, "reason": "unsupported_store"}
    result = service.propose_memory_candidate(
        owner,
        "entity",
        "statement:" + hashlib.sha256(normalized.encode()).hexdigest()[:24],
        {"statement": normalized},
        source="chat_trace",
        confidence=importance,
        evidence=[{"source": source, "legacy_scope": scope, "kind": "explicit_statement"}],
    )
    record = result.get("candidate") or {}
    return {
        **result,
        "id": record.get("memory_id", ""),
        "merged": result.get("created") is False,
        "truncated": truncated,
    }
