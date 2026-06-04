"""会话 / 认证 / 系统网关。"""

from __future__ import annotations

from typing import Any


def get_auth_service() -> Any:
    from app.services.auth_service import get_auth_service as _g

    return _g()


def get_session_service() -> Any:
    from app.services.session_service import get_session_service as _g

    return _g()


def get_database_service() -> Any:
    from app.utils.database_service import get_database_service as _g

    return _g()


def get_system_service() -> Any:
    from app.services.system_service import get_system_service as _g

    return _g()


__all__ = [
    "get_auth_service",
    "get_session_service",
    "get_database_service",
    "get_system_service",
]
