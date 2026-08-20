# mypy: disable-error-code="no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.user_memory_service")


class __UserMemoryServicePart01MixinPart01Mixin:
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_type: str = "json"):
        if bool(getattr(self, "_initialized", False)):
            return
        self._store = _facade().UserMemoryStore(storage_type=storage_type)
        self._memory_v2_lock = _facade().threading.RLock()
        self._initialized = True
        _facade().logger.info("用户记忆服务已初始化")

    def add_preference(self, user_id: str, key: str, value: _facade().Any) -> None:
        """
        添加用户偏好

        Args:
            user_id: 用户ID
            key: 偏好键 (如 "favorite_customer", "default_template")
            value: 偏好值
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = _facade().UserMemory(user_id=user_id)
        memory.preferences[key] = {
            "value": value,
            "updated_at": _facade().datetime.now().isoformat(),
            "count": memory.preferences.get(key, {}).get("count", 0) + 1,
        }
        self._store.save_memory(user_id, memory)
        _facade().logger.debug("用户 %s 偏好已更新: %s = %s", user_id, key, value)

    def get_preference(
        self, user_id: str, key: str, default: _facade().Any = None
    ) -> _facade().Any:
        """
        获取用户偏好

        Args:
            user_id: 用户ID
            key: 偏好键
            default: 默认值

        Returns:
            偏好值或默认值
        """
        memory = self._store.get_memory(user_id)
        if memory and key in memory.preferences:
            return memory.preferences[key].get("value", default)
        return default

    def get_all_preferences(self, user_id: str) -> dict[str, _facade().Any]:
        """获取用户所有偏好"""
        memory = self._store.get_memory(user_id)
        if memory:
            return {k: v.get("value") for k, v in memory.preferences.items()}
        return {}

    def _normalize_memory_v2_type(self, memory_type: str) -> str:
        normalized = str(memory_type or "").strip().lower()
        aliases = {
            "pref": "preference",
            "preference_memory": "preference",
            "entity_memory": "entity",
            "episodic_memory": "episodic",
            "task": "episodic",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in _facade().MEMORY_V2_TYPES:
            raise ValueError(f"unsupported memory_type: {memory_type}")
        return normalized

    def _normalize_memory_v2_status(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized not in _facade().MEMORY_V2_STATUSES:
            raise ValueError(f"unsupported memory status: {status}")
        return normalized

    def _memory_v2_fingerprint(self, memory_type: str, key: str, value: _facade().Any) -> str:
        raw = _facade().json.dumps(
            {"memory_type": memory_type, "key": key, "value": value},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return _facade().hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _govern_memory_v2_candidate(
        self, *, source: str, confidence: float, evidence: list[dict[str, _facade().Any]] | None
    ) -> dict[str, _facade().Any]:
        normalized_source = str(source or "agent_observation").strip().lower()
        normalized_source = normalized_source.replace(" ", "_")[:80] or "agent_observation"
        flags: list[str] = []
        source_policy = "requires_confirmation"
        source_trust = "observed"
        try:
            effective_confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            effective_confidence = 0.5
            flags.append("invalid_confidence_defaulted")
        evidence_items = [
            dict(item) for item in list(evidence or []) if isinstance(item, dict) and item
        ][:10]
        evidence_required = False
        if normalized_source in _facade().MEMORY_V2_BLOCKED_SOURCES:
            source_policy = "blocked"
            source_trust = "blocked"
            flags.append("blocked_source")
            effective_confidence = min(effective_confidence, 0.0)
        elif normalized_source in _facade().MEMORY_V2_TRUSTED_SOURCES:
            source_policy = "trusted_pending"
            source_trust = "trusted_user"
        elif normalized_source in _facade().MEMORY_V2_OBSERVED_SOURCES:
            source_policy = "observed_pending"
            source_trust = "observed"
            evidence_required = True
        else:
            source_policy = "needs_evidence"
            source_trust = "unverified"
            evidence_required = True
            flags.append("unknown_source")
        if evidence_required and (not evidence_items):
            flags.append("missing_evidence")
            effective_confidence = min(effective_confidence, 0.35)
        return {
            "source": normalized_source,
            "source_policy": source_policy,
            "source_trust": source_trust,
            "source_evidence_required": evidence_required,
            "requires_user_confirmation": True,
            "auto_confirm_allowed": False,
            "eligible_for_planner": False,
            "governance_flags": flags,
            "confidence": effective_confidence,
            "evidence": evidence_items,
        }

    def _find_memory_v2_record(
        self, memory: _facade().UserMemory, memory_id: str
    ) -> tuple[int, dict[str, _facade().Any] | None]:
        for idx, record in enumerate(memory.memory_v2_records):
            if str(record.get("memory_id") or "") == str(memory_id or ""):
                return (idx, record)
        return (-1, None)

    def propose_memory_candidate(
        self,
        user_id: str,
        memory_type: str,
        key: str,
        value: _facade().Any,
        *,
        source: str = "agent_observation",
        confidence: float = 0.5,
        evidence: list[dict[str, _facade().Any]] | None = None,
    ) -> dict[str, _facade().Any]:
        """Atomically deduplicate and persist a governed memory candidate."""
        with self._memory_v2_lock:
            return self._propose_memory_candidate_unlocked(
                user_id,
                memory_type,
                key,
                value,
                source=source,
                confidence=confidence,
                evidence=evidence,
            )

    def _propose_memory_candidate_unlocked(
        self,
        user_id: str,
        memory_type: str,
        key: str,
        value: _facade().Any,
        *,
        source: str = "agent_observation",
        confidence: float = 0.5,
        evidence: list[dict[str, _facade().Any]] | None = None,
    ) -> dict[str, _facade().Any]:
        """写入待确认记忆候选，不直接污染 planner 可用记忆。"""
        normalized_type = self._normalize_memory_v2_type(memory_type)
        normalized_key = str(key or "").strip()
        if not user_id:
            return {"success": False, "message": "缺少 user_id"}
        if not normalized_key:
            return {"success": False, "message": "缺少 memory key"}
        governance = self._govern_memory_v2_candidate(
            source=source, confidence=confidence, evidence=evidence
        )
        memory = self._store.get_memory(user_id) or _facade().UserMemory(user_id=user_id)
        fingerprint = self._memory_v2_fingerprint(normalized_type, normalized_key, value)
        for record in memory.memory_v2_records:
            if record.get("fingerprint") == fingerprint and record.get("status") in {
                "pending",
                "active",
                "rejected",
            }:
                return {"success": True, "created": False, "candidate": dict(record)}
        now = _facade().datetime.now().isoformat()
        candidate = {
            "memory_id": f"mem_{_facade().uuid.uuid4().hex[:12]}",
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
        memory.memory_v2_records = memory.memory_v2_records[: _facade().MAX_MEMORY_V2_RECORDS]
        self._store.save_memory(user_id, memory)
        return {"success": True, "created": True, "candidate": dict(candidate)}

    def confirm_memory_candidate(
        self, user_id: str, memory_id: str, *, correction: dict[str, _facade().Any] | None = None
    ) -> dict[str, _facade().Any]:
        """确认候选记忆，确认后才进入 active 状态并可被 planner 使用。"""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self._find_memory_v2_record(memory, memory_id)
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
                updated["memory_type"] = self._normalize_memory_v2_type(str(patch["memory_type"]))
            if "key" in patch:
                updated["key"] = str(patch["key"] or "").strip()
            if "value" in patch:
                updated["value"] = patch["value"]
            if "confidence" in patch:
                updated["confidence"] = max(0.0, min(1.0, float(patch["confidence"])))
            updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
        if not str(updated.get("key") or "").strip():
            return {"success": False, "message": "缺少 memory key"}
        now = _facade().datetime.now().isoformat()
        updated["status"] = "active"
        updated["confirmed_at"] = now
        updated["updated_at"] = now
        updated["eligible_for_planner"] = True
        updated["fingerprint"] = self._memory_v2_fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
        memory.memory_v2_records[idx] = updated
        if updated["memory_type"] == "preference":
            key = str(updated["key"])
            memory.preferences[key] = {
                "value": updated.get("value"),
                "updated_at": now,
                "count": memory.preferences.get(key, {}).get("count", 0) + 1,
                "source": "memory_v2",
                "memory_id": updated["memory_id"],
            }
        self._store.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    def reject_memory_candidate(
        self, user_id: str, memory_id: str, *, reason: str = ""
    ) -> dict[str, _facade().Any]:
        return self._set_memory_v2_status(user_id, memory_id, "rejected", reason=reason)

    def delete_memory(
        self, user_id: str, memory_id: str, *, reason: str = ""
    ) -> dict[str, _facade().Any]:
        return self._set_memory_v2_status(user_id, memory_id, "deleted", reason=reason)

    def _set_memory_v2_status(
        self, user_id: str, memory_id: str, status: str, *, reason: str = ""
    ) -> dict[str, _facade().Any]:
        normalized_status = self._normalize_memory_v2_status(status)
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}
        updated = dict(record)
        now = _facade().datetime.now().isoformat()
        updated["status"] = normalized_status
        updated["updated_at"] = now
        if reason:
            updated[f"{normalized_status}_reason"] = reason
        if normalized_status == "deleted":
            updated["deleted_at"] = now
        if normalized_status == "rejected":
            updated["rejected_at"] = now
        memory.memory_v2_records[idx] = updated
        if (
            normalized_status in {"deleted", "rejected"}
            and record.get("memory_type") == "preference"
        ):
            pref_key = str(record.get("key") or "").strip()
            previous_pref = memory.preferences.get(pref_key)
            if isinstance(previous_pref, dict) and previous_pref.get("memory_id") == record.get(
                "memory_id"
            ):
                memory.preferences.pop(pref_key, None)
        self._store.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}
