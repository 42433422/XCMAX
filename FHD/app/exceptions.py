"""Compatibility exceptions used by older route modules.

The canonical hierarchy lives in :mod:`app.errors`; keeping these names in a
real module prevents source and PyInstaller builds from diverging.
"""

from __future__ import annotations

from app.errors import (
    AppError,
    AuthError,
    AuthPermissionError,
    ErrorCode,
    ValidationError,
)


class AuthenticationError(AuthError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(ErrorCode.AUTH_TOKEN_INVALID, message, detail)


class PermissionDeniedError(AuthPermissionError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(ErrorCode.AUTH_PERMISSION_DENIED, message, detail)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", detail: dict | None = None):
        super().__init__(ErrorCode.FILE_NOT_FOUND, message, status_code=404, detail=detail)


__all__ = [
    "AuthenticationError",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationError",
]
