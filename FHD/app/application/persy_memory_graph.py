"""Governed Persy memory graph projection and mutation mixin."""

from __future__ import annotations

import threading
from collections import Counter
from typing import TYPE_CHECKING, Any, cast

from app.application.dataset_rag_app_service import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
)
from app.application.persy_memory_utils import (
    _VISIBLE_MEMORY_STATUSES,
    PERSY_MEMORY_ACTIVE,
    PERSY_MEMORY_PENDING,
    _coerce_access_context,
    _entity_node_id,
    _entity_role_label,
    _entity_type_label,
    _memory_owners,
    _memory_type_label,
    _permission_denied,
    _public_memory_record,
    _scope_denied,
    _truncate,
)
from app.services.user_memory_service import UserMemoryService


class PersyMemoryGraphMixin:
    _lock: threading.RLock

    if TYPE_CHECKING:
        @property
        def memory_service(self) -> UserMemoryService: ...
        def list_memories(
            self,
            *,
            access_context: DatasetAccessContext | dict[str, Any] | None,
            status: str = "",
            memory_type: str = "",
            limit: int = 200,
        ) -> dict[str, Any]: ...

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
            if not isinstance(value, dict):
                value = {}
            raw_entities = value.get("entities")
            entities = list(raw_entities) if isinstance(raw_entities, list) else []
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
        return cast("dict[str, Any]", result)

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
