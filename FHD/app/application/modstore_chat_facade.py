"""Application boundary for MODstore-backed chat client creation."""

from __future__ import annotations

from typing import Any


def create_modstore_openai_client_from_request(*args: Any, **kwargs: Any) -> Any:
    from app.services.conversation.modstore_adapter import (
        create_modstore_openai_client_from_request as implementation,
    )

    return implementation(*args, **kwargs)


__all__ = ["create_modstore_openai_client_from_request"]
