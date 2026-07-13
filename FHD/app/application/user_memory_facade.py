"""Application boundary for user memory route operations."""

from __future__ import annotations

from typing import Any


def get_user_memory_service() -> Any:
    from app.services.user_memory_service import get_user_memory_service as implementation

    return implementation()


__all__ = ["get_user_memory_service"]
