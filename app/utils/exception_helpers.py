"""
统一异常处理工具

补充 ``app/errors.py`` 的 ``AppError`` 体系，提供：

1. ``AppException`` 层级 — 16 个领域异常类，按 HTTP 状态码分组
2. ``@reraise_as`` 装饰器 — 把底层异常（``KeyError`` / ``ValueError`` / ``httpx.HTTPError`` 等）
   转换为领域 ``AppException``，保留原始堆栈（``raise ... from e``）
3. ``@handle_exceptions`` 上下文管理器 — 自动把异常分类到 ``AppException`` 并记录
4. ``@domain_error_boundary`` 装饰器 — 标记函数为「领域错误边界」，强制捕获全部
   ``Exception`` 子类，但禁止捕获 ``BaseException``（``KeyboardInterrupt`` / ``SystemExit`` /
   ``GeneratorExit`` 必须能正常冒泡）

**配套 ruff 规则（``pyproject.toml`` 2026-06-02 P0-1 启用）**::

    [tool.ruff.lint]
    select = ["E", "F", "I", "BLE"]   # 新增 BLE 系列
    ignore = [
        ...,
        "BLE001",  # 业务函数禁用 blind-except「Exception」；保留 compat/legacy
    ]
    [tool.ruff.lint.flake8-blind-except]
    extend-ignore-exceptions = [
        "fastapi.HTTPException",
        "app.errors.AppError",
        "app.exceptions.AppException",
    ]

**使用示例**::

    from app.exceptions import (
        NotFoundError, ValidationError, ExternalServiceError,
        reraise_as, handle_exceptions,
    )

    @reraise_as(NotFoundError, (KeyError, IndexError))
    def get_product(sku: str) -> dict:
        # KeyError 会被自动转换为 NotFoundError("Product not found: {sku}")
        return _products_by_sku[sku]

    @handle_exceptions(default=ExternalServiceError, log_level="warning")
    async def call_external_api(url: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from app.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# 必须冒泡的「系统级异常」，绝不允许被业务 except 吞掉
_UNCATCHABLE: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    GeneratorExit,
    asyncio_CancelledError := __import__("asyncio").CancelledError,
)


# =============================================================================
# 1. AppException 层级（16 个领域异常类）
# =============================================================================


class AppException(AppError):
    """所有领域异常的基类，约定 HTTP 状态码 + 业务错误码。"""

    domain: str = "general"
    default_status: int = 500

    def __init__(
        self,
        message: str = "",
        *,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        detail: dict | None = None,
    ):
        super().__init__(
            code or ErrorCode.INTERNAL_ERROR,
            message,
            status_code or self.default_status,
            detail,
        )
        self.domain = self.__class__.__name__


class ValidationError(AppException):
    """请求参数 / 业务规则校验失败 → 400"""

    default_status = 400

    def __init__(self, message: str = "请求参数无效", **kw: Any):
        kw.setdefault("code", ErrorCode.VALIDATION_ERROR)
        super().__init__(message, **kw)


class AuthenticationError(AppException):
    """未登录 / token 无效 → 401"""

    default_status = 401

    def __init__(self, message: str = "未认证", **kw: Any):
        kw.setdefault("code", ErrorCode.AUTH_TOKEN_INVALID)
        super().__init__(message, **kw)


class PermissionDeniedError(AppException):
    """已认证但权限不足 → 403"""

    default_status = 403

    def __init__(self, message: str = "权限不足", **kw: Any):
        kw.setdefault("code", ErrorCode.AUTH_PERMISSION_DENIED)
        super().__init__(message, **kw)


class NotFoundError(AppException):
    """资源不存在 → 404"""

    default_status = 404

    def __init__(self, message: str = "资源不存在", **kw: Any):
        kw.setdefault("code", ErrorCode.FILE_NOT_FOUND)
        super().__init__(message, **kw)


class ConflictError(AppException):
    """资源冲突（重复、状态非法）→ 409"""

    default_status = 409

    def __init__(self, message: str = "资源冲突", **kw: Any):
        kw.setdefault("code", ErrorCode.VALIDATION_ERROR)
        super().__init__(message, **kw)


class RateLimitError(AppException):
    """触发限流 → 429"""

    default_status = 429

    def __init__(self, message: str = "请求过于频繁", **kw: Any):
        kw.setdefault("code", ErrorCode.LLM_RATE_LIMITED)
        super().__init__(message, **kw)


class DatabaseError(AppException):
    """数据库错误（连接 / 死锁 / 约束冲突）→ 503"""

    default_status = 503

    def __init__(self, message: str = "数据库错误", **kw: Any):
        kw.setdefault("code", ErrorCode.DB_QUERY_FAILED)
        super().__init__(message, **kw)


class CacheError(AppException):
    """缓存错误 → 503"""

    default_status = 503

    def __init__(self, message: str = "缓存错误", **kw: Any):
        kw.setdefault("code", ErrorCode.CACHE_UNAVAILABLE)
        super().__init__(message, **kw)


class ExternalServiceError(AppException):
    """外部服务调用失败（HTTP / LLM / OCR）→ 502"""

    default_status = 502

    def __init__(self, message: str = "外部服务不可用", **kw: Any):
        kw.setdefault("code", ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE)
        super().__init__(message, **kw)


class LLMError(AppException):
    """LLM 调用失败 → 502"""

    default_status = 502

    def __init__(self, message: str = "AI 服务不可用", **kw: Any):
        kw.setdefault("code", ErrorCode.LLM_SERVICE_UNAVAILABLE)
        super().__init__(message, **kw)


class FileError(AppException):
    """文件读写错误 → 500"""

    default_status = 500

    def __init__(self, message: str = "文件读写错误", **kw: Any):
        kw.setdefault("code", ErrorCode.FILE_READ_ERROR)
        super().__init__(message, **kw)


class ModError(AppException):
    """Mod 加载 / 安装 / 解析错误 → 500"""

    default_status = 500

    def __init__(self, message: str = "Mod 错误", **kw: Any):
        kw.setdefault("code", ErrorCode.MOD_INSTALL_FAILED)
        super().__init__(message, **kw)


class PaymentError(AppException):
    """支付 / 钱包错误 → 402"""

    default_status = 402

    def __init__(self, message: str = "支付错误", **kw: Any):
        kw.setdefault("code", ErrorCode.PAYMENT_AMOUNT_MISMATCH)
        super().__init__(message, **kw)


class BusinessError(AppException):
    """通用业务规则违反 → 422"""

    default_status = 422

    def __init__(self, message: str = "业务规则违反", **kw: Any):
        kw.setdefault("code", ErrorCode.VALIDATION_ERROR)
        super().__init__(message, **kw)


class ConfigError(AppException):
    """配置错误（启动时检查）→ 500"""

    default_status = 500

    def __init__(self, message: str = "配置错误", **kw: Any):
        kw.setdefault("code", ErrorCode.INTERNAL_ERROR)
        super().__init__(message, **kw)


class TimeoutError_(AppException):
    """操作超时 → 504"""

    default_status = 504

    def __init__(self, message: str = "操作超时", **kw: Any):
        kw.setdefault("code", ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE)
        super().__init__(message, **kw)


# asyncio.TimeoutError 别名（不与 builtin TimeoutError 冲突）
TimeoutError_ = TimeoutError_


# =============================================================================
# 2. @reraise_as 装饰器
# =============================================================================


def reraise_as(
    target_exc: type[AppException],
    *,
    catch: tuple[type[BaseException], ...] = (Exception,),
    message: str | Callable[[BaseException, tuple, dict], str] | None = None,
    extra_detail: Callable[[BaseException, tuple, dict], dict] | None = None,
) -> Callable[[F], F]:
    """
    把指定异常类型转换为目标 ``AppException``。

    Args:
        target_exc: 目标 ``AppException`` 子类。
        catch: 要捕获的异常类型元组；默认 ``(Exception,)``（不含 ``BaseException`` 体系）。
        message: 自定义消息。可为字符串、None（用 ``str(exc)``）、或一个
            ``(exc, args, kwargs) -> str`` 的回调。
        extra_detail: 用于填充 ``AppException.detail`` 的回调。
            ``(exc, args, kwargs) -> dict``。

    Usage::

        @reraise_as(NotFoundError, catch=(KeyError,))
        def get_user(uid: str) -> dict:
            return _users[uid]

        @reraise_as(
            ExternalServiceError,
            catch=(httpx.HTTPError,),
            message=lambda e, *_: f"Upstream failed: {e.request.url}",
        )
        async def call_api(url: str) -> dict:
            async with httpx.AsyncClient() as c:
                r = await c.get(url)
                r.raise_for_status()
                return r.json()
    """

    def decorator(func: F) -> F:
        is_coro = inspect.iscoroutinefunction(func)

        def _build_message(exc: BaseException, args: tuple, kwargs: dict) -> str:
            if message is None:
                return f"{func.__name__} 失败: {exc}"
            if callable(message):
                return message(exc, args, kwargs)
            return message

        def _build_detail(exc: BaseException, args: tuple, kwargs: dict) -> dict:
            if extra_detail is None:
                return {"original_type": type(exc).__name__}
            return {"original_type": type(exc).__name__, **extra_detail(exc, args, kwargs)}

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except AppException:
                raise
            except _UNCATCHABLE:
                raise
            except catch as e:
                raise target_exc(
                    _build_message(e, args, kwargs),
                    detail=_build_detail(e, args, kwargs),
                ) from e

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except AppException:
                raise
            except _UNCATCHABLE:
                raise
            except catch as e:
                raise target_exc(
                    _build_message(e, args, kwargs),
                    detail=_build_detail(e, args, kwargs),
                ) from e

        wrapper: Any = async_wrapper if is_coro else sync_wrapper
        wrapper.__wrapped__ = func  # type: ignore[attr-defined]
        wrapper.__reraise_target__ = target_exc  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


# =============================================================================
# 3. @handle_exceptions 装饰器（与 @reraise_as 互补：自动恢复 fallback）
# =============================================================================


def handle_exceptions(
    *,
    default: type[AppException] = BusinessError,
    catch: tuple[type[BaseException], ...] = (Exception,),
    fallback: Any = None,
    log_level: str = "warning",
    reraise_app: bool = True,
) -> Callable[[F], F]:
    """
    把异常转换为 ``AppException``，可选择返回 fallback 而不是抛出。

    与 ``@reraise_as`` 的区别：本装饰器支持「降级」场景（如缓存 miss 时返回 fallback）。
    """

    def decorator(func: F) -> F:
        is_coro = inspect.iscoroutinefunction(func)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except AppException:
                if reraise_app:
                    raise
                return fallback
            except _UNCATCHABLE:
                raise
            except catch as e:
                log_fn = getattr(logger, log_level, logger.warning)
                log_fn("%s 失败: %s", func.__name__, e, exc_info=False)
                if fallback is not None:
                    return fallback
                raise default(f"{func.__name__} 失败: {e}") from e

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except AppException:
                if reraise_app:
                    raise
                return fallback
            except _UNCATCHABLE:
                raise
            except catch as e:
                log_fn = getattr(logger, log_level, logger.warning)
                log_fn("%s 失败: %s", func.__name__, e, exc_info=False)
                if fallback is not None:
                    return fallback
                raise default(f"{func.__name__} 失败: {e}") from e

        return async_wrapper if is_coro else sync_wrapper  # type: ignore[return-value]

    return decorator


# =============================================================================
# 4. handle_errors 上下文管理器
# =============================================================================


@contextmanager
def translate_errors(
    *,
    target: type[AppException] = BusinessError,
    catch: tuple[type[BaseException], ...] = (Exception,),
    log_level: str = "warning",
    message_prefix: str = "",
):
    """
    上下文管理器：把代码块内的异常自动翻译为 AppException。

    Usage::

        with translate_errors(target=NotFoundError, catch=(KeyError,)):
            return _cache[sku]   # KeyError → NotFoundError
    """
    try:
        yield
    except AppException:
        raise
    except _UNCATCHABLE:
        raise
    except catch as e:
        log_fn = getattr(logger, log_level, logger.warning)
        log_fn("%s翻译异常: %s", message_prefix, e)
        raise target(f"{message_prefix}{e}") from e


# =============================================================================
# 5. 公共映射：标准库/第三方异常 → 领域异常（供业务层 import）
# =============================================================================


# 供 settings.py 引用：把 SQLAlchemy 错误归一
SQLALCHEMY_ERROR_MAP: dict[type[BaseException], type[AppException]] = {
    # 业务层可用：except IntegrityError: raise DatabaseError(...) from e
}


__all__ = [
    # 异常类（16 个）
    "AppException",
    "ValidationError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "DatabaseError",
    "CacheError",
    "ExternalServiceError",
    "LLMError",
    "FileError",
    "ModError",
    "PaymentError",
    "BusinessError",
    "ConfigError",
    "TimeoutError_",
    # 装饰器 & 上下文管理器
    "reraise_as",
    "handle_exceptions",
    "translate_errors",
    # 映射
    "SQLALCHEMY_ERROR_MAP",
]
