"""检索时打分：对 recall_facts 做可解释线性排序并拼装模型上下文。"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from app.application.user_memory.write import MemoryFactsStore, default_memory_store

HALF_LIFE_DAYS = 30.0
OVERLAP_WEIGHT = 0.5
IMPORTANCE_WEIGHT = 0.3
RECENCY_WEIGHT = 0.2

_ALNUM_RUN = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
CONTEXT_HEADER = "【相关记忆】"


def _tokens(text: str) -> set[str]:
    """朴素切分：英文/数字按词，中文按二元组（bigram），不依赖第三方分词库。"""
    lowered = str(text or "").lower()
    tokens = set(_ALNUM_RUN.findall(lowered))
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.add(run)
            continue
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _clamp_importance(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, number))


def _recency(record: dict[str, Any], reference: datetime) -> float:
    updated = _parse_time(record.get("updated_at"))
    if updated is None:
        return 0.0
    # 记录与参考时间统一按本地时间计算，忽略时区标记，避免 naive/aware 混算报错。
    age_seconds = (reference.replace(tzinfo=None) - updated.replace(tzinfo=None)).total_seconds()
    age_days = max(0.0, age_seconds / 86400.0)
    return math.exp(-math.log(2) * age_days / HALF_LIFE_DAYS)


def _is_expired(record: dict[str, Any], reference: datetime) -> bool:
    expires_at = _parse_time(record.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at.replace(tzinfo=None) <= reference.replace(tzinfo=None)


def score_memory(query: str, record: dict[str, Any], now: datetime | str | None = None) -> float:
    """线性可解释打分。

    公式：``score = 0.5 * overlap + 0.3 * importance + 0.2 * recency``

    - overlap = |query 分词 ∩ 记忆分词| / |query 分词|，query 无有效分词时取 0；
    - importance 为记忆重要度，截断到 [0, 1]；
    - recency = ``exp(-ln2 * 距今天数 / 30)``，即半衰期 30 天的时间衰减。
    """
    query_tokens = _tokens(query)
    memory_tokens = _tokens(str(record.get("text") or record.get("normalized") or ""))
    overlap = len(query_tokens & memory_tokens) / len(query_tokens) if query_tokens else 0.0
    importance = _clamp_importance(record.get("importance"))
    reference = _parse_time(now) or datetime.now()
    return (
        OVERLAP_WEIGHT * overlap
        + IMPORTANCE_WEIGHT * importance
        + RECENCY_WEIGHT * _recency(record, reference)
    )


def search(
    query: str,
    *,
    scope: str,
    owner_id: str,
    limit: int = 5,
    min_score: float = 0.05,
    now: datetime | str | None = None,
    store: MemoryFactsStore | None = None,
) -> list[dict[str, Any]]:
    """按打分降序召回记忆，过滤过期、低分与其它 scope 的记录。"""
    owner = str(owner_id or "").strip()
    if not owner:
        return []
    scope_name = str(scope or "chat").strip() or "chat"
    facts_store = store or default_memory_store()
    memory = facts_store.get_memory(owner)
    records = list(getattr(memory, "recall_facts", []) or []) if memory is not None else []
    reference = _parse_time(now) or datetime.now()
    hits: list[dict[str, Any]] = []
    for record in records:
        if record.get("scope") != scope_name or _is_expired(record, reference):
            continue
        score = score_memory(query, record, reference)
        if score < float(min_score):
            continue
        hits.append(
            {
                "id": str(record.get("id") or ""),
                "text": str(record.get("text") or ""),
                "score": round(score, 4),
                "importance": round(_clamp_importance(record.get("importance")), 4),
                "updated_at": str(record.get("updated_at") or ""),
            }
        )
    hits.sort(key=lambda item: (-item["score"], item["text"]))
    return hits[: max(0, int(limit))]


def build_memory_context(
    query: str,
    *,
    scope: str,
    owner_id: str,
    limit: int = 5,
    max_chars: int = 800,
    now: datetime | str | None = None,
    store: MemoryFactsStore | None = None,
) -> str:
    """把命中记忆拼成给模型的上下文片段；无命中返回空串，超长按 max_chars 截断。"""
    hits = search(query, scope=scope, owner_id=owner_id, limit=limit, now=now, store=store)
    if not hits or max_chars <= 0:
        return ""
    lines = [CONTEXT_HEADER]
    lines.extend(f"{index}. {hit['text']}" for index, hit in enumerate(hits, start=1))
    return "\n".join(lines)[:max_chars]
