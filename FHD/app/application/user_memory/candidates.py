"""Transactional candidate proposal, confirmation, correction and lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.application.user_memory.preferences import sync_preference_projection
from app.application.user_memory.projections import project_after_commit
from app.application.user_memory.protocols import (
    CandidateGovernance,
    JsonObject,
    MemoryAccess,
    MemoryStatusUpdate,
    memory_transaction,
)
from app.application.user_memory.relation_retrieval import (
    relation_write_conflicts,
    validate_relation_value,
)
from app.domain.user_memory.policy import is_scoped_memory_owner
from app.domain.user_memory.records import UserMemory


def _advance_revision(record: JsonObject, updated: JsonObject, *, action: str, at: str) -> None:
    previous = {key: deepcopy(value) for key, value in record.items() if key != "history"}
    updated["revision"] = int(record.get("revision") or 1) + 1
    updated["recorded_at_utc"] = datetime.now(UTC).isoformat()
    updated["history"] = [
        *record.get("history", []),
        {"action": action, "at": at, "previous": previous},
    ]


def _conflict_response(conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": "memory_relation_review_required",
        "message": "单值关系有效期重叠，请审核原记忆或明确不重叠的有效期",
        "conflicts": conflicts,
    }


@dataclass(frozen=True)
class CandidatePorts:
    normalize_type: Callable[[str], str]
    normalize_status: Callable[[str], str]
    fingerprint: Callable[[str, str, Any], str]
    govern: CandidateGovernance
    find_record: Callable[[UserMemory, str], tuple[int, JsonObject | None]]
    set_status: MemoryStatusUpdate
    max_records: Callable[[], int]
    new_id: Callable[[], str]


class CandidateMemory:
    def __init__(self, access: MemoryAccess, ports: CandidatePorts) -> None:
        self.access = access
        self.ports = ports

    @project_after_commit
    @memory_transaction
    def propose(
        self,
        user_id: str,
        memory_type: str,
        key: str,
        value: Any,
        *,
        source: str = "agent_observation",
        confidence: float = 0.5,
        evidence: list[dict[str, Any]] | None = None,
        activate_personal_capture: bool = False,
        auto_review_capture: bool = False,
    ) -> dict[str, Any]:
        """Persist a candidate or activate an authorized personal capture in one commit."""
        normalized_type = self.ports.normalize_type(memory_type)
        normalized_key = str(key or "").strip()
        if not user_id:
            return {"success": False, "message": "缺少 user_id"}
        if not normalized_key:
            return {"success": False, "message": "缺少 memory key"}
        invalid = validate_relation_value(value)
        if invalid is not None:
            return invalid
        governance = self.ports.govern(source=source, confidence=confidence, evidence=evidence)
        personal_capture = (
            user_id.startswith("personal-memory:v1:")
            and governance["source"] == "chat_trace"
            and governance["source_policy"] == "observed_pending"
            and bool(governance["evidence"])
        )
        expected_scope = (
            "user"
            if user_id.startswith("personal-memory:v1:")
            else "tenant"
            if user_id.startswith("enterprise-memory:v1:")
            else ""
        )
        reviewed_capture = (
            auto_review_capture
            and bool(expected_scope)
            and governance["source"] == "chat_trace"
            and governance["source_policy"] == "observed_pending"
            and any(
                item.get("kind") == "conversation_turn"
                and item.get("scope") == expected_scope
                and item.get("user_excerpt")
                and item.get("tenant_id")
                for item in governance["evidence"]
            )
        )
        if reviewed_capture:
            from app.application.persy_memory_utils import review_explicit_capture

            # Recheck the actual canonical value at the authority boundary;
            # the caller's review flag alone is not sufficient to activate it.
            proposed = {
                "memory_type": normalized_type,
                "key": normalized_key,
                "value": value,
            }
            reviewed_capture = any(
                review_explicit_capture(
                    proposed, str(item.get("user_excerpt") or ""), expected_scope
                )
                == {**proposed, "confidence": governance["confidence"]}
                for item in governance["evidence"]
                if item.get("kind") == "conversation_turn"
                and item.get("scope") == expected_scope
                and item.get("tenant_id")
            )
        activate = (activate_personal_capture and personal_capture) or reviewed_capture
        memory = self.access.get_memory(user_id) or self.access.new_memory(user_id)
        fingerprint = self.ports.fingerprint(normalized_type, normalized_key, value)
        for record in memory.memory_v2_records:
            if record.get("fingerprint") == fingerprint and record.get("status") in {
                "pending",
                "active",
                "rejected",
            }:
                return {"success": True, "created": False, "candidate": dict(record)}
            # Scoped owner revocations and superseded revisions survive repeated capture.
            if is_scoped_memory_owner(user_id) and (
                (record.get("fingerprint") == fingerprint and record.get("status") == "deleted")
                or any(
                    (revision.get("previous") or {}).get("fingerprint") == fingerprint
                    for revision in record.get("history") or []
                    if revision.get("action") in {"correct", "confirm"}
                    and record.get("fingerprint") != fingerprint
                )
            ):
                return {"success": True, "created": False}
        now = self.access.now()
        if (
            sum(row.get("status") in {"pending", "active"} for row in memory.memory_v2_records)
            >= self.ports.max_records()
        ):
            return {
                "success": False,
                "message": "记忆容量已满，请先审核或撤销候选",
                "error_code": "memory_capacity_reached",
            }
        candidate = {
            **governance,
            "memory_id": f"mem_{self.ports.new_id()}",
            "memory_type": normalized_type,
            "key": normalized_key,
            "value": value,
            "status": "rejected" if governance["source_policy"] == "blocked" else "pending",
            "fingerprint": fingerprint,
            "created_at": now,
            "updated_at": now,
            "revision": 1,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "history": [],
        }
        if candidate["status"] == "rejected":
            candidate["rejected_at"] = now
            candidate["rejected_reason"] = "source_policy_blocked"
        if candidate["status"] == "pending":
            conflicts = relation_write_conflicts(memory.memory_v2_records, candidate)
            if conflicts:
                candidate["conflict_review"] = conflicts
                activate = False
        # A different active value for the same key is a review task, not a
        # silent overwrite or an additional contradictory planner fact.
        if reviewed_capture and any(
            row.get("status") == "active"
            and row.get("key") == normalized_key
            and row.get("fingerprint") != fingerprint
            for row in memory.memory_v2_records
        ):
            candidate["governance_flags"].append("auto_review_conflicting_key")
            activate = False
        if activate:
            candidate.update(
                status="active",
                source_policy=(
                    "personal_auto_saved" if expected_scope == "user" else "capture_auto_reviewed"
                ),
                auto_review_policy="direct_assertion_v1" if reviewed_capture else "legacy_personal",
                auto_confirm_allowed=True,
                requires_user_confirmation=False,
                eligible_for_planner=True,
                auto_saved_at=now,
            )
            sync_preference_projection(memory, {}, candidate, now)
        memory.memory_v2_records.insert(0, candidate)
        self.access.save_memory(user_id, memory)
        result = {"success": True, "created": True, "candidate": dict(candidate)}
        if activate:
            result["memory"] = candidate
        return result

    @project_after_commit
    @memory_transaction
    def confirm(
        self, user_id: str, memory_id: str, *, correction: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """确认候选记忆，确认后才进入 active 状态并可被 planner 使用。"""
        memory = self.access.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self.ports.find_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}
        if record.get("status") == "deleted":
            return {"success": False, "message": "记忆已删除"}
        if record.get("status") == "rejected":
            return {"success": False, "message": "记忆已拒绝，不能确认"}
        if record.get("source_policy") == "blocked":
            return {"success": False, "message": "记忆来源被策略阻断"}
        if (
            record.get("status") == "active"
            and record.get("eligible_for_planner") is True
            and not correction
        ):
            return {"success": True, "memory": dict(record)}
        updated = dict(record)
        patch = dict(correction or {})
        if patch:
            if "memory_type" in patch:
                updated["memory_type"] = self.ports.normalize_type(str(patch["memory_type"]))
            if "key" in patch:
                updated["key"] = str(patch["key"] or "").strip()
            if "value" in patch:
                updated["value"] = patch["value"]
            if "confidence" in patch:
                updated["confidence"] = max(0.0, min(1.0, float(patch["confidence"])))
            updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
        if not str(updated.get("key") or "").strip():
            return {"success": False, "message": "缺少 memory key"}
        invalid = validate_relation_value(updated.get("value"))
        if invalid is not None:
            return invalid
        conflicts = relation_write_conflicts(memory.memory_v2_records, updated)
        if conflicts:
            return _conflict_response(conflicts)
        updated.pop("conflict_review", None)
        now = self.access.now()
        updated["status"] = "active"
        updated["confirmed_at"] = now
        updated["updated_at"] = now
        updated["eligible_for_planner"] = True
        updated["fingerprint"] = self.ports.fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
        _advance_revision(record, updated, action="confirm", at=now)
        memory.memory_v2_records[idx] = updated
        sync_preference_projection(memory, record, updated, now)
        self.access.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    @project_after_commit
    @memory_transaction
    def auto_review_pending(
        self,
        user_id: str,
        memory_id: str,
        *,
        expected_revision: int,
        proof: JsonObject,
    ) -> dict[str, Any]:
        """Review one unchanged candidate against an independently read chat receipt."""
        from app.application.dataset_rag_app_service import DatasetAccessContext
        from app.application.persy_memory_utils import (
            AUTO_REVIEW_SCOPES,
            _memory_owner_id,
            review_explicit_capture,
        )

        def pending(reason: str) -> dict[str, Any]:
            return {"success": True, "review_status": "pending", "reason": reason}

        scope = str(proof.get("scope") or "")
        if scope not in AUTO_REVIEW_SCOPES:
            return pending("invalid_scope")
        access = DatasetAccessContext(
            actor_id=str(proof.get("actor_id") or ""),
            tenant_id=str(proof.get("tenant_id") or ""),
            mod_id=str(proof.get("mod_id") or ""),
        )
        if not access.actor_id or not access.tenant_id or _memory_owner_id(access, scope) != user_id:
            return pending("scope_mismatch")
        if not proof.get("message_id") or not proof.get("conversation_key"):
            return pending("source_receipt_missing")
        memory = self.access.get_memory(user_id)
        if memory is None:
            return pending("not_found")
        idx, record = self.ports.find_record(memory, memory_id)
        if record is None or record.get("status") != "pending":
            return pending("not_pending")
        if (
            int(record.get("revision") or 1) != expected_revision
            or record.get("history")
            or record.get("correction_count")
        ):
            return pending("revision_changed")
        if record.get("source") != "chat_trace" or record.get("source_policy") != "observed_pending":
            return pending("unsupported_source")
        if not any(
            isinstance(item, dict)
            and item.get("kind") == "conversation_turn"
            and all(
                str(item.get(key) or "") == str(proof.get(key) or "")
                for key in ("scope", "tenant_id", "mod_id", "session_id", "user_excerpt")
            )
            for item in record.get("evidence") or []
        ):
            return pending("source_evidence_changed")
        reviewed = review_explicit_capture(record, str(proof["user_excerpt"]), scope)
        if reviewed is None:
            return pending("review_policy_not_met")
        fingerprint = self.ports.fingerprint(
            reviewed["memory_type"], reviewed["key"], reviewed["value"]
        )
        for other in memory.memory_v2_records:
            if other.get("memory_id") == memory_id:
                continue
            # Canonicalization must not revive rejected or deleted values,
            # including historical revisions of a different memory ID.
            if other.get("fingerprint") == fingerprint and other.get("status") in {
                "active", "deleted", "rejected"
            }:
                return pending("duplicate_or_revoked")
            if any(
                (entry.get("previous") or {}).get("fingerprint") == fingerprint
                for entry in other.get("history") or []
                if entry.get("action") in {"correct", "confirm"}
            ):
                return pending("superseded")
            if other.get("status") == "active" and other.get("key") == reviewed["key"]:
                return pending("conflicting_active_key")
        updated = {**record, **reviewed, "fingerprint": fingerprint}
        invalid = validate_relation_value(updated["value"])
        if invalid is not None:
            return pending("invalid_relation")
        if relation_write_conflicts(memory.memory_v2_records, updated):
            return pending("conflicting_relation")
        now = self.access.now()
        updated.pop("conflict_review", None)
        updated.update(
            status="active",
            source_policy="personal_auto_saved" if scope == "user" else "capture_auto_reviewed",
            auto_review_policy="historical_direct_assertion_v1",
            auto_confirm_allowed=True,
            requires_user_confirmation=False,
            eligible_for_planner=True,
            auto_saved_at=now,
            confirmed_at=now,
            updated_at=now,
            auto_review_receipt={
                "message_id": str(proof["message_id"]),
                "conversation_key": str(proof["conversation_key"]),
                "session_id": str(proof["session_id"]),
                "actor_id": access.actor_id,
                "tenant_id": access.tenant_id,
                "mod_id": access.mod_id,
                "reviewed_at": now,
            },
        )
        _advance_revision(record, updated, action="confirm", at=now)
        memory.memory_v2_records[idx] = updated
        sync_preference_projection(memory, record, updated, now)
        self.access.save_memory(user_id, memory)
        return {"success": True, "review_status": "active", "memory": dict(updated)}

    def reject(self, user_id: str, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.ports.set_status(user_id, memory_id, "rejected", reason=reason)

    def delete(self, user_id: str, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.ports.set_status(user_id, memory_id, "deleted", reason=reason)

    @project_after_commit
    @memory_transaction
    def set_status(
        self, user_id: str, memory_id: str, status: str, *, reason: str = ""
    ) -> dict[str, Any]:
        normalized_status = self.ports.normalize_status(status)
        memory = self.access.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self.ports.find_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}
        if record.get("status") == normalized_status:
            return {"success": True, "memory": dict(record)}
        if record.get("status") == "deleted":
            return {"success": False, "message": "记忆已删除"}
        updated = dict(record)
        now = self.access.now()
        updated["status"] = normalized_status
        updated["eligible_for_planner"] = False
        updated["updated_at"] = now
        if reason:
            updated[f"{normalized_status}_reason"] = reason
        if normalized_status == "deleted":
            updated["deleted_at"] = now
        if normalized_status == "rejected":
            updated["rejected_at"] = now
        _advance_revision(record, updated, action=normalized_status, at=now)
        memory.memory_v2_records[idx] = updated
        if normalized_status in {"deleted", "rejected"}:
            sync_preference_projection(memory, record, updated, now)
        self.access.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    @project_after_commit
    @memory_transaction
    def correct(
        self,
        user_id: str,
        memory_id: str,
        *,
        value: Any | None = None,
        key: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """纠正 active/pending 记忆，保留同一个 memory_id 便于审计。"""
        memory = self.access.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self.ports.find_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}
        if record.get("status") == "deleted":
            return {"success": False, "message": "记忆已删除"}
        if record.get("status") not in {"active", "pending"}:
            return {"success": False, "message": "只能纠正有效记忆或待审核候选"}
        updated = dict(record)
        if key is not None:
            updated["key"] = str(key or "").strip()
        if value is not None:
            updated["value"] = value
        if not str(updated.get("key") or "").strip():
            return {"success": False, "message": "缺少 memory key"}
        invalid = validate_relation_value(updated.get("value"))
        if invalid is not None:
            return invalid
        conflicts = relation_write_conflicts(memory.memory_v2_records, updated)
        if updated["status"] == "active" and conflicts:
            return _conflict_response(conflicts)
        if conflicts:
            updated["conflict_review"] = conflicts
        else:
            updated.pop("conflict_review", None)
        now = self.access.now()
        updated["updated_at"] = now
        updated["last_correction_reason"] = reason
        updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
        updated["fingerprint"] = self.ports.fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
        _advance_revision(record, updated, action="correct", at=now)
        memory.memory_v2_records[idx] = updated
        if updated.get("status") == "active":
            sync_preference_projection(memory, record, updated, now)
        self.access.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    @memory_transaction
    def record_recall(self, user_id: str, memory_id: str) -> dict[str, Any]:
        """Reinforce a confirmed memory after it contributed to retrieval."""
        memory = self.access.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self.ports.find_record(memory, memory_id)
        if record is None or record.get("status") != "active":
            return {"success": False, "message": "可召回记忆不存在"}
        updated = dict(record)
        now = self.access.now()
        updated["recall_count"] = int(updated.get("recall_count") or 0) + 1
        updated["last_recalled_at"] = now
        memory.memory_v2_records[idx] = updated
        self.access.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}
