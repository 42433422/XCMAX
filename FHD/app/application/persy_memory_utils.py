"""Extraction, access control, ranking, graph labels, and serialization helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.application.dataset_rag_app_service import (
    DATASET_ADMIN_PERMISSION,
    DatasetAccessContext,
)

PERSY_MEMORY_PENDING = "pending"
PERSY_MEMORY_ACTIVE = "active"
_VISIBLE_MEMORY_STATUSES = {PERSY_MEMORY_PENDING, PERSY_MEMORY_ACTIVE}
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


def extract_explicit_memories(message: str) -> list[dict[str, Any]]:
    """Extract only explicit, bounded facts; every result still requires confirmation."""

    results: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for raw_sentence in _SENTENCE_SPLIT.split(str(message or "")):
        sentence = re.sub(r"\s+", " ", raw_sentence).strip(" ，,。！？!?；;")
        if len(sentence) < 3 or len(sentence) > 500:
            continue

        candidates: list[tuple[str, str, str, str, float]] = []
        for pattern, predicate, memory_type, confidence in (
            (
                r"(?:^|[,，])(?:我叫|我的名字是|我名叫)\s*([^,，]{1,32})(?=$|[,，])",
                "姓名",
                "entity",
                0.96,
            ),
            (
                r"(?:^|[,，])(?:我来自|我住在|我的所在地是)\s*([^,，]{1,48})(?=$|[,，])",
                "所在地",
                "entity",
                0.93,
            ),
            (
                r"(?:^|[,，])(?:我喜欢|我偏好|我更喜欢|我的偏好是)\s*([^,，]{1,120})(?=$|[,，])",
                "偏好",
                "preference",
                0.94,
            ),
            (
                r"(?:^|[,，])(?:我习惯|我通常会)\s*([^,，]{1,120})(?=$|[,，])",
                "习惯",
                "preference",
                0.9,
            ),
            (
                r"(?:^|[,，])(?:我希望|请记住我希望)\s*([^,，]{1,120})(?=$|[,，])",
                "期望",
                "preference",
                0.88,
            ),
        ):
            match = re.search(pattern, sentence)
            if match:
                candidates.append(("用户", predicate, match.group(1), memory_type, confidence))

        enterprise = re.search(
            r"^(?:客户|公司|联系人)?\s*([^,，]{2,40}?)\s*(?:的)?"
            r"(负责人|联系人|所在地|地址|行业|偏好|沟通时间|邮箱|电话)"
            r"\s*(?:是|为|：|:)\s*(.{1,120})$",
            sentence,
        )
        if enterprise:
            subject, predicate, object_text = enterprise.groups()
            memory_type = "preference" if predicate in {"偏好", "沟通时间"} else "entity"
            candidates.append((subject, predicate, object_text, memory_type, 0.91))

        relation = None
        if enterprise is None:
            relation = re.search(
                r"^([^,，]{2,40}?)\s*(负责(?!人)|属于|位于|使用|采用)\s*(.{1,120})$",
                sentence,
            )
        if relation:
            subject, predicate, object_text = relation.groups()
            candidates.append((subject, predicate, object_text, "entity", 0.86))

        for subject, predicate, object_text, memory_type, confidence in candidates:
            subject = _clean_memory_part(subject, 48)
            object_text = _clean_memory_part(object_text, 160)
            if not subject or not object_text or subject == object_text:
                continue
            statement = (
                f"{subject}{predicate}{object_text}"
                if predicate in {"负责", "属于", "位于", "使用", "采用"}
                else f"{subject}的{predicate}是{object_text}"
            )
            fingerprint = _normalized_fingerprint(statement)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            results.append(
                {
                    "memory_type": memory_type,
                    "key": f"{subject}.{predicate}",
                    "confidence": confidence,
                    "value": {
                        "subject": subject,
                        "predicate": predicate,
                        "object": object_text,
                        "statement": statement,
                        "entities": [
                            {
                                "name": subject,
                                "type": _infer_entity_type(subject, predicate, role="subject"),
                                "role": "subject",
                            },
                            {
                                "name": object_text,
                                "type": _infer_entity_type(object_text, predicate, role="object"),
                                "role": "object",
                            },
                        ],
                    },
                }
            )
    return results


def merge_memory_graph(
    base_graph: dict[str, Any],
    memory_graph: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    merged = dict(base_graph)
    nodes = [dict(node) for node in base_graph.get("nodes", []) if isinstance(node, dict)]
    edges = [dict(edge) for edge in base_graph.get("edges", []) if isinstance(edge, dict)]
    node_ids = {str(node.get("id") or "") for node in nodes}
    bounded = max(20, min(int(limit or 120), 240))
    for node in memory_graph.get("nodes", []):
        if not isinstance(node, dict) or len(nodes) >= bounded:
            break
        node_id = str(node.get("id") or "")
        if node_id and node_id not in node_ids:
            nodes.append(dict(node))
            node_ids.add(node_id)
    edge_ids = {str(edge.get("id") or "") for edge in edges}
    for edge in memory_graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if (
            str(edge.get("source") or "") not in node_ids
            or str(edge.get("target") or "") not in node_ids
        ):
            continue
        edge_id = str(edge.get("id") or "")
        if edge_id and edge_id in edge_ids:
            continue
        edges.append(dict(edge))
        if edge_id:
            edge_ids.add(edge_id)
    categories = Counter(str(node.get("type") or "unknown") for node in nodes)
    stats = dict(base_graph.get("stats") or {})
    memory_stats = dict(memory_graph.get("stats") or {})
    stats.update(memory_stats)
    stats.update(
        {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "categories": dict(sorted(categories.items())),
        }
    )
    merged.update({"nodes": nodes, "edges": edges, "stats": stats})
    return merged


def _public_memory_record(record: dict[str, Any], scope: str) -> dict[str, Any]:
    value = record.get("value")
    structured = value if isinstance(value, dict) else {}
    statement = str(structured.get("statement") or "").strip()
    if not statement:
        key = str(record.get("key") or "记忆")
        rendered = (
            json.dumps(value, ensure_ascii=False, default=str)
            if not isinstance(value, str)
            else value
        )
        statement = f"{key}：{rendered}"
    public = {
        key: record.get(key)
        for key in (
            "memory_id",
            "memory_type",
            "key",
            "value",
            "status",
            "confidence",
            "source",
            "source_policy",
            "source_trust",
            "requires_user_confirmation",
            "eligible_for_planner",
            "evidence",
            "created_at",
            "updated_at",
            "confirmed_at",
            "last_recalled_at",
            "recall_count",
            "correction_count",
        )
    }
    public["scope"] = scope
    public["statement"] = statement
    public["strength"] = _memory_strength(record)
    return public


def _memory_strength(record: dict[str, Any]) -> float:
    confidence = max(0.0, min(1.0, float(record.get("confidence") or 0.5)))
    updated = _parse_datetime(record.get("updated_at") or record.get("created_at"))
    age_days = max(0.0, (datetime.now(UTC) - updated).total_seconds() / 86400)
    memory_type = str(record.get("memory_type") or "episodic")
    half_life = {"preference": 365.0, "entity": 240.0, "episodic": 90.0}.get(
        memory_type,
        120.0,
    )
    retention = math.exp(-math.log(2) * age_days / half_life)
    recall_count = max(0, int(record.get("recall_count") or 0))
    reinforcement = min(0.22, math.log1p(recall_count) * 0.07)
    status_factor = 1.0 if record.get("status") == PERSY_MEMORY_ACTIVE else 0.68
    return round(
        max(0.05, min(1.0, (confidence * 0.72 + retention * 0.28 + reinforcement) * status_factor)),
        4,
    )


def _coerce_access_context(
    value: DatasetAccessContext | dict[str, Any] | None,
) -> DatasetAccessContext | None:
    if value is None:
        return None
    if isinstance(value, DatasetAccessContext):
        return value
    if not isinstance(value, dict):
        return None
    raw_permissions = value.get("permissions") or []
    if isinstance(raw_permissions, str):
        permissions = frozenset(part.strip() for part in raw_permissions.split(",") if part.strip())
    else:
        permissions = frozenset(str(part).strip() for part in raw_permissions if str(part).strip())
    return DatasetAccessContext(
        actor_id=str(value.get("actor_id") or value.get("user_id") or "").strip(),
        tenant_id=str(value.get("tenant_id") or "").strip(),
        permissions=permissions,
        is_admin=bool(value.get("is_admin")),
    )


def _memory_owners(access: DatasetAccessContext) -> list[tuple[str, str]]:
    owners = [("user", access.actor_id), ("tenant", _tenant_owner_id(access.tenant_id))]
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for scope, owner in owners:
        if owner and owner not in seen:
            seen.add(owner)
            unique.append((scope, owner))
    return unique


def _tenant_owner_id(tenant_id: str) -> str:
    return f"tenant:{str(tenant_id or '').strip()}" if str(tenant_id or "").strip() else ""


def _scope_denied() -> dict[str, Any]:
    return {
        "success": False,
        "message": "trusted Persy memory scope is required",
        "error_code": "persy_memory_scope_missing",
    }


def _permission_denied(
    access: DatasetAccessContext,
    permission: str,
) -> dict[str, Any] | None:
    if (
        access.is_admin
        or DATASET_ADMIN_PERMISSION in access.permissions
        or permission in access.permissions
        or "dataset.*" in access.permissions
        or "*" in access.permissions
    ):
        return None
    return {
        "success": False,
        "message": f"{permission} permission is required",
        "error_code": "dataset_permission_denied",
        "required_permission": permission,
    }


def _clean_memory_part(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ，,。！？!?；;：:")
    return text[:limit].strip()


def _normalized_fingerprint(value: str) -> str:
    normalized = re.sub(r"[\s，,。！？!?；;：:]", "", value).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _infer_entity_type(name: str, predicate: str, *, role: str) -> str:
    if name == "用户":
        return "person"
    if predicate in {"所在地", "地址", "位于"} and role == "object":
        return "place"
    if predicate in {"负责人", "联系人", "姓名"} and role == "object":
        return "person"
    if any(token in name for token in ("公司", "科技", "集团", "客户")):
        return "organization"
    if predicate in {"偏好", "习惯", "期望", "沟通时间"} and role == "object":
        return "preference"
    return "concept"


def _search_tokens(value: str) -> set[str]:
    text = str(value or "").casefold()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_.-]{1,30}", text))
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.update(cjk)
    tokens.update("".join(cjk[index : index + 2]) for index in range(len(cjk) - 1))
    return {token for token in tokens if token}


def _lexical_score(query: str, query_tokens: set[str], statement: str) -> float:
    normalized_query = re.sub(r"\s+", "", query).casefold()
    normalized_statement = re.sub(r"\s+", "", statement).casefold()
    if normalized_query and normalized_query in normalized_statement:
        return 1.0
    statement_tokens = _search_tokens(statement)
    if not query_tokens or not statement_tokens:
        return 0.0
    overlap = len(query_tokens & statement_tokens)
    if overlap == 0:
        return 0.0
    return min(
        1.0, overlap / max(1, len(query_tokens)) * 0.78 + overlap / len(statement_tokens) * 0.22
    )


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _entity_node_id(entity_type: str, name: str) -> str:
    digest = hashlib.sha1(f"{entity_type}:{name.casefold()}".encode()).hexdigest()[:14]
    return f"entity:{digest}"


def _entity_type_label(entity_type: str) -> str:
    return {
        "person": "人物",
        "place": "地点",
        "organization": "组织",
        "preference": "偏好",
        "concept": "概念",
    }.get(entity_type, "实体")


def _entity_role_label(role: str) -> str:
    return {"subject": "主体", "object": "关联", "related": "相关"}.get(role, "相关")


def _memory_type_label(memory_type: str) -> str:
    return {
        "preference": "偏好",
        "entity": "人物与事实",
        "episodic": "经历",
    }.get(memory_type, "记忆")


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
