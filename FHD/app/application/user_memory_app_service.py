"""Application-layer access point for the user memory service."""

from __future__ import annotations

from typing import Any


def get_user_memory_app_service() -> Any:
    """Return the shared memory service without exposing it to route modules."""
    from app.services.user_memory_service import get_user_memory_service

    return get_user_memory_service()


__all__ = ["get_user_memory_app_service"]
