from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from typing import Any

from app.application.dataset_rag_app_service import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
)
from app.application.persy_memory_graph import PersyMemoryGraphMixin
from app.application.persy_memory_utils import (
    PERSY_MEMORY_ACTIVE as PERSY_MEMORY_ACTIVE,
)
from app.application.persy_memory_utils import (
    PERSY_MEMORY_PENDING as PERSY_MEMORY_PENDING,
)
from app.application.persy_memory_utils import (
    _coerce_access_context as _coerce_access_context,
)
from app.application.persy_memory_utils import (
    _lexical_score as _lexical_score,
)
from app.application.persy_memory_utils import (
    _memory_owner_id,
    _personal_preference,
    _personal_subject,
)
from app.application.persy_memory_utils import (
    _memory_owners as _memory_owners,
)
from app.application.persy_memory_utils import (
    _permission_denied as _permission_denied,
)
from app.application.persy_memory_utils import (
    _public_memory_record as _public_memory_record,
)
from app.application.persy_memory_utils import (
    _scope_denied as _scope_denied,
)
from app.application.persy_memory_utils import (
    _search_tokens as _search_tokens,
)
from app.application.persy_memory_utils import (
    _utc_now_iso as _utc_now_iso,
)
from app.application.persy_memory_utils import (
    extract_explicit_memories as extract_explicit_memories,
)
from app.application.persy_memory_utils import (
    merge_memory_graph as merge_memory_graph,
)
from app.application.user_memory.relation_retrieval import (
    parse_as_of,
    record_key,
    relation_paths,
    select_effective_records,
    snapshot_at,
)
from app.domain.shared_services.user_memory_service import (
    UserMemoryService,
    get_user_memory_service,
)
from app.domain.user_memory.policy import is_recallable_memory
from app.security.secrets_redactor import redact_text
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SENSITIVE_PATTERN = re.compile(
    r"(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
    re.I,
)


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

    def capture_erp_field(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        entity_type: str,
        entity_id: str,
        field: str,
    ) -> dict[str, Any]:
        """Propose a private, reviewed MemoryV2 claim from one authorized ERP field.

        Cross-actor sharing is intentionally excluded until list/graph read paths
        can enforce each recipient's original ERP source permission as well.
        """
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return _scope_denied()
        denied = _permission_denied(access, DATASET_WRITE_PERMISSION)
        if denied is not None:
            return denied
        from app.application.enterprise_cognition.memory_reference import build_erp_field_claim
        from app.application.enterprise_cognition.projection import get_projection_service

        try:
            snapshot = get_projection_service().get(
                entity_type,
                entity_id,
                tenant_id=access.tenant_id,
                actor_id=access.actor_id,
                mod_id=access.mod_id,
                force_refresh=True,
                verify_only=True,
            )
        except (PermissionError, ValueError, TypeError):
            return {
                "success": False,
                "error_code": "persy_erp_fact_source_denied",
                "candidate": None,
            }
        claim = build_erp_field_claim(snapshot, field)
        if claim is None:
            return {
                "success": False,
                "error_code": "persy_erp_fact_source_unavailable",
                "candidate": None,
            }
        owner_id = _memory_owner_id(access, "user")
        proposed = self.memory_service.propose_memory_candidate(
            owner_id,
            "entity",
            f"erp.{entity_type}.{entity_id}.{field}",
            claim["value"],
            source="erp_authority",
            confidence=1.0,
            evidence=[claim["evidence"]],
        )
        candidate = proposed.get("candidate")
        return {
            "success": proposed.get("success") is True,
            "created": proposed.get("created") is True,
            "candidate": (
                _public_memory_record(candidate, "user")
                if isinstance(candidate, dict)
                else None
            ),
            "confirmation_required": True,
            "business_data_written": False,
        }

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
        normalized_scope = str(scope or "user").strip().lower()
        if normalized_scope not in {"user", "tenant", "global_preference"}:
            return {
                "success": False,
                "created_count": 0,
                "error_code": "persy_memory_invalid_scope",
            }
        owner_id = _memory_owner_id(access, normalized_scope)
        return self._capture_for_owner(
            owner_id=owner_id,
            access=access,
            normalized_scope=normalized_scope,
            user_message=user_message,
            assistant_message=assistant_message,
            session_id=session_id,
            source=source,
        )

    def capture_personal_turn(
        self,
        *,
        user_id: str,
        context: dict[str, Any],
        user_message: str,
        assistant_message: str = "",
        source: str = "chat",
    ) -> dict[str, Any]:
        """Capture private memory for a live actor without granting dataset access."""
        from app.application.ai_chat.conversation_history import authorized_memory_context

        authorized = authorized_memory_context(user_id, context, write=True)
        if authorized is None:
            return {**_scope_denied(), "created_count": 0}
        owner_id, _ = authorized
        access = DatasetAccessContext(
            actor_id=str(context.get("local_user_id") or context.get("actor_id") or ""),
            tenant_id=str(context.get("tenant_id") or ""),
            mod_id=str(context.get("mod_id") or context.get("active_mod_id") or ""),
        )
        scope = (
            "global_preference"
            if context.get("persy_memory_scope") == "global_preference"
            else "user"
        )
        if scope == "global_preference":
            owner_id = _memory_owner_id(access, scope)
        return self._capture_for_owner(
            owner_id=owner_id,
            access=access,
            normalized_scope=scope,
            user_message=user_message,
            assistant_message=assistant_message,
            session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
            source=source,
        )

    def _capture_for_owner(
        self,
        *,
        owner_id: str,
        access: DatasetAccessContext,
        normalized_scope: str,
        user_message: str,
        assistant_message: str,
        session_id: str,
        source: str,
    ) -> dict[str, Any]:
        message = str(user_message or "").strip()
        if not message or _SENSITIVE_PATTERN.search(message) or redact_text(message) != message:
            return {"success": True, "created_count": 0, "candidates": []}
        candidates = None
        from app.infrastructure.memory.mem0_backend import get_long_term_memory

        try:
            backend = get_long_term_memory()
            extractor = getattr(backend, "extract_candidates", None)
            if callable(extractor):
                candidates = extractor(
                    user_id=owner_id,
                    user_message=message,
                    assistant_message=assistant_message,
                    metadata={
                        "session_id": session_id,
                        "source": source,
                        "scope": normalized_scope,
                    },
                )
        except RECOVERABLE_ERRORS:
            # Model unavailability permits only the bounded offline candidate parser.
            candidates = None
        assertion_context_verified = candidates is not None
        if candidates is None:
            candidates = extract_explicit_memories(message)
        if normalized_scope == "global_preference":
            candidates = [candidate for candidate in candidates if _personal_preference(candidate)]
        if not candidates:
            return {"success": True, "created_count": 0, "candidates": []}

        captured: list[dict[str, Any]] = []
        failures: list[str] = []
        created_count = 0
        now = _utc_now_iso()
        for candidate in candidates[:8]:
            evidence = {
                "kind": "conversation_turn",
                "source": str(source or "chat")[:80],
                "session_id": str(session_id or "")[:160],
                "user_excerpt": message[:500],
                "assistant_excerpt": redact_text(str(assistant_message or "").strip())[:500],
                "captured_at": now,
                "scope": normalized_scope,
                "tenant_id": access.tenant_id,
                "mod_id": access.mod_id,
            }
            result = self.memory_service.propose_memory_candidate(
                owner_id,
                candidate["memory_type"],
                candidate["key"],
                candidate["value"],
                source="chat_trace",
                confidence=float(candidate["confidence"]),
                evidence=[evidence],
                activate_personal_capture=(
                    assertion_context_verified
                    and normalized_scope == "user"
                    and _personal_subject(candidate)
                ),
            )
            record = result.get("candidate") if isinstance(result, dict) else None
            if not result.get("success"):
                failures.append(str(result.get("error_code") or "memory_candidate_write_failed"))
            if isinstance(record, dict):
                captured.append(_public_memory_record(record, normalized_scope))
            if result.get("created") is True:
                created_count += 1
        return {
            "success": not failures,
            "created_count": created_count,
            "candidate_count": len(captured),
            "candidates": captured,
            "errors": failures,
        }

    def list_memories(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        status: str = "",
        memory_type: str = "",
        limit: int = 200,
        revalidate_erp: bool = True,
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
                        "message": "memory status or type filter is invalid",
                        "error_code": "persy_memory_invalid_filter",
                    }
                rows.extend(
                    _public_memory_record(record, scope_name)
                    for record in records
                    if scope_name != "global_preference" or _personal_preference(record)
                )

        rows.sort(
            key=lambda item: (
                item.get("status") != PERSY_MEMORY_ACTIVE,
                -float(item.get("strength") or 0.0),
                str(item.get("updated_at") or ""),
            )
        )
        bounded = max(1, min(int(limit or 200), 1000))
        visible = rows[:bounded]
        if revalidate_erp and visible:
            from app.application.enterprise_cognition.memory_reference import (
                sanitize_erp_memory_view,
            )

            visible = [sanitize_erp_memory_view(row, access) for row in visible]
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

    def clear_memories(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Delete every memory visible in the knowledge base for this owner/tenant."""
        access = _coerce_access_context(access_context)
        if access is None or not access.actor_id or not access.tenant_id:
            return {**_scope_denied(), "deleted_memories": 0}
        denied = _permission_denied(access, DATASET_WRITE_PERMISSION)
        if denied is not None:
            return {**denied, "deleted_memories": 0}
        # 列举待删记忆需要读权限，删除本身仍由 mutate 校验写权限。
        list_access = (
            access
            if DATASET_READ_PERMISSION in access.permissions
            else DatasetAccessContext(
                actor_id=access.actor_id,
                tenant_id=access.tenant_id,
                permissions=frozenset(set(access.permissions) | {DATASET_READ_PERMISSION}),
                is_admin=access.is_admin,
                mod_id=access.mod_id,
            )
        )
        rows: list[dict[str, Any]] = []
        for status in (PERSY_MEMORY_PENDING, PERSY_MEMORY_ACTIVE):
            listed = self.list_memories(access_context=list_access, status=status, limit=1000)
            if not listed.get("success"):
                return {**listed, "deleted_memories": 0}
            listed_memories = listed.get("memories")
            rows.extend(
                row
                for row in (listed_memories if isinstance(listed_memories, list) else [])
                if isinstance(row, dict) and row.get("status") == status
            )
        deleted = 0
        for row in rows:
            memory_id = str(row.get("memory_id") or "").strip()
            if not memory_id:
                continue
            result = self.mutate(
                access_context=access,
                memory_id=memory_id,
                action="delete",
                reason="clear knowledge base",
            )
            if not result.get("success"):
                return result
            deleted += 1
        return {
            "success": True,
            "dataset_id": "persy-knowledge",
            "deleted_memories": deleted,
        }

    def query(
        self,
        *,
        access_context: DatasetAccessContext | dict[str, Any] | None,
        query: str,
        top_k: int = 5,
        reinforce: bool = True,
        max_hops: int = 2,
        as_of: str | None = None,
        effective_at: str | None = None,
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
        instant = None
        if as_of is not None:
            try:
                instant = parse_as_of(as_of)
                if instant > datetime.now(UTC):
                    raise ValueError("future as_of")
            except ValueError:
                return {
                    "success": False,
                    "error_code": "persy_memory_invalid_as_of",
                    "message": "as_of requires a non-future ISO timestamp with UTC offset",
                    "memories": [],
                    "chunks": [],
                }
        business_time = None
        if effective_at is not None:
            try:
                business_time = parse_as_of(effective_at)
            except ValueError:
                return {
                    "success": False,
                    "error_code": "persy_memory_invalid_effective_at",
                    "message": "effective_at requires an ISO timestamp with UTC offset",
                    "memories": [],
                    "chunks": [],
                }
        review_only = instant is not None or business_time is not None
        # Pending, revoked and blocked records never supply recall facts.
        listed = self.list_memories(
            access_context=access, status="active", limit=1000, revalidate_erp=False
        )
        if not listed.get("success"):
            return {**listed, "memories": [], "chunks": []}
        listed_memories = listed.get("memories")
        rows = [
            row
            for row in (listed_memories if isinstance(listed_memories, list) else [])
            if is_recallable_memory(row)
        ]
        original_revisions = {record_key(row): row.get("revision") for row in rows}
        unavailable = 0
        if instant is not None:
            historical = []
            for row in rows:
                snapshot, unknown = snapshot_at(row, instant)
                unavailable += int(unknown)
                if snapshot is None:
                    continue
                scope = str(row.get("scope") or "")
                if scope == "global_preference" and not _personal_preference(snapshot):
                    continue
                public = _public_memory_record(snapshot, scope)
                public.update(
                    recorded_from=snapshot["recorded_from"],
                    recorded_until=snapshot["recorded_until"],
                    strength=0.0,
                )
                for field in ("history", "last_recalled_at", "recall_count"):
                    public.pop(field, None)
                historical.append(public)
            rows = historical
        conflicts: list[dict[str, Any]] = []
        if instant is None or business_time is not None:
            rows, conflicts, invalid_count = select_effective_records(
                rows, at=business_time, require_explicit=business_time is not None
            )
            unavailable += invalid_count
        paths, traversal_truncated = relation_paths(query_text, rows, max_hops=max_hops)
        scored: list[tuple[float, dict[str, Any]]] = []
        query_tokens = _search_tokens(query_text)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            statement = str(row.get("statement") or row.get("value") or "")
            lexical = _lexical_score(query_text, query_tokens, statement)
            path = paths.get(record_key(row))
            if lexical <= 0 and not path:
                continue
            lexical_rank = 0.0
            if lexical > 0:
                lexical_rank = (
                    lexical
                    if review_only
                    else lexical * 0.72 + float(row.get("strength") or 0.0) * 0.28
                )
            relation_rank = 0.68 / len(path) ** 0.5 if path else 0.0
            score = min(1.0, max(lexical_rank, relation_rank))
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: max(1, min(int(top_k or 5), 20))]

        dropped = 0
        if selected:
            # A second authority read fences changes while building paths. Each returned
            # result still identifies its source revision, never a new business authorization.
            fresh = self.list_memories(
                access_context=access, status="active", limit=1000, revalidate_erp=False
            )
            if not fresh.get("success"):
                return {**fresh, "memories": [], "chunks": []}
            fresh_rows = [row for row in fresh.get("memories", []) if is_recallable_memory(row)]
            if not review_only:
                fresh_rows, _, _ = select_effective_records(fresh_rows)
            latest = {record_key(row): row.get("revision") for row in fresh_rows}

            def unchanged(row: dict[str, Any]) -> bool:
                keys = [record_key(row)]
                keys.extend(
                    (str(step["scope"]), str(step["memory_id"]))
                    for step in paths.get(record_key(row), [])
                )
                return all(
                    key in latest and latest[key] == original_revisions.get(key) for key in keys
                )

            checked = [(score, row) for score, row in selected if unchanged(row)]
            dropped = len(selected) - len(checked)
            selected = checked
        erp_revalidation_dropped = 0
        if not review_only and selected:
            from app.application.enterprise_cognition.memory_reference import revalidate_erp_memory

            verified = []
            for score, row in selected:
                safe_row, bound_to_erp = revalidate_erp_memory(row, access)
                if bound_to_erp and safe_row is None:
                    erp_revalidation_dropped += 1
                    continue
                if safe_row is not None:
                    verified.append((score, safe_row))
            selected = verified
        if not review_only and reinforce and selected:
            with self._lock:
                for _score, row in selected:
                    owner_id = _memory_owner_id(access, str(row.get("scope") or "user"))
                    self.memory_service.record_memory_recall(
                        owner_id,
                        str(row.get("memory_id") or ""),
                    )

        memories: list[dict[str, Any]] = []
        chunks: list[dict[str, Any]] = []
        for score, row in selected:
            public = dict(row)
            public["score"] = score
            if paths.get(record_key(row)):
                public["relation_path"] = paths[record_key(row)]
            if review_only:
                # Historical or business-time views are for explicit review, not tool authority.
                public["eligible_for_planner"] = False
                public["historical"] = True
            memories.append(public)
            if review_only:
                continue
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
                        "eligible_for_planner": public.get("eligible_for_planner"),
                        "source_policy": public.get("source_policy"),
                        "source_memory_id": public.get("memory_id"),
                        "source_revision": public.get("revision"),
                        "source_owner_id": _memory_owner_id(
                            access, str(public.get("scope") or "user")
                        ),
                        "source": "对话记忆",
                        "updated_at": public.get("updated_at"),
                        "relation_path": public.get("relation_path", []),
                        "erp_fact_verification": public.get("erp_fact_verification"),
                    },
                }
            )
        return {
            "success": True,
            "query": query_text,
            "memories": memories,
            "chunks": chunks,
            "retriever": "persy_memory_relation_v2"
            if max_hops > 0
            else "persy_memory_lexical_strength_v1",
            "as_of": instant.isoformat() if instant is not None else None,
            "historical_review_only": review_only,
            "effective_at": business_time.isoformat() if business_time is not None else None,
            "temporal_unavailable_count": unavailable,
            "relation_conflicts": conflicts[:50],
            "relation_conflict_count": len(conflicts),
            "revalidation_dropped": dropped,
            "erp_revalidation_dropped": erp_revalidation_dropped,
            "coverage_complete": (
                not traversal_truncated
                and unavailable == 0
                and dropped == 0
                and erp_revalidation_dropped == 0
                and int((listed.get("summary") or {}).get("total") or 0)
                <= len(listed_memories or [])
            ),
            "relation_traversal_truncated": traversal_truncated,
        }


_persy_memory_service: PersyMemoryApplicationService | None = None


def get_persy_memory_app_service() -> PersyMemoryApplicationService:
    global _persy_memory_service
    if _persy_memory_service is None:
        _persy_memory_service = PersyMemoryApplicationService()
    return _persy_memory_service


def reset_persy_memory_app_service_for_tests() -> None:
    global _persy_memory_service
    _persy_memory_service = None
