"""Structured error codes for the FHD platform.

Replaces bare ``except Exception`` with domain-specific error types,
enabling precise frontend UI responses and alerting.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
    AUTH_PERMISSION_DENIED = "AUTH_PERMISSION_DENIED"
    PAYMENT_ORDER_NOT_FOUND = "PAYMENT_ORDER_NOT_FOUND"
    PAYMENT_AMOUNT_MISMATCH = "PAYMENT_AMOUNT_MISMATCH"
    PAYMENT_WALLET_INSUFFICIENT_BALANCE = "PAYMENT_WALLET_INSUFFICIENT_BALANCE"
    PAYMENT_WALLET_RECHARGE_BLOCKED = "PAYMENT_WALLET_RECHARGE_BLOCKED"
    PAYMENT_ORDER_ALREADY_REFUNDED = "PAYMENT_ORDER_ALREADY_REFUNDED"
    DB_CONNECTION_FAILED = "DB_CONNECTION_FAILED"
    DB_QUERY_FAILED = "DB_QUERY_FAILED"
    DB_TABLE_NOT_FOUND = "DB_TABLE_NOT_FOUND"
    DB_LOCK_ERROR = "DB_LOCK_ERROR"
    DB_FOREIGN_KEY_VIOLATION = "DB_FOREIGN_KEY_VIOLATION"
    LLM_SERVICE_UNAVAILABLE = "LLM_SERVICE_UNAVAILABLE"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_READ_ERROR = "FILE_READ_ERROR"
    FILE_WRITE_ERROR = "FILE_WRITE_ERROR"
    MOD_NOT_FOUND = "MOD_NOT_FOUND"
    MOD_INSTALL_FAILED = "MOD_INSTALL_FAILED"
    MOD_SIGNATURE_ERROR = "MOD_SIGNATURE_ERROR"
    MOD_ACCESS_DENIED = "MOD_ACCESS_DENIED"
    WORKFLOW_ERROR = "WORKFLOW_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    CACHE_UNAVAILABLE = "CACHE_UNAVAILABLE"
    EXTERNAL_SERVICE_UNAVAILABLE = "EXTERNAL_SERVICE_UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Structured application error with error code and HTTP status."""

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        status_code: int = 500,
        detail: dict | None = None,
    ):
        self.code = code
        self.message = message or code.value
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(self.message)

    def to_dict(self, *, request_id: str = "") -> dict:
        return {
            "success": False,
            "error_code": self.code.value,
            "message": self.message,
            "request_id": request_id,
            **self.detail,
        }


class AuthError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.AUTH_TOKEN_INVALID,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=401, detail=detail)


class AuthPermissionError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.AUTH_PERMISSION_DENIED,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=403, detail=detail)


# Backward-compatible alias (avoid shadowing builtin when importing selectively).
PermissionError = AuthPermissionError


class PaymentError(AppError):
    def __init__(
        self, code: ErrorCode, message: str = "", status_code: int = 400, detail: dict | None = None
    ):
        super().__init__(code, message, status_code=status_code, detail=detail)


class DatabaseError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.DB_QUERY_FAILED,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=503, detail=detail)


class DatabaseLockError(DatabaseError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(ErrorCode.DB_LOCK_ERROR, message or "Database is busy", detail=detail)


class ForeignKeyViolationError(DatabaseError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(
            ErrorCode.DB_FOREIGN_KEY_VIOLATION,
            message or "Data integrity error",
            detail=detail,
        )


class LLMError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.LLM_SERVICE_UNAVAILABLE,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=503, detail=detail)


class ModError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.MOD_NOT_FOUND,
        message: str = "",
        status_code: int = 404,
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=status_code, detail=detail)


class ModNotFoundError(ModError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(ErrorCode.MOD_NOT_FOUND, message or "Mod not found", detail=detail)


class ModInstallFailedError(ModError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(
            ErrorCode.MOD_INSTALL_FAILED,
            message or "Mod install failed",
            status_code=400,
            detail=detail,
        )


class ModSignatureError(ModError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(
            ErrorCode.MOD_SIGNATURE_ERROR,
            message or "Mod signature invalid",
            status_code=400,
            detail=detail,
        )


class ModAccessDeniedError(ModError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(
            ErrorCode.MOD_ACCESS_DENIED,
            message or "Mod access denied",
            status_code=403,
            detail=detail,
        )


class WorkflowError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.WORKFLOW_ERROR,
        message: str = "",
        status_code: int = 400,
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=status_code, detail=detail)


class ToolExecutionError(WorkflowError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(
            ErrorCode.TOOL_EXECUTION_ERROR,
            message or "Tool execution failed",
            detail=detail,
        )


class DataValidationError(WorkflowError):
    def __init__(self, message: str = "", detail: dict | None = None):
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            message or "Validation error",
            detail=detail,
        )


class ServiceUnavailableError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=503, detail=detail)


class ExternalServiceError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
        message: str = "",
        status_code: int = 503,
        detail: dict | None = None,
    ):
        super().__init__(code, message, status_code=status_code, detail=detail)


class ValidationError(AppError):
    def __init__(
        self,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, status_code=422, detail=detail)


class CacheError(AppError):
    def __init__(
        self,
        message: str = "",
        detail: dict | None = None,
    ):
        super().__init__(ErrorCode.CACHE_UNAVAILABLE, message, status_code=503, detail=detail)
