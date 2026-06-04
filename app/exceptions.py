"""
app.exceptions — 公开导出层

向后兼容 ``app.errors``，并暴露新的领域异常层级。生产代码应从此处 import：

    from app.exceptions import NotFoundError, reraise_as

而非：

    from app.errors import ErrorCode  # OK；ErrorCode 仍在 app/errors.py
"""

from app.errors import AppError, AuthError, DatabaseError, ErrorCode, LLMError, PaymentError, PermissionError
from app.utils.exception_helpers import (
    AppException,
    AuthenticationError,
    BusinessError,
    CacheError,
    ConfigError,
    ConflictError,
    DatabaseError as DatabaseDomainError,
    ExternalServiceError,
    FileError,
    LLMError as LLMDomainError,
    ModError,
    NotFoundError,
    PaymentError as PaymentDomainError,
    PermissionDeniedError,
    RateLimitError,
    TimeoutError_,
    ValidationError,
    handle_exceptions,
    reraise_as,
    translate_errors,
)

__all__ = [
    # 来自 app/errors.py（保留向后兼容）
    "AppError",
    "AuthError",
    "DatabaseError",
    "LLMError",
    "PaymentError",
    "PermissionError",
    "ErrorCode",
    # 来自 app/utils/exception_helpers.py（推荐新代码使用）
    "AppException",
    "ValidationError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "DatabaseDomainError",
    "CacheError",
    "ExternalServiceError",
    "LLMDomainError",
    "FileError",
    "ModError",
    "PaymentDomainError",
    "BusinessError",
    "ConfigError",
    "TimeoutError_",
    # 工具
    "reraise_as",
    "handle_exceptions",
    "translate_errors",
]
