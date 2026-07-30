from __future__ import annotations

from typing import Any


def get_conversation_service(*args: Any, **kwargs: Any) -> Any:
    from app.services.conversation_service import get_conversation_service as _get

    return _get(*args, **kwargs)


def get_data_analysis_service(*args: Any, **kwargs: Any) -> Any:
    from app.services.data_analysis_service import get_data_analysis_service as _get

    return _get(*args, **kwargs)


def get_user_preference_service(*args: Any, **kwargs: Any) -> Any:
    from app.services.user_preference_service import get_user_preference_service as _get

    return _get(*args, **kwargs)


__all__ = [
    "get_conversation_service",
    "get_data_analysis_service",
    "get_user_preference_service",
]
