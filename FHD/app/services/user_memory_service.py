"""Compose durable JSON and volatile user-memory operations.

Only ``storage_type="json"`` persists data. Other historical values, including
``"sqlite"``, keep their existing process-local behavior; this module does not
implement a SQLite backend.
"""

from __future__ import annotations

import hashlib as hashlib
import json as json
import logging
import os
import threading
import uuid
from collections import defaultdict as defaultdict
from collections.abc import Callable
from contextlib import contextmanager as contextmanager
from dataclasses import asdict as asdict
from dataclasses import dataclass as dataclass
from dataclasses import field as field
from dataclasses import fields as fields
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, Protocol, Self, TypeVar, cast

from app.application.user_memory.candidates import CandidateMemory, CandidatePorts
from app.application.user_memory.feedback import FeedbackMemory, FeedbackPorts
from app.application.user_memory.models import ActionPattern as ActionPattern
from app.application.user_memory.models import ContextSummary as ContextSummary
from app.application.user_memory.models import FeedbackRecord as FeedbackRecord
from app.application.user_memory.models import UserMemory as UserMemory
from app.application.user_memory.patterns import ActionMemory, PatternPorts
from app.application.user_memory.policy import MemoryPolicy, PolicyPorts
from app.application.user_memory.ports import MemoryAccess, MemoryStore, late_callback
from app.application.user_memory.preferences import PreferenceMemory
from app.application.user_memory.queries import MemoryQueries, QueryPorts
from app.infrastructure.user_memory.json_storage import JsonMemoryStorage
from app.infrastructure.user_memory.persistence import MemoryRepository
from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.neuro_bus.neuro_service_instrumentation import (
    instrument_service_layer_class as instrument_service_layer_class,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS
from app.utils.process_lock import exclusive_file_lock

logger = logging.getLogger(__name__)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MEMORY_DIR = os.environ.get("XCAGI_USER_MEMORY_DIR", os.path.join(BASE_DIR, "user_memory"))

JSON_MEMORY_PATH = os.environ.get(
    "XCAGI_USER_MEMORY_JSON_PATH", os.path.join(MEMORY_DIR, "memory_store.json")
)

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


class _StoreOwner(Protocol):
    _store: MemoryStore


_Owner = TypeVar("_Owner", bound=_StoreOwner)
_Args = ParamSpec("_Args")
_Return = TypeVar("_Return")


def memory_store_transaction(
    method: Callable[Concatenate[_Owner, str, _Args], _Return],
) -> Callable[Concatenate[_Owner, str, _Args], _Return]:
    """Preserve the public transaction decorator for integrations."""

    @wraps(method)
    def wrapped(self: _Owner, user_id: str, *args: _Args.args, **kwargs: _Args.kwargs) -> _Return:
        with self._store.transaction():
            return method(self, user_id, *args, **kwargs)

    return wrapped


class UserMemoryStore(MemoryRepository):
    """Legacy singleton constructor for the explicit snapshot repository."""

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
        configured_dir = os.environ.get("XCAGI_USER_MEMORY_DIR")
        memory_dir = Path(configured_dir or MEMORY_DIR)
        configured_path = os.environ.get("XCAGI_USER_MEMORY_JSON_PATH")
        path = Path(
            configured_path
            or (memory_dir / "memory_store.json" if configured_dir else JSON_MEMORY_PATH)
        )
        backend = (
            JsonMemoryStorage(
                path,
                lock=lambda: exclusive_file_lock(
                    self._lock_path, blocking=True, timeout=60, reject_symlink=True
                ),
                deserialize=lambda data: UserMemory.from_dict(data),
                temporary_id=lambda: uuid.uuid4().hex,
            )
            if storage_type == "json"
            else None
        )
        super().__init__(
            storage_type=storage_type,
            memory_path=path,
            backend=backend,
            new_memory=lambda user_id: UserMemory(user_id=user_id),
            now=lambda: datetime.now().isoformat(),
            logger=logger,
        )
        self._initialized = True


class UserMemoryService(NeuroEventPublisherMixin):
    """Stable user-memory API assembled from independently usable components."""

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
        self._store = UserMemoryStore(storage_type=storage_type)
        self._memory_v2_lock = threading.RLock()
        access = MemoryAccess(
            transaction=late_callback(lambda: self._store.transaction),
            get_memory=late_callback(lambda: self._store.get_memory),
            save_memory=late_callback(lambda: self._store.save_memory),
            new_memory=lambda user_id: UserMemory(user_id=user_id),
            now=lambda: datetime.now().isoformat(),
        )
        self._policy = MemoryPolicy(
            PolicyPorts(
                types=lambda: MEMORY_V2_TYPES,
                statuses=lambda: MEMORY_V2_STATUSES,
                blocked_sources=lambda: MEMORY_V2_BLOCKED_SOURCES,
                trusted_sources=lambda: MEMORY_V2_TRUSTED_SOURCES,
                observed_sources=lambda: MEMORY_V2_OBSERVED_SOURCES,
            )
        )
        self._preferences = PreferenceMemory(
            access, late_callback(lambda: self.get_preference), logger
        )
        self._candidates = CandidateMemory(
            access,
            CandidatePorts(
                normalize_type=late_callback(lambda: self._normalize_memory_v2_type),
                normalize_status=late_callback(lambda: self._normalize_memory_v2_status),
                fingerprint=late_callback(lambda: self._memory_v2_fingerprint),
                govern=late_callback(lambda: self._govern_memory_v2_candidate),
                find_record=late_callback(lambda: self._find_memory_v2_record),
                propose_unlocked=late_callback(lambda: self._propose_memory_candidate_unlocked),
                set_status=late_callback(lambda: self._set_memory_v2_status),
                proposal_lock=lambda: self._memory_v2_lock,
                max_records=lambda: MAX_MEMORY_V2_RECORDS,
                new_id=lambda: uuid.uuid4().hex[:12],
            ),
        )
        self._queries = MemoryQueries(
            access,
            QueryPorts(
                normalize_type=late_callback(lambda: self._normalize_memory_v2_type),
                normalize_status=late_callback(lambda: self._normalize_memory_v2_status),
                list_memories=late_callback(lambda: self.list_memories),
            ),
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

    def _normalize_memory_v2_type(self, memory_type: str) -> str:
        return self._policy.normalize_type(memory_type)

    def _normalize_memory_v2_status(self, status: str) -> str:
        return self._policy.normalize_status(status)

    def _memory_v2_fingerprint(self, memory_type: str, key: str, value: Any) -> str:
        return self._policy.fingerprint(memory_type, key, value)

    def _govern_memory_v2_candidate(
        self, *, source: str, confidence: float, evidence: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return self._policy.govern_candidate(
            source=source, confidence=confidence, evidence=evidence
        )

    def _find_memory_v2_record(
        self, memory: UserMemory, memory_id: str
    ) -> tuple[int, dict[str, Any] | None]:
        return self._policy.find_record(memory, memory_id)

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
        return self._candidates.propose(
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
        value: Any,
        *,
        source: str = "agent_observation",
        confidence: float = 0.5,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._candidates.propose_unlocked(
            user_id,
            memory_type,
            key,
            value,
            source=source,
            confidence=confidence,
            evidence=evidence,
        )

    def confirm_memory_candidate(
        self, user_id: str, memory_id: str, *, correction: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._candidates.confirm(user_id, memory_id, correction=correction)

    def reject_memory_candidate(
        self, user_id: str, memory_id: str, *, reason: str = ""
    ) -> dict[str, Any]:
        return self._candidates.reject(user_id, memory_id, reason=reason)

    def delete_memory(self, user_id: str, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._candidates.delete(user_id, memory_id, reason=reason)

    def _set_memory_v2_status(
        self, user_id: str, memory_id: str, status: str, *, reason: str = ""
    ) -> dict[str, Any]:
        return self._candidates.set_status(user_id, memory_id, status, reason=reason)

    def correct_memory(
        self,
        user_id: str,
        memory_id: str,
        *,
        value: Any | None = None,
        key: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        return self._candidates.correct(user_id, memory_id, value=value, key=key, reason=reason)

    def list_memories(
        self, user_id: str, *, status: str | None = None, memory_type: str | None = None
    ) -> list[dict[str, Any]]:
        return self._queries.list_memories(user_id, status=status, memory_type=memory_type)

    def record_memory_recall(self, user_id: str, memory_id: str) -> dict[str, Any]:
        return self._candidates.record_recall(user_id, memory_id)

    def get_memory_v2_summary(self, user_id: str) -> dict[str, Any]:
        return self._queries.get_memory_v2_summary(user_id)

    def format_memory_v2_for_prompt(
        self, user_id: str, *, max_items: int = 6, memory_type: str | None = None
    ) -> str:
        return self._queries.format_memory_v2_for_prompt(
            user_id, max_items=max_items, memory_type=memory_type
        )

    def record_action(
        self, user_id: str, intent: str, slots: dict[str, Any], message: str = ""
    ) -> None:
        self._patterns.record_action(user_id, intent, slots, message)

    def _make_pattern_key(self, intent: str, slots: dict[str, Any]) -> str:
        return self._patterns.make_pattern_key(intent, slots)

    def _save_context_summary(
        self, memory: UserMemory, intent: str, slots: dict[str, Any], message: str
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
        memory: UserMemory,
        recognized_intent: str,
        corrected_intent: str | None,
        feedback: str,
    ) -> None:
        self._feedback.adjust_pattern_weights(memory, recognized_intent, corrected_intent, feedback)

    def get_feedback_stats(self, user_id: str) -> dict[str, Any]:
        return self._feedback.get_feedback_stats(user_id)

    def get_habit_suggestions(self, user_id: str) -> list[dict[str, Any]]:
        return self._patterns.get_habit_suggestions(user_id)

    def _analyze_action_sequence(self, memory: UserMemory) -> list[dict[str, Any]]:
        return self._patterns.analyze_action_sequence(memory)

    def apply_preference_to_slots(
        self, user_id: str, intent: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        return self._preferences.apply_preference_to_slots(user_id, intent, slots)

    def get_memory_summary(self, user_id: str) -> dict[str, Any]:
        return self._queries.get_memory_summary(user_id)


_user_memory_service: UserMemoryService | None = None


def get_user_memory_service() -> UserMemoryService:
    global _user_memory_service
    if _user_memory_service is None:
        _user_memory_service = UserMemoryService()
    return _user_memory_service


def reset_user_memory_service() -> None:
    global _user_memory_service
    _user_memory_service = None
    UserMemoryService._instance = None
    UserMemoryStore._instance = None


# The old instrumentation pass saw only inherited methods and emitted no calls.
# Keep that observed behavior and method signatures while retaining _publish_event.
