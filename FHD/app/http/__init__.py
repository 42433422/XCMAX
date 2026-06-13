"""与框架无关的 HTTP 小工具（JSON 响应、错误码信封等）。"""

from app.http.error_codes import (
    BATCH_LIMIT_EXCEEDED,
    EMPTY_MESSAGE,
    FORBIDDEN,
    INTERNAL_ERROR,
    NOT_FOUND,
    UNAUTHORIZED,
    VALIDATION_ERROR,
    WEAK_PASSWORD,
    error_envelope,
)

__all__ = [
    "BATCH_LIMIT_EXCEEDED",
    "EMPTY_MESSAGE",
    "FORBIDDEN",
    "INTERNAL_ERROR",
    "NOT_FOUND",
    "UNAUTHORIZED",
    "VALIDATION_ERROR",
    "WEAK_PASSWORD",
    "error_envelope",
]
