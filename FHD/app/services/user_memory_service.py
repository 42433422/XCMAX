"""
用户记忆服务 - UserMemoryService

提供跨会话的长期记忆能力，包括：
- 用户偏好记忆
- 操作模式学习
- 上下文摘要
- 反馈记录与难例挖掘

支持 SQLite 和 JSON 文件两种存储后端。
"""

import hashlib
import json
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_DIR = os.path.join(BASE_DIR, "user_memory")
JSON_MEMORY_PATH = os.path.join(MEMORY_DIR, "memory_store.json")

MAX_FEEDBACK_HISTORY = 100
MAX_FREQUENT_ACTIONS = 20
MAX_CONTEXT_SUMMARIES = 10
MAX_MEMORY_V2_RECORDS = 200

MEMORY_V2_TYPES = {"preference", "entity", "episodic"}
MEMORY_V2_STATUSES = {"pending", "active", "rejected", "deleted"}
MEMORY_V2_TRUSTED_SOURCES = {
    "agent_eval",
    "memory_v2_api",
    "settings_ui",
    "user_correction",
    "user_explicit",
}
MEMORY_V2_OBSERVED_SOURCES = {
    "agent_observation",
    "chat_trace",
    "excel_artifact",
    "file_analysis",
    "ocr_artifact",
    "tool_observation",
    "workflow_observation",
}
MEMORY_V2_BLOCKED_SOURCES = {
    "llm_guess",
    "llm_inference_only",
    "prompt_injection",
    "system_prompt",
    "unsafe_import",
}


@dataclass
class ActionPattern:
    pattern: str
    intent: str
    slots: dict[str, Any]
    frequency: int = 1
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionPattern":
        return cls(**data)


@dataclass
class FeedbackRecord:
    timestamp: str
    message: str
    recognized_intent: str
    user_feedback: str
    corrected_intent: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeedbackRecord":
        return cls(**data)


@dataclass
class ContextSummary:
    timestamp: str
    intent: str
    slots: dict[str, Any]
    message: str
    turn_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextSummary":
        return cls(**data)


@dataclass
class UserMemory:
    user_id: str
    preferences: dict[str, Any] = field(default_factory=dict)
    frequent_actions: list[dict[str, Any]] = field(default_factory=list)
    historical_contexts: list[dict[str, Any]] = field(default_factory=list)
    feedback_history: list[dict[str, Any]] = field(default_factory=list)
    memory_v2_records: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserMemory":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class UserMemoryStore:
    """用户记忆存储后端"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_type: str = "json"):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.storage_type = storage_type
        self._memory_cache: dict[str, UserMemory] = {}
        self._cache_dirty: dict[str, bool] = {}
        self._load_all_memories()
        self._initialized = True

    def _load_all_memories(self) -> None:
        """加载所有用户记忆"""
        if self.storage_type == "json" and os.path.exists(JSON_MEMORY_PATH):
            try:
                with open(JSON_MEMORY_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, memory_data in data.items():
                        self._memory_cache[user_id] = UserMemory.from_dict(memory_data)
                logger.info("从 %s 加载了 %s 个用户记忆", JSON_MEMORY_PATH, len(self._memory_cache))
            except RECOVERABLE_ERRORS as e:
                logger.error("加载用户记忆失败: %s", e)
                self._memory_cache = {}

    def _save_all_memories(self) -> None:
        """保存所有用户记忆到磁盘"""
        if self.storage_type != "json":
            return

        try:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            data = {user_id: memory.to_dict() for user_id, memory in self._memory_cache.items()}
            with open(JSON_MEMORY_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("已保存 %s 个用户记忆到 %s", len(self._memory_cache), JSON_MEMORY_PATH)
        except RECOVERABLE_ERRORS as e:
            logger.error("保存用户记忆失败: %s", e)

    def get_memory(self, user_id: str) -> UserMemory | None:
        """获取用户记忆"""
        if user_id not in self._memory_cache:
            self._memory_cache[user_id] = UserMemory(user_id=user_id)
        return self._memory_cache[user_id]

    def save_memory(self, user_id: str, memory: UserMemory) -> None:
        """保存用户记忆"""
        memory.updated_at = datetime.now().isoformat()
        self._memory_cache[user_id] = memory
        self._cache_dirty[user_id] = True

        if self._should_persist():
            self._save_all_memories()
            self._cache_dirty[user_id] = False

    def _should_persist(self) -> bool:
        """判断是否应该持久化"""
        return any(self._cache_dirty.values())


class UserMemoryService(NeuroEventPublisherMixin):
    """
    用户记忆服务

    提供：
    - add_preference: 添加用户偏好
    - get_preference: 获取用户偏好
    - record_action: 记录用户操作
    - get_recent_actions: 获取最近操作
    - get_similar_pattern: 查找相似模式
    - add_feedback: 添加反馈
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_type: str = "json"):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._store = UserMemoryStore(storage_type=storage_type)
        self._initialized = True
        logger.info("用户记忆服务已初始化")

    def add_preference(self, user_id: str, key: str, value: Any) -> None:
        """
        添加用户偏好

        Args:
            user_id: 用户ID
            key: 偏好键 (如 "favorite_customer", "default_template")
            value: 偏好值
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = UserMemory(user_id=user_id)

        memory.preferences[key] = {
            "value": value,
            "updated_at": datetime.now().isoformat(),
            "count": memory.preferences.get(key, {}).get("count", 0) + 1,
        }

        self._store.save_memory(user_id, memory)
        logger.debug("用户 %s 偏好已更新: %s = %s", user_id, key, value)

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
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

    def get_all_preferences(self, user_id: str) -> dict[str, Any]:
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
        if normalized not in MEMORY_V2_TYPES:
            raise ValueError(f"unsupported memory_type: {memory_type}")
        return normalized

    def _normalize_memory_v2_status(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized not in MEMORY_V2_STATUSES:
            raise ValueError(f"unsupported memory status: {status}")
        return normalized

    def _memory_v2_fingerprint(self, memory_type: str, key: str, value: Any) -> str:
        raw = json.dumps(
            {"memory_type": memory_type, "key": key, "value": value},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _govern_memory_v2_candidate(
        self,
        *,
        source: str,
        confidence: float,
        evidence: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
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
        if normalized_source in MEMORY_V2_BLOCKED_SOURCES:
            source_policy = "blocked"
            source_trust = "blocked"
            flags.append("blocked_source")
            effective_confidence = min(effective_confidence, 0.0)
        elif normalized_source in MEMORY_V2_TRUSTED_SOURCES:
            source_policy = "trusted_pending"
            source_trust = "trusted_user"
        elif normalized_source in MEMORY_V2_OBSERVED_SOURCES:
            source_policy = "observed_pending"
            source_trust = "observed"
            evidence_required = True
        else:
            source_policy = "needs_evidence"
            source_trust = "unverified"
            evidence_required = True
            flags.append("unknown_source")

        if evidence_required and not evidence_items:
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
        self, memory: UserMemory, memory_id: str
    ) -> tuple[int, dict[str, Any] | None]:
        for idx, record in enumerate(memory.memory_v2_records):
            if str(record.get("memory_id") or "") == str(memory_id or ""):
                return idx, record
        return -1, None

    def propose_memory_candidate(
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
        normalized_type = self._normalize_memory_v2_type(memory_type)
        normalized_key = str(key or "").strip()
        if not user_id:
            return {"success": False, "message": "缺少 user_id"}
        if not normalized_key:
            return {"success": False, "message": "缺少 memory key"}

        governance = self._govern_memory_v2_candidate(
            source=source,
            confidence=confidence,
            evidence=evidence,
        )
        memory = self._store.get_memory(user_id) or UserMemory(user_id=user_id)
        fingerprint = self._memory_v2_fingerprint(normalized_type, normalized_key, value)
        for record in memory.memory_v2_records:
            if record.get("fingerprint") == fingerprint and record.get("status") in {
                "pending",
                "active",
                "rejected",
            }:
                return {"success": True, "created": False, "candidate": dict(record)}

        now = datetime.now().isoformat()
        candidate = {
            "memory_id": f"mem_{uuid.uuid4().hex[:12]}",
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
        memory.memory_v2_records = memory.memory_v2_records[:MAX_MEMORY_V2_RECORDS]
        self._store.save_memory(user_id, memory)
        return {"success": True, "created": True, "candidate": dict(candidate)}

    def confirm_memory_candidate(
        self,
        user_id: str,
        memory_id: str,
        *,
        correction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

        now = datetime.now().isoformat()
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
    ) -> dict[str, Any]:
        return self._set_memory_v2_status(user_id, memory_id, "rejected", reason=reason)

    def delete_memory(self, user_id: str, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._set_memory_v2_status(user_id, memory_id, "deleted", reason=reason)

    def _set_memory_v2_status(
        self, user_id: str, memory_id: str, status: str, *, reason: str = ""
    ) -> dict[str, Any]:
        normalized_status = self._normalize_memory_v2_status(status)
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}

        updated = dict(record)
        now = datetime.now().isoformat()
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

    def correct_memory(
        self,
        user_id: str,
        memory_id: str,
        *,
        value: Any | None = None,
        key: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """纠正 active/pending 记忆，保留同一个 memory_id 便于审计。"""
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"success": False, "message": "用户记忆不存在"}
        idx, record = self._find_memory_v2_record(memory, memory_id)
        if record is None:
            return {"success": False, "message": "记忆不存在"}
        if record.get("status") == "deleted":
            return {"success": False, "message": "记忆已删除"}

        updated = dict(record)
        previous_key = str(record.get("key") or "").strip()
        if key is not None:
            updated["key"] = str(key or "").strip()
        if value is not None:
            updated["value"] = value
        if not str(updated.get("key") or "").strip():
            return {"success": False, "message": "缺少 memory key"}

        now = datetime.now().isoformat()
        updated["updated_at"] = now
        updated["last_correction_reason"] = reason
        updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
        updated["fingerprint"] = self._memory_v2_fingerprint(
            str(updated["memory_type"]), str(updated["key"]), updated.get("value")
        )
        memory.memory_v2_records[idx] = updated

        if updated.get("status") == "active" and updated.get("memory_type") == "preference":
            if previous_key and previous_key != str(updated["key"]):
                previous_pref = memory.preferences.get(previous_key)
                if (
                    isinstance(previous_pref, dict)
                    and previous_pref.get("memory_id") == updated["memory_id"]
                ):
                    memory.preferences.pop(previous_key, None)
            pref_key = str(updated["key"])
            memory.preferences[pref_key] = {
                "value": updated.get("value"),
                "updated_at": now,
                "count": memory.preferences.get(pref_key, {}).get("count", 0) + 1,
                "source": "memory_v2",
                "memory_id": updated["memory_id"],
            }

        self._store.save_memory(user_id, memory)
        return {"success": True, "memory": dict(updated)}

    def list_memories(
        self,
        user_id: str,
        *,
        status: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        memory = self._store.get_memory(user_id)
        if memory is None:
            return []
        normalized_status = self._normalize_memory_v2_status(status) if status else None
        normalized_type = self._normalize_memory_v2_type(memory_type) if memory_type else None
        records = []
        for record in memory.memory_v2_records:
            if normalized_status and record.get("status") != normalized_status:
                continue
            if normalized_type and record.get("memory_type") != normalized_type:
                continue
            records.append(dict(record))
        return records

    def get_memory_v2_summary(self, user_id: str) -> dict[str, Any]:
        memory = self._store.get_memory(user_id)
        if memory is None:
            return {"total": 0, "by_status": {}, "by_type": {}}
        by_status: object = defaultdict(int)
        by_type: object = defaultdict(int)
        by_source_policy: object = defaultdict(int)
        for record in memory.memory_v2_records:
            by_status[str(record.get("status") or "unknown")] += 1
            by_type[str(record.get("memory_type") or "unknown")] += 1
            by_source_policy[str(record.get("source_policy") or "unknown")] += 1
        return {
            "total": len(memory.memory_v2_records),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "by_source_policy": dict(by_source_policy),
        }

    def format_memory_v2_for_prompt(
        self,
        user_id: str,
        *,
        max_items: int = 6,
        memory_type: str | None = None,
    ) -> str:
        """Format confirmed Memory v2 records as compact planner context."""
        active = [
            record
            for record in self.list_memories(user_id, status="active", memory_type=memory_type)
            if record.get("source_policy") != "blocked"
            and record.get("eligible_for_planner", True) is not False
        ]
        if not active:
            return "【MemoryV2】无已确认记忆。"

        type_order = {"preference": 0, "entity": 1, "episodic": 2}
        active.sort(
            key=lambda item: (
                type_order.get(str(item.get("memory_type") or ""), 99),
                str(item.get("updated_at") or ""),
            ),
            reverse=False,
        )
        lines = ["【MemoryV2】已确认记忆（仅供 planner 补全偏好/实体/任务上下文，不得编造）:"]
        for idx, record in enumerate(active[: max(1, int(max_items))], start=1):
            memory_kind = str(record.get("memory_type") or "unknown")
            key = str(record.get("key") or "-")
            value = json.dumps(record.get("value"), ensure_ascii=False, default=str)
            confidence = float(record.get("confidence") or 0.0)
            source = str(record.get("source") or "-")
            updated_at = str(record.get("updated_at") or "-")
            lines.append(
                f"{idx}. type={memory_kind}; key={key}; value={value}; "
                f"confidence={confidence:.2f}; source={source}; updated_at={updated_at}"
            )
        return "\n".join(lines)

    def record_action(
        self, user_id: str, intent: str, slots: dict[str, Any], message: str = ""
    ) -> None:
        """
        记录用户操作模式

        Args:
            user_id: 用户ID
            intent: 意图类型
            slots: 槽位信息
            message: 原始消息
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = UserMemory(user_id=user_id)

        pattern_key = self._make_pattern_key(intent, slots)
        existing_pattern = None
        pattern_idx = -1

        for idx, action in enumerate(memory.frequent_actions):
            if action.get("pattern") == pattern_key:
                existing_pattern = action
                pattern_idx = idx
                break

        if existing_pattern:
            existing_pattern["frequency"] += 1
            existing_pattern["last_used"] = datetime.now().isoformat()
            existing_pattern["confidence"] = min(0.99, existing_pattern["confidence"] + 0.05)
            memory.frequent_actions[pattern_idx] = existing_pattern
        else:
            new_pattern = ActionPattern(
                pattern=pattern_key,
                intent=intent,
                slots=slots,
                frequency=1,
                last_used=datetime.now().isoformat(),
                confidence=0.5,
            )
            memory.frequent_actions.insert(0, new_pattern.to_dict())

        memory.frequent_actions.sort(key=lambda x: x.get("frequency", 0), reverse=True)
        memory.frequent_actions = memory.frequent_actions[:MAX_FREQUENT_ACTIONS]

        self._save_context_summary(memory, intent, slots, message)

        self._store.save_memory(user_id, memory)
        logger.debug("用户 %s 操作已记录: intent=%s, slots=%s", user_id, intent, slots)

    def _make_pattern_key(self, intent: str, slots: dict[str, Any]) -> str:
        """生成模式唯一键"""
        key_parts = [intent]
        important_slots = ["unit_name", "product_name", "model_number"]
        for slot_key in important_slots:
            if slot_key in slots and slots[slot_key]:
                key_parts.append(f"{slot_key}={slots[slot_key]}")
        key_str = "|".join(key_parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _save_context_summary(
        self, memory: UserMemory, intent: str, slots: dict[str, Any], message: str
    ) -> None:
        """保存上下文摘要"""
        summary = ContextSummary(
            timestamp=datetime.now().isoformat(),
            intent=intent,
            slots=slots,
            message=message[:100] if message else "",
            turn_count=1,
        )
        memory.historical_contexts.insert(0, summary.to_dict())
        memory.historical_contexts = memory.historical_contexts[:MAX_CONTEXT_SUMMARIES]

    def get_recent_actions(
        self, user_id: str, limit: int = 5, intent_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """
        获取最近操作模式

        Args:
            user_id: 用户ID
            limit: 返回数量
            intent_filter: 意图过滤器

        Returns:
            最近操作列表
        """
        memory = self._store.get_memory(user_id)
        if not memory:
            return []

        actions = memory.frequent_actions
        if intent_filter:
            actions = [a for a in actions if a.get("intent") == intent_filter]

        return actions[:limit]

    def get_similar_pattern(
        self, user_id: str, intent: str, slots: dict[str, Any], threshold: float = 0.2
    ) -> dict[str, Any] | None:
        """
        查找相似的操作模式

        Args:
            user_id: 用户ID
            intent: 目标意图
            slots: 当前槽位
            threshold: 相似度阈值

        Returns:
            相似模式或 None
        """
        memory = self._store.get_memory(user_id)
        if not memory:
            return None

        best_match = None
        best_score = 0.0

        for action in memory.frequent_actions:
            if action.get("intent") != intent:
                continue

            score = self._calculate_similarity(slots, action.get("slots", {}))
            action_confidence = action.get("confidence", 0.5)

            if score >= 0.5:
                combined_score = score
            else:
                combined_score = score * action_confidence

            if combined_score > best_score and combined_score >= threshold:
                best_score = combined_score
                best_match = action

        if best_match:
            best_match["match_score"] = round(best_score, 3)

        return best_match

    def _calculate_similarity(self, slots1: dict[str, Any], slots2: dict[str, Any]) -> float:
        """计算槽位相似度"""
        if not slots1 and not slots2:
            return 1.0

        important_keys = ["unit_name", "spec", "model_number", "quantity", "product_name"]
        match_count = 0
        total_count = 0

        for key in important_keys:
            v1 = slots1.get(key, "") or slots1.get(key)
            v2 = slots2.get(key, "") or slots2.get(key)
            if v1 and v2:
                total_count += 1
                if str(v1) == str(v2):
                    match_count += 1

        if total_count == 0:
            return 0.5

        return match_count / total_count

    def add_feedback(
        self,
        user_id: str,
        message: str,
        recognized_intent: str,
        feedback: str,
        corrected_intent: str | None = None,
        slots: dict[str, Any] | None = None,
    ) -> None:
        """
        添加用户反馈

        Args:
            user_id: 用户ID
            message: 用户消息
            recognized_intent: 系统识别的意图
            feedback: 反馈类型 (confirmed/negated/corrected)
            corrected_intent: 正确意图（当 feedback=corrected 时）
            slots: 槽位信息
        """
        memory = self._store.get_memory(user_id)
        if memory is None:
            memory = UserMemory(user_id=user_id)

        record = FeedbackRecord(
            timestamp=datetime.now().isoformat(),
            message=message[:200] if message else "",
            recognized_intent=recognized_intent,
            user_feedback=feedback,
            corrected_intent=corrected_intent,
            slots=slots or {},
        )
        memory.feedback_history.insert(0, record.to_dict())
        memory.feedback_history = memory.feedback_history[:MAX_FEEDBACK_HISTORY]

        self._adjust_pattern_weights(memory, recognized_intent, corrected_intent, feedback)

        self._store.save_memory(user_id, memory)
        logger.debug(
            "用户 %s 反馈已记录: feedback=%s, recognized=%s", user_id, feedback, recognized_intent
        )

    def _adjust_pattern_weights(
        self,
        memory: UserMemory,
        recognized_intent: str,
        corrected_intent: str | None,
        feedback: str,
    ) -> None:
        """调整模式权重"""
        weight_delta = 0
        target_intent = recognized_intent

        if feedback == "confirmed":
            weight_delta = 0.1
        elif feedback == "negated":
            weight_delta = -0.15
        elif feedback == "corrected" and corrected_intent:
            for action in memory.frequent_actions:
                if action.get("intent") == recognized_intent:
                    new_confidence = action.get("confidence", 0.5) - 0.1
                    action["confidence"] = max(0.1, min(0.99, new_confidence))
            target_intent = corrected_intent
            weight_delta = 0.1

        for action in memory.frequent_actions:
            if action.get("intent") == target_intent:
                new_confidence = action.get("confidence", 0.5) + weight_delta
                action["confidence"] = max(0.1, min(0.99, new_confidence))

    def get_feedback_stats(self, user_id: str) -> dict[str, Any]:
        """获取反馈统计"""
        memory = self._store.get_memory(user_id)
        if not memory:
            return {"total": 0, "confirmed": 0, "negated": 0, "corrected": 0}

        feedback_counts: object = defaultdict(int)
        intent_error_rates: object = defaultdict(lambda: {"total": 0, "errors": 0})

        for record in memory.feedback_history:
            fb_type = record.get("user_feedback", "unknown")
            feedback_counts[fb_type] += 1

            recognized = record.get("recognized_intent", "")
            intent_error_rates[recognized]["total"] += 1
            if fb_type in ("negated", "corrected"):
                intent_error_rates[recognized]["errors"] += 1

        error_rates = {}
        for intent, stats in intent_error_rates.items():
            if stats["total"] >= 3:
                error_rates[intent] = round(stats["errors"] / stats["total"], 3)

        return {
            "total": len(memory.feedback_history),
            "confirmed": feedback_counts.get("confirmed", 0),
            "negated": feedback_counts.get("negated", 0),
            "corrected": feedback_counts.get("corrected", 0),
            "error_rates": error_rates,
        }

    def get_habit_suggestions(self, user_id: str) -> list[dict[str, Any]]:
        """
        获取操作习惯建议

        Returns:
            习惯建议列表 (如：生成发货单后经常打印标签)
        """
        memory = self._store.get_memory(user_id)
        if not memory:
            return []

        suggestions = []
        action_sequence = self._analyze_action_sequence(memory)

        for seq in action_sequence:
            if seq["confidence"] >= 0.8 and len(seq["actions"]) >= 2:
                suggestions.append(
                    {
                        "type": "action_sequence",
                        "actions": seq["actions"],
                        "confidence": seq["confidence"],
                        "suggestion": f"执行 {seq['actions'][0]} 后主动提示 {seq['actions'][1]}",
                    }
                )

        return suggestions

    def _analyze_action_sequence(self, memory: UserMemory) -> list[dict[str, Any]]:
        """分析操作序列"""
        sequences: object = defaultdict(lambda: {"count": 0, "first_action": ""})

        for i in range(len(memory.historical_contexts) - 1):
            current = memory.historical_contexts[i]
            next_ctx = memory.historical_contexts[i + 1]

            seq_key = f"{current.get('intent')}->{next_ctx.get('intent')}"
            sequences[seq_key]["count"] += 1
            sequences[seq_key]["first_action"] = current.get("intent")

        result = []
        for seq_key, stats in sequences.items():
            if stats["count"] >= 2:
                actions = seq_key.split("->")
                result.append(
                    {
                        "actions": actions,
                        "confidence": min(0.95, stats["count"] * 0.15),
                        "count": stats["count"],
                    }
                )

        return result

    def apply_preference_to_slots(
        self, user_id: str, intent: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        """
        将用户偏好应用到槽位

        Args:
            user_id: 用户ID
            intent: 当前意图
            slots: 当前槽位

        Returns:
            填充后的槽位
        """
        filled_slots = slots.copy()

        if "unit_name" not in filled_slots or not filled_slots["unit_name"]:
            favorite_customer = self.get_preference(user_id, "favorite_customer")
            if favorite_customer:
                filled_slots["unit_name"] = favorite_customer

        if "template" not in filled_slots:
            default_template = self.get_preference(user_id, "default_template")
            if default_template:
                filled_slots["template"] = default_template

        return filled_slots

    def get_memory_summary(self, user_id: str) -> dict[str, Any]:
        """获取用户记忆摘要"""
        memory = self._store.get_memory(user_id)
        if not memory:
            return {"has_memory": False}

        return {
            "has_memory": True,
            "preference_count": len(memory.preferences),
            "action_count": len(memory.frequent_actions),
            "feedback_count": len(memory.feedback_history),
            "memory_v2_count": len(memory.memory_v2_records),
            "memory_v2_pending_count": len(
                [m for m in memory.memory_v2_records if m.get("status") == "pending"]
            ),
            "memory_v2_active_count": len(
                [m for m in memory.memory_v2_records if m.get("status") == "active"]
            ),
            "last_updated": memory.updated_at,
            "top_intents": [a.get("intent") for a in memory.frequent_actions[:3]],
        }


_user_memory_service: UserMemoryService | None = None


def get_user_memory_service() -> UserMemoryService:
    """获取用户记忆服务单例"""
    global _user_memory_service
    if _user_memory_service is None:
        _user_memory_service = UserMemoryService()
    return _user_memory_service


def reset_user_memory_service() -> None:
    """重置用户记忆服务单例"""
    global _user_memory_service
    _user_memory_service = None
    UserMemoryService._instance = None
    UserMemoryStore._instance = None


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(UserMemoryService, "app.services.user_memory_service")
