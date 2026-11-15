"""记忆单元：事实抽取、有效期判断与召回重排。

成熟长期记忆的共性是「记忆是带时间与来源的结构化单元」，而不是整段对话。
本模块只做纯函数，方便离线单测；mem0 适配留在 ``mem0_backend``。

事实元数据约定：

- ``memory_type``：``fact`` / ``utterance``
- ``fact_key``：稳定键，如 ``finance.budget``，用于去重与冲突判定
- ``fact_value``：归一化后的值，用于判断是否 NOOP
- ``valid_from`` / ``valid_to``：有效区间，空字符串表示未失效
- ``superseded_by``：替代它的新记忆 id
- ``confidence``：规则抽取置信度
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_FACTS_PER_TURN = 5

_FACT_LABELS = {
    "company.name": "公司名称",
    "finance.budget": "预算",
    "logistics.default_warehouse": "默认仓库",
    "sales.contact": "联系人",
    "purchase.lead_time": "交期/账期",
    "preference": "偏好",
    "explicit.note": "明确要求记住",
}

_FACT_RULES: tuple[tuple[str, re.Pattern[str], float], ...] = (
    (
        "company.name",
        re.compile(
            r"(?:我们公司|本公司|公司名称|单位名称)(?:叫|是|为|改为|改成)\s*([^\s，。；,;！？?]{1,40})"
        ),
        0.85,
    ),
    (
        "finance.budget",
        re.compile(
            r"(?:预算|采购预算|年度预算)(?:调整|改|变)?(?:为|成|是)\s*"
            r"([0-9]+(?:\.[0-9]+)?\s*(?:万元|元|万|块)?)"
        ),
        0.85,
    ),
    (
        "logistics.default_warehouse",
        re.compile(
            r"(?:默认仓库|发货仓库|常用仓库)(?:是|为|改为|改成)\s*([^\s，。；,;！？?]{1,30})"
        ),
        0.8,
    ),
    (
        "sales.contact",
        re.compile(r"(?:联系人|对接人|负责人)(?:是|为|改为|改成)\s*([^\s，。；,;！？?]{1,20})"),
        0.8,
    ),
    (
        "purchase.lead_time",
        re.compile(r"(?:交期|交付周期|账期)(?:是|为|改为|改成)\s*([^\s，。；,;！？?]{1,20})"),
        0.75,
    ),
    (
        "preference",
        re.compile(
            r"(?:以后|今后|后续|默认)(?:都|请|统一)?(?:用|使用|走|按)\s*([^\s，。；,;！？?]{1,30})"
        ),
        0.7,
    ),
)

_EXPLICIT_MEMORY = re.compile(r"(?:^|[。；;\n])记(?:住|一下)[:：]?\s*(.{4,120})")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def utc_now() -> datetime:
    return datetime.now(UTC)


def today_iso(now: datetime | None = None) -> str:
    return (now or utc_now()).date().isoformat()


def iso_at(now: datetime | None = None) -> str:
    return (now or utc_now()).isoformat(timespec="seconds")


def expiration_iso(days: int, *, now: datetime | None = None) -> str:
    base = (now or utc_now()).date()
    return (base + timedelta(days=max(1, int(days)))).isoformat()


def normalize_value(value: Any) -> str:
    """归一化值用于 NOOP 判定：去空白、去标点、数字统一。"""
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s，。；、,;:：\"'“”‘’]", "", text)
    return text


def _explicit_key(text: str) -> str:
    digest = hashlib.sha1(normalize_value(text).encode("utf-8")).hexdigest()[:12]
    return f"explicit.{digest}"


def extract_facts(message: str, *, limit: int = MAX_FACTS_PER_TURN) -> list[dict[str, Any]]:
    """从用户原话抽取稳定事实；只认明确陈述，不做猜测。"""
    text = str(message or "").strip()
    if not text:
        return []
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, pattern, confidence in _FACT_RULES:
        match = pattern.search(text)
        if not match:
            continue
        value = re.sub(r"\s+", "", match.group(1)).strip()
        if not value or key in seen:
            continue
        seen.add(key)
        label = _FACT_LABELS.get(key, key)
        facts.append(
            {
                "key": key,
                "value": value,
                "text": f"{label}：{value}",
                "confidence": confidence,
            }
        )
        if len(facts) >= limit:
            return facts
    explicit = _EXPLICIT_MEMORY.search(text)
    if explicit:
        note = explicit.group(1).strip()
        if note:
            facts.append(
                {
                    "key": _explicit_key(note),
                    "value": note,
                    "text": f"{_FACT_LABELS['explicit.note']}：{note}",
                    "confidence": 0.9,
                }
            )
    return facts[:limit]


def is_active(metadata: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """有效记忆：未被替代、未过 valid_to、未过 expiration_date、已生效。"""
    meta = metadata if isinstance(metadata, dict) else {}
    if str(meta.get("superseded_by") or "").strip():
        return False
    today = today_iso(now)
    valid_to = str(meta.get("valid_to") or "").strip()
    if valid_to and valid_to[:10] <= today:
        return False
    expiration = str(meta.get("expiration_date") or "").strip()
    if expiration and expiration[:10] < today:
        return False
    valid_from = str(meta.get("valid_from") or "").strip()
    if valid_from and valid_from[:10] > today:
        return False
    return True


def _tokens(text: str) -> set[str]:
    raw = str(text or "")
    tokens = {word.lower() for word in _WORD.findall(raw)}
    cjk = _CJK.findall(raw)
    tokens.update(a + b for a, b in zip(cjk, cjk[1:]))
    return tokens


def lexical_overlap(query: str, content: str) -> float:
    """轻量词法重合度，替代需要下载模型的 BM25 稀疏检索。"""
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(content)
    if not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _recency_weight(
    metadata: dict[str, Any], *, memory_type: str, now: datetime | None = None
) -> float:
    """事实长期稳定；原始轮次随时间缓慢降权，避免旧闲聊挤占预算。"""
    if memory_type == "fact":
        return 1.0
    raw = str(metadata.get("valid_from") or metadata.get("created_at") or "").strip()
    if not raw:
        return 1.0
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 1.0
    base = now or utc_now()
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = max(0.0, (base - created).total_seconds() / 86400)
    return max(0.6, 1.0 - age_days / 365 * 0.4)


def rank_hits(
    hits: list[dict[str, Any]],
    *,
    query: str,
    limit: int = 3,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """过滤失效记忆后，按向量 + 词法 + 类型 + 时效重排。"""
    ranked: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get("metadata")
        meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}
        if not is_active(meta, now=now):
            continue
        content = str(hit.get("content") or "")
        vector = float(hit.get("score") or 0.0)
        lexical = lexical_overlap(query, content)
        memory_type = str(meta.get("memory_type") or "utterance")
        type_boost = 0.05 if memory_type == "fact" else 0.0
        recency = _recency_weight(meta, memory_type=memory_type, now=now)
        score = (vector + 0.35 * lexical + type_boost) * recency
        ranked.append(
            {
                **hit,
                "score": round(min(1.0, score), 6),
                "retrieval": {
                    "vector": round(vector, 6),
                    "lexical": round(lexical, 6),
                    "recency": round(recency, 6),
                },
            }
        )
    ranked.sort(key=lambda item: (-item["score"], str(item.get("chunk_id") or "")))
    return ranked[: max(1, int(limit))]


__all__ = [
    "MAX_FACTS_PER_TURN",
    "expiration_iso",
    "extract_facts",
    "is_active",
    "iso_at",
    "lexical_overlap",
    "normalize_value",
    "rank_hits",
    "today_iso",
    "utc_now",
]
