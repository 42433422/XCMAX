# ruff: noqa: E402, F401
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
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.process_lock import exclusive_file_lock

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_DIR = os.environ.get("XCAGI_USER_MEMORY_DIR", os.path.join(BASE_DIR, "user_memory"))
JSON_MEMORY_PATH = os.environ.get(
    "XCAGI_USER_MEMORY_JSON_PATH", os.path.join(MEMORY_DIR, "memory_store.json")
)


def memory_store_transaction(method):
    @wraps(method)
    def wrapped(self, user_id, *args, **kwargs):
        with self._store.transaction():
            return method(self, user_id, *args, **kwargs)

    return wrapped


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

    _instance: "UserMemoryStore | None" = None
    _initialized: bool

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_type: str = "json"):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.storage_type = storage_type
        configured_dir = os.environ.get("XCAGI_USER_MEMORY_DIR")
        memory_dir = Path(configured_dir or MEMORY_DIR)
        configured_path = os.environ.get("XCAGI_USER_MEMORY_JSON_PATH")
        memory_path = Path(
            configured_path
            or (memory_dir / "memory_store.json" if configured_dir else JSON_MEMORY_PATH)
        )
        self._memory_path = memory_path
        self._lock_path = memory_path.with_name(f"{memory_path.name}.lock")
        self._transaction_lock = threading.RLock()
        self._transaction_state = threading.local()
        self._memory_cache: dict[str, UserMemory] = {}
        self._load_all_memories()
        self._initialized = True

    @contextmanager
    def transaction(self):
        depth = getattr(self._transaction_state, "depth", 0)
        if depth:
            self._transaction_state.depth += 1
            try:
                yield
            finally:
                self._transaction_state.depth -= 1
            return
        with self._transaction_lock:
            if self.storage_type == "json":
                with exclusive_file_lock(
                    self._lock_path, blocking=True, timeout=60, reject_symlink=True
                ):
                    self._transaction_state.depth = 1
                    try:
                        self._load_all_memories(strict=True)
                        yield
                    finally:
                        self._transaction_state.depth = 0
            else:
                self._transaction_state.depth = 1
                try:
                    yield
                finally:
                    self._transaction_state.depth = 0

    def _load_all_memories(self, *, strict: bool = False) -> None:
        """加载所有用户记忆"""
        self._memory_cache.clear()
        if self.storage_type == "json" and self._memory_path.exists():
            try:
                with self._memory_path.open(encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, memory_data in data.items():
                        self._memory_cache[user_id] = UserMemory.from_dict(memory_data)
                logger.info(
                    "从 %s 加载了 %s 个用户记忆", self._memory_path, len(self._memory_cache)
                )
            except RECOVERABLE_ERRORS as exc:
                self._memory_cache.clear()
                if strict:
                    raise
                logger.error("加载用户记忆失败: %s", exc)

    def _save_all_memories(self) -> None:
        """保存所有用户记忆到磁盘"""
        if self.storage_type != "json":
            return

        with self.transaction():
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            data = {user_id: memory.to_dict() for user_id, memory in self._memory_cache.items()}
            temporary = self._memory_path.with_name(
                f".{self._memory_path.name}.{uuid.uuid4().hex}.tmp"
            )
            try:
                with temporary.open("w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, self._memory_path)
            finally:
                temporary.unlink(missing_ok=True)
            logger.debug("已保存 %s 个用户记忆到 %s", len(self._memory_cache), self._memory_path)

    def get_memory(self, user_id: str) -> UserMemory | None:
        """获取用户记忆"""
        with self.transaction():
            if user_id not in self._memory_cache:
                self._memory_cache[user_id] = UserMemory(user_id=user_id)
            return self._memory_cache[user_id]

    def save_memory(self, user_id: str, memory: UserMemory) -> None:
        """保存用户记忆"""
        with self.transaction():
            memory.updated_at = datetime.now().isoformat()
            self._memory_cache[user_id] = memory
            self._save_all_memories()


from app.services.user_memory_service_usermemoryservice_mixin01 import _UserMemoryServicePart01Mixin
from app.services.user_memory_service_usermemoryservice_mixin02 import _UserMemoryServicePart02Mixin


class UserMemoryService(
    _UserMemoryServicePart01Mixin, _UserMemoryServicePart02Mixin, NeuroEventPublisherMixin
):
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

    _instance: "UserMemoryService | None" = None
    _initialized: bool


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
