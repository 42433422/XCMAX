"""Own the JSON file lock and atomic replacement of serialized memory snapshots."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from app.application.user_memory.protocols import JsonObject
from app.domain.user_memory.records import UserMemory


class JsonMemoryStorage:
    def __init__(
        self,
        path: Path,
        *,
        lock: Callable[[], AbstractContextManager[None]],
        deserialize: Callable[[JsonObject], UserMemory],
        temporary_id: Callable[[], str],
    ) -> None:
        self.path = path
        self.lock = lock
        self.deserialize = deserialize
        self.temporary_id = temporary_id

    def read(self) -> dict[str, UserMemory]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        return self.decode_snapshot(data, deserialize=self.deserialize)

    @staticmethod
    def decode_snapshot(
        data: Any, *, deserialize: Callable[[JsonObject], UserMemory] = UserMemory.from_dict
    ) -> dict[str, UserMemory]:
        """Decode an already opened snapshot without creating users or writing caches."""
        if not isinstance(data, dict):
            raise ValueError("memory store must contain an object")
        return {user_id: deserialize(value) for user_id, value in data.items()}

    def write(self, memories: dict[str, UserMemory]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {user_id: memory.to_dict() for user_id, memory in memories.items()}
        temporary = self.path.with_name(f".{self.path.name}.{self.temporary_id()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        descriptor_owned = True
        try:
            stream = os.fdopen(descriptor, "w", encoding="utf-8")
            descriptor_owned = False
            with stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if descriptor_owned:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            temporary.unlink(missing_ok=True)
