"""Compatibility API assembled from the shared user-memory capabilities.

The legacy six-argument value constructor, JSON path and feedback policy remain
available. JSON writes use the canonical process lock and atomic replacement;
other historical storage values (including ``"sqlite"``) remain process-local.
"""

from __future__ import annotations

import hashlib as hashlib
import json as json
import logging
import os
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

from app.domain.user_memory.analysis import analyze_action_sequence as analyze_action_sequence
from app.domain.user_memory.analysis import feedback_stats as feedback_stats
from app.domain.user_memory.analysis import habit_suggestions as habit_suggestions
from app.domain.user_memory.analysis import memory_summary as memory_summary
from app.domain.user_memory.models import ActionPattern as ActionPattern
from app.domain.user_memory.models import ContextSummary as ContextSummary
from app.domain.user_memory.models import FeedbackRecord as FeedbackRecord
from app.domain.user_memory.models import UserMemory as UserMemory
from app.domain.user_memory.records import UserMemory as MemoryRecord
from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS
from app.utils.process_lock import exclusive_file_lock

if TYPE_CHECKING:
    from app.application.user_memory.ports import MemoryStore

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_DIR = os.path.join(BASE_DIR, "user_memory")
JSON_MEMORY_PATH = os.path.join(MEMORY_DIR, "memory_store.json")

MAX_FEEDBACK_HISTORY = 100
MAX_FREQUENT_ACTIONS = 20
MAX_CONTEXT_SUMMARIES = 10


class UserMemoryStore:
    """Preserve the legacy store API while owning one snapshot repository."""

    _instance: UserMemoryStore | None = None
    _initialized: bool

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cast(Self, cls._instance)

    def __init__(self, storage_type: str = "json") -> None:
        if getattr(self, "_initialized", False):
            return
        from app.infrastructure.user_memory.json_storage import JsonMemoryStorage
        from app.infrastructure.user_memory.persistence import MemoryRepository

        self.storage_type = storage_type
        self._cache_dirty: dict[str, bool] = {}
        path = Path(JSON_MEMORY_PATH)
        lock_path = path.with_name(f"{path.name}.lock")
        backend = (
            JsonMemoryStorage(
                path,
                lock=lambda: exclusive_file_lock(
                    lock_path, blocking=True, timeout=60, reject_symlink=True
                ),
                deserialize=lambda data: UserMemory.from_dict(data),
                temporary_id=lambda: uuid.uuid4().hex,
            )
            if storage_type == "json"
            else None
        )
        self._repository = MemoryRepository(
            storage_type=storage_type,
            memory_path=path,
            backend=backend,
            new_memory=lambda user_id: UserMemory(user_id=user_id),
            now=lambda: datetime.now().isoformat(),
            logger=logger,
        )
        self._initialized = True

    @property
    def _memory_cache(self) -> dict[str, MemoryRecord]:
        return self._repository._memory_cache

    @_memory_cache.setter
    def _memory_cache(self, memories: dict[str, MemoryRecord]) -> None:
        self._repository._memory_cache = memories

    def transaction(self) -> AbstractContextManager[None]:
        return self._repository.transaction()

    def _load_all_memories(self) -> None:
        self._repository._load_all_memories()

    def _save_all_memories(self) -> None:
        self._repository._save_all_memories()

    def get_memory(self, user_id: str) -> MemoryRecord | None:
        return self._repository.get_memory(user_id)

    def save_memory(self, user_id: str, memory: MemoryRecord) -> None:
        def persist() -> None:
            if self._should_persist():
                self._save_all_memories()
                self._cache_dirty[user_id] = False

        with self.transaction():
            self._cache_dirty[user_id] = True
            self._repository.save_legacy_memory(user_id, memory, persist)

    def _should_persist(self) -> bool:
        return any(self._cache_dirty.values())


class UserMemoryService:
    """Legacy preference, action and feedback API with explicit component ports."""

    _instance: UserMemoryService | None = None
    _initialized: bool
    _store: MemoryStore

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cast(Self, cls._instance)

    def __init__(self, storage_type: str = "json") -> None:
        if getattr(self, "_initialized", False):
            return
        from app.application.user_memory.feedback import FeedbackMemory, FeedbackPorts
        from app.application.user_memory.patterns import ActionMemory, PatternPorts
        from app.application.user_memory.ports import MemoryAccess, late_callback
        from app.application.user_memory.preferences import PreferenceMemory

        self._store = UserMemoryStore(storage_type=storage_type)
        access = MemoryAccess(
            transaction=late_callback(lambda: self._store.transaction),
            get_memory=late_callback(lambda: self._store.get_memory),
            save_memory=late_callback(lambda: self._store.save_memory),
            new_memory=lambda user_id: UserMemory(user_id=user_id),
            now=lambda: datetime.now().isoformat(),
        )
        self._preferences = PreferenceMemory(
            access, late_callback(lambda: self.get_preference), logger
        )
        self._patterns = ActionMemory(
            access,
            PatternPorts(
                action_factory=late_callback(lambda: ActionPattern),
                context_factory=late_callback(lambda: ContextSummary),
                pattern_key=late_callback(lambda: self._make_pattern_key),
                save_context=late_callback(lambda: self._save_context_summary),
                similarity=late_callback(lambda: self._calculate_similarity),
                analyze_sequence=late_callback(lambda: self._analyze_action_sequence),
                max_actions=lambda: MAX_FREQUENT_ACTIONS,
                max_contexts=lambda: MAX_CONTEXT_SUMMARIES,
            ),
            logger,
        )
        self._feedback = FeedbackMemory(
            access,
            FeedbackPorts(
                record_factory=late_callback(lambda: FeedbackRecord),
                adjust_weights=late_callback(lambda: self._adjust_pattern_weights),
                max_history=lambda: MAX_FEEDBACK_HISTORY,
                corrected_policy="legacy_penalty",
            ),
            logger,
        )
        self._initialized = True
        logger.info("用户记忆服务已初始化")

    def add_preference(self, user_id: str, key: str, value: Any) -> None:
        self._preferences.add_preference(user_id, key, value)

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        return self._preferences.get_preference(user_id, key, default)

    def get_all_preferences(self, user_id: str) -> dict[str, Any]:
        return self._preferences.get_all_preferences(user_id)

    def record_action(
        self, user_id: str, intent: str, slots: dict[str, Any], message: str = ""
    ) -> None:
        self._patterns.record_action(user_id, intent, slots, message)

    def _make_pattern_key(self, intent: str, slots: dict[str, Any]) -> str:
        return self._patterns.make_pattern_key(intent, slots)

    def _save_context_summary(
        self, memory: MemoryRecord, intent: str, slots: dict[str, Any], message: str
    ) -> None:
        self._patterns.save_context_summary(memory, intent, slots, message)

    def get_recent_actions(
        self, user_id: str, limit: int = 5, intent_filter: str | None = None
    ) -> list[dict[str, Any]]:
        return self._patterns.get_recent_actions(user_id, limit, intent_filter)

    def get_similar_pattern(
        self, user_id: str, intent: str, slots: dict[str, Any], threshold: float = 0.2
    ) -> dict[str, Any] | None:
        return self._patterns.get_similar_pattern(user_id, intent, slots, threshold)

    def _calculate_similarity(self, slots1: dict[str, Any], slots2: dict[str, Any]) -> float:
        return self._patterns.calculate_similarity(slots1, slots2)

    def add_feedback(
        self,
        user_id: str,
        message: str,
        recognized_intent: str,
        feedback: str,
        corrected_intent: str | None = None,
        slots: dict[str, Any] | None = None,
    ) -> None:
        self._feedback.add_feedback(
            user_id, message, recognized_intent, feedback, corrected_intent, slots
        )

    def _adjust_pattern_weights(
        self,
        memory: MemoryRecord,
        recognized_intent: str,
        corrected_intent: str | None,
        feedback: str,
    ) -> None:
        self._feedback.adjust_pattern_weights(memory, recognized_intent, corrected_intent, feedback)

    def get_feedback_stats(self, user_id: str) -> dict[str, Any]:
        return feedback_stats(self._store.get_memory(user_id))

    def get_habit_suggestions(self, user_id: str) -> list[dict[str, Any]]:
        return habit_suggestions(self._store.get_memory(user_id))

    def _analyze_action_sequence(self, memory: MemoryRecord) -> list[dict[str, Any]]:
        return analyze_action_sequence(memory)

    def apply_preference_to_slots(
        self, user_id: str, intent: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        return self._preferences.apply_preference_to_slots(user_id, intent, slots)

    def get_memory_summary(self, user_id: str) -> dict[str, Any]:
        return memory_summary(self._store.get_memory(user_id))


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
