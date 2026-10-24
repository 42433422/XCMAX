"""Transactional candidate proposal, confirmation, correction and lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any

from app.application.user_memory.models import UserMemory
from app.application.user_memory.ports import (
    CandidateGovernance,
    CandidateProposal,
    JsonObject,
    MemoryAccess,
    MemoryStatusUpdate,
    memory_transaction,
)
from app.application.user_memory.preferences import sync_preference_projection


@dataclass(frozen=True)
class CandidatePorts:
    normalize_type: Callable[[str], str]
    normalize_status: Callable[[str], str]
    fingerprint: Callable[[str, str, Any], str]
    govern: CandidateGovernance
    find_record: Callable[[UserMemory, str], tuple[int, JsonObject | None]]
    propose_unlocked: CandidateProposal
    set_status: MemoryStatusUpdate
    proposal_lock: Callable[[], RLock]
    max_records: Callable[[], int]
    new_id: Callable[[], str]


class CandidateMemory:
    def __init__(self, access: MemoryAccess, ports: CandidatePorts) -> None:
        self.access = access
        self.ports = ports

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
    ) -> dict[str, Any]:
        """Atomically deduplicate and persist a governed memory candidate."""
        with self.ports.proposal_lock():
            return self.ports.propose_unlocked(
                user_id,
                memory_type,
                key,
                value,
                source=source,
                confidence=confidence,
                evidence=evidence,
            )

    def propose_unlocked(
        self,
        user_id: str,
        memory_type: str,
        key: str,
        value: Any,
        *,
        source: str = "agent_observation",
        confidence: float = 0.5,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """写入待确认记忆候选，不直接污染 planner 可用记忆。"""
        normalized_type = self.ports.normalize_type(memory_type)
        normalized_key = str(key or "").strip()
        if not user_id:
            return {"success": False, "message": "缺少 user_id"}
        if not normalized_key:
            return {"success": False, "message": "缺少 memory key"}
        governance = self.ports.govern(source=source, confidence=confidence, evidence=evidence)
        memory = self.access.get_memory(user_id) or self.access.new_memory(user_id)
        fingerprint = self.ports.fingerprint(normalized_type, normalized_key, value)
        for record in memory.memory_v2_records:
            if record.get("fingerprint") == fingerprint and record.get("status") in {
                "pending",
                "active",
                "rejected",
            }:
                return {"success": True, "created": False, "candidate": dict(record)}
        now = self.access.now()
        candidate = {
            "memory_id": f"mem_{self.ports.new_id()}",
            "memory_type": normalized_type,
            "key": normalized_key,
            "value": value,
            "status": "rejected" if governance["source_policy"] == "blocked" else "pending",
            "confidence": governance["confidence"],
            "source": governance["source"],
            "source_policy": governance["source_policy"],
            "source_trust": governance["source_trust"],
            "source_evidence_required": governance["source_evidence_required"],
            "requires_user_confirmation": governance["requires_user_confirmation"],
            "auto_confirm_allowed": governance["auto_confirm_allowed"],
            "eligible_for_planner": governance["eligible_for_planner"],
            "governance_flags": governance["governance_flags"],
            "evidence": governance["evidence"],
            "fingerprint": fingerprint,
            "created_at": now,
            "updated_at": now,
        }
        if candidate["status"] == "rejected":
            candidate["rejected_at"] = now
            candidate["rejected_reason"] = "source_policy_blocked"
        memory.memory_v2_records.insert(0, candidate)
        memory.memory_v2_records = memory.memory_v2_records[: self.ports.max_records()]
        self.access.save_memory(user_id, memory)
        return {"success": True, "created": True, "candidate": dict(candidate)}

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
        now = self.access.now()
        updated["status"] = "active"
        updated["confirmed_at"] = now
        updated["updated_at"] = now
        updated["eligible_for_planner"] = True
        updated["fingerprint"] = self.ports.fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
        memory.memory_v2_records[idx] = updated
        sync_preference_projection(memory, record, updated, now)
        self.access.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    def reject(self, user_id: str, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.ports.set_status(user_id, memory_id, "rejected", reason=reason)

    def delete(self, user_id: str, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.ports.set_status(user_id, memory_id, "deleted", reason=reason)

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
        updated = dict(record)
        now = self.access.now()
        updated["status"] = normalized_status
        updated["updated_at"] = now
        if reason:
            updated[f"{normalized_status}_reason"] = reason
        if normalized_status == "deleted":
            updated["deleted_at"] = now
        if normalized_status == "rejected":
            updated["rejected_at"] = now
        memory.memory_v2_records[idx] = updated
        if normalized_status in {"deleted", "rejected"}:
            sync_preference_projection(memory, record, updated, now)
        self.access.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

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
        updated = dict(record)
        if key is not None:
            updated["key"] = str(key or "").strip()
        if value is not None:
            updated["value"] = value
        if not str(updated.get("key") or "").strip():
            return {"success": False, "message": "缺少 memory key"}
        now = self.access.now()
        updated["updated_at"] = now
        updated["last_correction_reason"] = reason
        updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
        updated["fingerprint"] = self.ports.fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
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
