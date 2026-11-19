"""Assemble the default snapshot adapter behind the memory service's store port."""

from collections.abc import Callable
from logging import Logger
from pathlib import Path

from app.application.user_memory.protocols import MemoryStore
from app.domain.user_memory.records import UserMemory
from app.infrastructure.user_memory.persistence import MemoryRepository


def create_memory_repository(
    *,
    storage_type: str,
    memory_path: Path,
    new_memory: Callable[[str], UserMemory],
    now: Callable[[], str],
    logger: Logger,
) -> MemoryStore:
    return MemoryRepository(
        storage_type=storage_type,
        memory_path=memory_path,
        backend=None,
        new_memory=new_memory,
        now=now,
        logger=logger,
    )
