from __future__ import annotations

import threading
from typing import Any

from app.application.dataset_rag_app_service import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
)
from app.application.persy_memory_graph import (
    PersyMemoryGraphMixin,
)
from app.application.persy_memory_graph import (
    merge_memory_graph as merge_memory_graph,
)
from app.application.persy_memory_support import (
    _SENSITIVE_PATTERN,
    PERSY_MEMORY_ACTIVE,
    PERSY_MEMORY_PENDING,
    _coerce_access_context,
    _lexical_score,
    _memory_owners,
    _permission_denied,
    _public_memory_record,
    _scope_denied,
    _search_tokens,
    _tenant_owner_id,
    _utc_now_iso,
    extract_explicit_memories,
)
from app.services.user_memory_service import UserMemoryService, get_user_memory_service


class PersyMemoryApplicationService(PersyMemoryGraphMixin):
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
        owner_id = (
            _tenant_owner_id(access.tenant_id) if normalized_scope == "tenant" else access.actor_id
        )
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
        if requested_status and requested_status not in {
            "pending",
            "active",
            "rejected",
            "deleted",
        }:
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
                except ValueError:
                    return {
                        "success": False,
                        "message": "invalid memory filter",
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


_persy_memory_service: PersyMemoryApplicationService | None = None


def get_persy_memory_app_service() -> PersyMemoryApplicationService:
    global _persy_memory_service
    if _persy_memory_service is None:
        _persy_memory_service = PersyMemoryApplicationService()
    return _persy_memory_service


def reset_persy_memory_app_service_for_tests() -> None:
    global _persy_memory_service
    _persy_memory_service = None
