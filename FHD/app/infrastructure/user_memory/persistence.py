"""Serialize updates and isolate callers from the repository's mutable user cache."""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from app.infrastructure.user_memory.json_storage import JsonMemoryStorage
from app.application.user_memory.models import UserMemory
from app.utils.operational_errors import RECOVERABLE_ERRORS


class MemoryRepository:
    def __init__(
        self,
        *,
        storage_type: str,
        memory_path: Path,
        backend: JsonMemoryStorage | None,
        new_memory: Callable[[str], UserMemory],
        now: Callable[[], str],
        logger: logging.Logger,
    ) -> None:
        self.storage_type = storage_type
        self._memory_path = memory_path
        self._lock_path = memory_path.with_name(f"{memory_path.name}.lock")
        self._backend = backend
        self._new_memory = new_memory
        self._now = now
        self._logger = logger
        self._transaction_lock = threading.RLock()
        self._transaction_state = threading.local()
        self._memory_cache: dict[str, UserMemory] = {}
        self._load_all_memories()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if getattr(self._transaction_state, "depth", 0):
            yield
            return
        with self._transaction_lock:
            if self._backend is not None:
                with self._backend.lock():
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
        self._memory_cache.clear()
        if self._backend is not None:
            try:
                self._memory_cache.update(self._backend.read())
                self._logger.info(
                    "从 %s 加载了 %s 个用户记忆", self._memory_path, len(self._memory_cache)
                )
            except RECOVERABLE_ERRORS as exc:
                self._memory_cache.clear()
                if strict:
                    raise
                self._logger.error("加载用户记忆失败: %s", exc)

    def _save_all_memories(self) -> None:
        if self._backend is None:
            return
        with self.transaction():
            self._backend.write(self._memory_cache)
            self._logger.debug(
                "已保存 %s 个用户记忆到 %s", len(self._memory_cache), self._memory_path
            )

    def get_memory(self, user_id: str) -> UserMemory | None:
        with self.transaction():
            if user_id not in self._memory_cache:
                self._memory_cache[user_id] = self._new_memory(user_id)
            return copy.deepcopy(self._memory_cache[user_id])

    def save_memory(self, user_id: str, memory: UserMemory) -> None:
        with self.transaction():
            memory.updated_at = self._now()
            self._memory_cache[user_id] = copy.deepcopy(memory)
            self._save_all_memories()

    def save_legacy_memory(
        self, user_id: str, memory: UserMemory, persist: Callable[[], None]
    ) -> None:
        """Save v1 fields without letting a legacy snapshot replace governed records."""
        with self.transaction():
            memory.updated_at = self._now()
            snapshot = copy.deepcopy(memory)
            current = self._memory_cache.get(user_id)
            if current is not None:
                snapshot.memory_v2_records = copy.deepcopy(current.memory_v2_records)
            self._memory_cache[user_id] = snapshot
            persist()
