from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.application.dataset_rag_app_service import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
)
from app.services.user_memory_service import UserMemoryService, get_user_memory_service

PERSY_MEMORY_PENDING = "pending"
PERSY_MEMORY_ACTIVE = "active"
_VISIBLE_MEMORY_STATUSES = {PERSY_MEMORY_PENDING, PERSY_MEMORY_ACTIVE}
_SENSITIVE_PATTERN = re.compile(
    r"(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
    re.I,
)
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


class PersyMemoryApplicationService:
    """Structured, governed conversation memory projected into the Persy graph."""

    def __init__(self, memory_service: UserMemoryService | None = None) -> None:
        self._memory_service = memory_service
        self._lock = threading.RLock()

    @property
    def memory_service(self) -> UserMemoryService:
        if self._memory_service is None:
            self._memory_service = get_user_memory_service()
        return self._memory_service

    def capture_conversation_turn(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        user_message: str,
        assistant_message: str = "",
        session_id: str = "",
        source: str = "chat",
        scope: str = "user",
    ) -> dict[str, Any]:
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return {
                "success": False,
                "created_count": 0,
                "message": "trusted Persy memory scope is required",
                "error_code": "persy_memory_scope_missing",
            }
        denied = _permission_denied(access, DATASET_WRITE_PERMISSION)
        if denied is not None:
            return {**denied, "created_count": 0, "candidates": []}
        message = str(user_message or "").strip()
        if not message or _SENSITIVE_PATTERN.search(message):
            return {"success": True, "created_count": 0, "candidates": []}

        candidates = extract_explicit_memories(message)
        if not candidates:
            return {"success": True, "created_count": 0, "candidates": []}

        normalized_scope = "tenant" if str(scope).strip().lower() == "tenant" else "user"
        owner_id = _tenant_owner_id(access.tenant_id) if normalized_scope == "tenant" else access.actor_id
        captured: list[dict[str, Any]] = []
        created_count = 0
        now = _utc_now_iso()
        with self._lock:
            for candidate in candidates[:8]:
                evidence = {
                    "kind": "conversation_turn",
                    "source": str(source or "chat")[:80],
                    "session_id": str(session_id or "")[:160],
                    "user_excerpt": message[:500],
                    "assistant_excerpt": str(assistant_message or "").strip()[:500],
                    "captured_at": now,
                    "scope": normalized_scope,
                }
                result = self.memory_service.propose_memory_candidate(
                    owner_id,
                    candidate["memory_type"],
                    candidate["key"],
                    candidate["value"],
                    source="chat_trace",
                    confidence=float(candidate["confidence"]),
                    evidence=[evidence],
                )
                record = result.get("candidate") if isinstance(result, dict) else None
                if isinstance(record, dict):
                    captured.append(_public_memory_record(record, normalized_scope))
                if result.get("created") is True:
                    created_count += 1
        return {
            "success": True,
            "created_count": created_count,
            "candidate_count": len(captured),
            "candidates": captured,
        }

    def list_memories(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        status: str = "",
        memory_type: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return _scope_denied()
        denied = _permission_denied(access, DATASET_READ_PERMISSION)
        if denied is not None:
            return denied
        requested_status = str(status or "").strip().lower()
        if requested_status and requested_status not in {"pending", "active", "rejected", "deleted"}:
            return {
                "success": False,
                "message": f"unsupported memory status: {requested_status}",
                "error_code": "persy_memory_invalid_status",
            }
        requested_type = str(memory_type or "").strip().lower()
        rows: list[dict[str, Any]] = []
        with self._lock:
            for scope_name, owner_id in _memory_owners(access):
                try:
                    records = self.memory_service.list_memories(
                        owner_id,
                        status=requested_status or None,
                        memory_type=requested_type or None,
                    )
                except ValueError as exc:
                    return {
                        "success": False,
                        "message": str(exc),
                        "error_code": "persy_memory_invalid_filter",
                    }
                rows.extend(_public_memory_record(record, scope_name) for record in records)

        rows.sort(
            key=lambda item: (
                item.get("status") != PERSY_MEMORY_ACTIVE,
                -float(item.get("strength") or 0.0),
                str(item.get("updated_at") or ""),
            )
        )
        bounded = max(1, min(int(limit or 200), 1000))
        visible = rows[:bounded]
        return {
            "success": True,
            "memories": visible,
            "summary": {
                "total": len(rows),
                "active": sum(1 for row in rows if row.get("status") == PERSY_MEMORY_ACTIVE),
                "pending": sum(1 for row in rows if row.get("status") == PERSY_MEMORY_PENDING),
                "returned": len(visible),
            },
        }

    def query(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        query: str,
        top_k: int = 5,
        reinforce: bool = True,
    ) -> dict[str, Any]:
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return {**_scope_denied(), "memories": [], "chunks": []}
        denied = _permission_denied(access, DATASET_READ_PERMISSION)
        if denied is not None:
            return {**denied, "memories": [], "chunks": []}
        query_text = str(query or "").strip()
        if not query_text:
            return {
                "success": False,
                "message": "query is required",
                "error_code": "persy_memory_query_required",
                "memories": [],
                "chunks": [],
            }
        listed = self.list_memories(access_context=access, status=PERSY_MEMORY_ACTIVE, limit=1000)
        rows = listed.get("memories") if isinstance(listed.get("memories"), list) else []
        scored: list[tuple[float, dict[str, Any]]] = []
        query_tokens = _search_tokens(query_text)
        for row in rows:
            if not isinstance(row, dict):
                continue
            statement = str(row.get("statement") or row.get("value") or "")
            lexical = _lexical_score(query_text, query_tokens, statement)
            if lexical <= 0:
                continue
            score = min(1.0, lexical * 0.72 + float(row.get("strength") or 0.0) * 0.28)
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: max(1, min(int(top_k or 5), 20))]

        if reinforce and selected:
            with self._lock:
                for _score, row in selected:
                    owner_id = (
                        _tenant_owner_id(access.tenant_id)
                        if row.get("scope") == "tenant"
                        else access.actor_id
                    )
                    self.memory_service.record_memory_recall(
                        owner_id,
                        str(row.get("memory_id") or ""),
                    )

        memories: list[dict[str, Any]] = []
        chunks: list[dict[str, Any]] = []
        for score, row in selected:
            public = dict(row)
            public["score"] = score
            memories.append(public)
            chunks.append(
                {
                    "text": str(public.get("statement") or ""),
                    "source": "对话记忆",
                    "score": score,
                    "metadata": {
                        "memory_id": public.get("memory_id"),
                        "memory_type": public.get("memory_type"),
                        "scope": public.get("scope"),
                        "status": public.get("status"),
                        "source": "对话记忆",
                        "updated_at": public.get("updated_at"),
                    },
                }
            )
        return {
            "success": True,
            "query": query_text,
            "memories": memories,
            "chunks": chunks,
            "retriever": "persy_memory_lexical_strength_v1",
        }

    def graph(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        limit: int = 80,
    ) -> dict[str, Any]:
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return {**_scope_denied(), "nodes": [], "edges": [], "stats": {}}
        denied = _permission_denied(access, DATASET_READ_PERMISSION)
        if denied is not None:
            return {**denied, "nodes": [], "edges": [], "stats": {}}
        listed = self.list_memories(access_context=access, limit=1000)
        records = [
            row
            for row in listed.get("memories", [])
            if isinstance(row, dict) and row.get("status") in _VISIBLE_MEMORY_STATUSES
        ]
        records.sort(
            key=lambda item: (
                item.get("status") != PERSY_MEMORY_ACTIVE,
                -float(item.get("strength") or 0.0),
            )
        )
        bounded = max(1, min(int(limit or 80), 160))
        records = records[:bounded]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        entity_nodes: dict[str, dict[str, Any]] = {}
        topic_counts: Counter[str] = Counter()
        root_id = "persy:persy-knowledge"

        for row in records:
            memory_id = str(row.get("memory_id") or "")
            node_id = f"memory:{memory_id}"
            memory_type = str(row.get("memory_type") or "episodic")
            topic_counts[memory_type] += 1
            nodes.append(
                {
                    "id": node_id,
                    "label": _truncate(str(row.get("statement") or "记忆"), 38),
                    "type": "memory",
                    "summary": str(row.get("statement") or ""),
                    "size": 24 + round(float(row.get("strength") or 0.0) * 12),
                    "strength": float(row.get("strength") or 0.0),
                    "metadata": {
                        key: row.get(key)
                        for key in (
                            "memory_id",
                            "memory_type",
                            "status",
                            "scope",
                            "confidence",
                            "source",
                            "created_at",
                            "updated_at",
                            "last_recalled_at",
                            "recall_count",
                            "requires_user_confirmation",
                        )
                    },
                }
            )
            topic_id = f"memory-topic:{memory_type}"
            edges.append(
                {
                    "id": f"edge:{topic_id}:{node_id}",
                    "source": topic_id,
                    "target": node_id,
                    "type": "groups",
                    "label": "包含",
                    "weight": 0.52,
                }
            )
            value = row.get("value") if isinstance(row.get("value"), dict) else {}
            entities = value.get("entities") if isinstance(value.get("entities"), list) else []
            for entity in entities[:6]:
                if not isinstance(entity, dict):
                    continue
                name = str(entity.get("name") or "").strip()
                if not name:
                    continue
                entity_type = str(entity.get("type") or "concept")
                entity_id = _entity_node_id(entity_type, name)
                entity_nodes.setdefault(
                    entity_id,
                    {
                        "id": entity_id,
                        "label": _truncate(name, 28),
                        "type": "topic",
                        "summary": f"{_entity_type_label(entity_type)} · 关联记忆",
                        "size": 27,
                        "strength": 0.62,
                        "metadata": {
                            "topic_kind": "entity",
                            "entity_type": entity_type,
                            "entity_name": name,
                        },
                    },
                )
                role = str(entity.get("role") or "related")
                edges.append(
                    {
                        "id": f"edge:{entity_id}:{node_id}:{role}",
                        "source": entity_id,
                        "target": node_id,
                        "type": role,
                        "label": _entity_role_label(role),
                        "weight": 0.6 if role == "subject" else 0.46,
                    }
                )

        for memory_type, count in topic_counts.items():
            topic_id = f"memory-topic:{memory_type}"
            nodes.append(
                {
                    "id": topic_id,
                    "label": _memory_type_label(memory_type),
                    "type": "topic",
                    "summary": f"{count} 条相关记忆",
                    "size": 29 + min(count * 2, 12),
                    "strength": min(1.0, 0.5 + count / 20),
                    "metadata": {"topic_kind": "memory_type", "memory_type": memory_type},
                }
            )
            edges.append(
                {
                    "id": f"edge:{root_id}:{topic_id}",
                    "source": root_id,
                    "target": topic_id,
                    "type": "memory_topic",
                    "label": "记忆主题",
                    "weight": 0.66,
                }
            )

        nodes.extend(entity_nodes.values())
        return {
            "success": True,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "memory_count": len(records),
                "active_memory_count": sum(
                    1 for row in records if row.get("status") == PERSY_MEMORY_ACTIVE
                ),
                "pending_memory_count": sum(
                    1 for row in records if row.get("status") == PERSY_MEMORY_PENDING
                ),
                "entity_count": len(entity_nodes),
            },
        }

    def mutate(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        memory_id: str,
        action: str,
        patch: dict[str, Any] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return _scope_denied()
        denied = _permission_denied(access, DATASET_WRITE_PERMISSION)
        if denied is not None:
            return denied
        target_id = str(memory_id or "").strip()
        if not target_id:
            return {
                "success": False,
                "message": "memory_id is required",
                "error_code": "persy_memory_id_required",
            }
        with self._lock:
            owner = self._find_memory_owner(access, target_id)
            if owner is None:
                return {
                    "success": False,
                    "message": "memory not found",
                    "error_code": "persy_memory_not_found",
                }
            scope_name, owner_id = owner
            normalized_action = str(action or "").strip().lower()
            if normalized_action == "confirm":
                result = self.memory_service.confirm_memory_candidate(
                    owner_id,
                    target_id,
                    correction=dict(patch or {}),
                )
            elif normalized_action == "reject":
                result = self.memory_service.reject_memory_candidate(
                    owner_id,
                    target_id,
                    reason=reason,
                )
            elif normalized_action == "delete":
                result = self.memory_service.delete_memory(owner_id, target_id, reason=reason)
            elif normalized_action == "correct":
                data = dict(patch or {})
                result = self.memory_service.correct_memory(
                    owner_id,
                    target_id,
                    key=data.get("key"),
                    value=data.get("value"),
                    reason=reason,
                )
            else:
                return {
                    "success": False,
                    "message": f"unsupported memory action: {normalized_action}",
                    "error_code": "persy_memory_action_invalid",
                }
        memory = result.get("memory") if isinstance(result, dict) else None
        if isinstance(memory, dict):
            result = {**result, "memory": _public_memory_record(memory, scope_name)}
        return result

    def _find_memory_owner(
        self,
        access: DatasetAccessContext,
        memory_id: str,
    ) -> tuple[str, str] | None:
        for scope_name, owner_id in _memory_owners(access):
            records = self.memory_service.list_memories(owner_id)
            if any(str(record.get("memory_id") or "") == memory_id for record in records):
                return scope_name, owner_id
        return None


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
        if str(edge.get("source") or "") not in node_ids or str(edge.get("target") or "") not in node_ids:
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
        rendered = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
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
    return round(max(0.05, min(1.0, (confidence * 0.72 + retention * 0.28 + reinforcement) * status_factor)), 4)


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
    return min(1.0, overlap / max(1, len(query_tokens)) * 0.78 + overlap / len(statement_tokens) * 0.22)


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


_persy_memory_service: PersyMemoryApplicationService | None = None


def get_persy_memory_app_service() -> PersyMemoryApplicationService:
    global _persy_memory_service
    if _persy_memory_service is None:
        _persy_memory_service = PersyMemoryApplicationService()
    return _persy_memory_service


def reset_persy_memory_app_service_for_tests() -> None:
    global _persy_memory_service
    _persy_memory_service = None
