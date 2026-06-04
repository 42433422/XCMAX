"""对话、偏好、Modstore 客户端网关。"""

from __future__ import annotations

from typing import Any


def get_conversation_service() -> Any:
    from app.services.conversation_service import get_conversation_service as _g

    return _g()


def get_data_analysis_service() -> Any:
    from app.services.data_analysis_service import get_data_analysis_service as _g

    return _g()


def get_user_preference_service() -> Any:
    from app.services.user_preference_service import get_user_preference_service as _g

    return _g()


def create_modstore_openai_client_from_request(*args: Any, **kwargs: Any) -> Any:
    from app.services.conversation.modstore_adapter import (
        create_modstore_openai_client_from_request as _f,
    )

    return _f(*args, **kwargs)


__all__ = [
    "get_conversation_service",
    "get_data_analysis_service",
    "get_user_preference_service",
    "create_modstore_openai_client_from_request",
]
