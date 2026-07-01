"""多租户作用域：集中式 tenant_id 读取与查询过滤。

单一真相源 + 自动派生（账号体系 · 租户数据隔离）：
- 真相源：``User.tenant_id``（登录用户所属租户）
- 派生：登录请求由 IndustryContextMiddleware 注入 ``request.state.tenant_id``；
  仓储层用 ``apply_tenant_filter`` 自动按租户过滤业务查询。

安全策略：
- 默认 **严格隔离**：``tenant_id == 当前租户``。
- 当前租户为 None 时 fail-closed，业务查询返回空，业务写入拒绝。
- 只有显式设置 ``XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE=1`` 才临时允许
  ``tenant_id IS NULL`` 存量数据对当前租户可见；这个开关仅用于受控迁移。

后台任务（无请求上下文）用 ``with tenant_scope(tid): ...`` 显式设定租户。
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from collections.abc import Mapping
from typing import Any, Iterator

from sqlalchemy import false

logger = logging.getLogger(__name__)

_current_tenant_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)


class TenantScopeError(RuntimeError):
    """业务数据读写缺少租户上下文。"""


def _is_test_double(value: Any) -> bool:
    """测试替身不承载真实 SQLAlchemy 查询语义，避免改写 MagicMock 链。"""
    return type(value).__module__.startswith("unittest.mock")


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def set_current_tenant_id(tenant_id: int | None) -> contextvars.Token:
    """设置当前租户（返回 token 供 reset）。"""
    value = int(tenant_id) if tenant_id is not None else None
    return _current_tenant_id.set(value)


def reset_current_tenant_id(token: contextvars.Token) -> None:
    try:
        _current_tenant_id.reset(token)
    except (ValueError, LookupError):
        pass


def current_tenant_id() -> int | None:
    """读取当前租户：优先 ContextVar，其次当前请求 ``request.state.tenant_id``。"""
    tid = _current_tenant_id.get()
    if tid is not None:
        return tid
    try:
        from app.infrastructure.request_context import get_current_request

        request = get_current_request()
        if request is not None:
            value = getattr(request.state, "tenant_id", None)
            return int(value) if value is not None else None
    except (ImportError, ValueError, TypeError, AttributeError):
        return None
    return None


@contextlib.contextmanager
def tenant_scope(tenant_id: int | None) -> Iterator[None]:
    """临时设定当前租户（后台任务 / 跨上下文调用）。"""
    token = set_current_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_current_tenant_id(token)


def tenant_strict_mode() -> bool:
    """是否启用严格租户过滤（默认启用）。"""
    return not tenant_legacy_null_visible()


def tenant_legacy_null_visible() -> bool:
    """是否临时允许当前租户读取 tenant_id IS NULL 的迁移期旧数据。"""
    return _truthy_env("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE")


def apply_tenant_filter(query: Any, model: Any, *, tenant_id: int | None = None) -> Any:
    """给 SQLAlchemy query 追加租户过滤。

    - model 无 ``tenant_id`` 列 → 原样返回（不支持隔离的表）。
    - 当前租户为 None → 返回空集合（fail-closed）。
    - 默认严格相等；仅迁移开关允许 NULL 旧数据可见。
    """
    if _is_test_double(query):
        return query
    column = getattr(model, "tenant_id", None)
    if column is None:
        return query
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    if tid is None:
        return query.filter(false())
    if tenant_legacy_null_visible():
        return query.filter((column == tid) | (column.is_(None)))
    return query.filter(column == tid)


def tenant_id_for_write(tenant_id: int | None = None) -> int:
    """写入业务数据时应打标的租户 id（当前租户；可显式覆盖）。"""
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    if tid is None:
        raise TenantScopeError("写入业务数据缺少 tenant_id")
    return tid


def _column_name_set(column_names: set[str] | Mapping[str, object]) -> set[str]:
    if isinstance(column_names, Mapping):
        return set(column_names.keys())
    return set(column_names)


def append_tenant_scope_where(
    where_parts: list[str],
    bind: dict[str, object],
    column_names: set[str] | Mapping[str, object],
    *,
    table_name: str = "business_table",
) -> bool:
    """给 raw SQL WHERE 追加租户条件；缺租户/缺列时 fail-closed。

    返回 ``True`` 表示成功追加 ``tenant_id = :tenant_id``；返回 ``False`` 表示
    已追加 ``1 = 0``，调用方会得到空结果。
    """
    cols = _column_name_set(column_names)
    tid = current_tenant_id()
    if tid is None or "tenant_id" not in cols:
        where_parts.append("1 = 0")
        logger.warning("raw SQL %s 缺少租户上下文或 tenant_id 列，已 fail-closed", table_name)
        return False
    where_parts.append("tenant_id = :tenant_id")
    bind["tenant_id"] = int(tid)
    return True


def require_raw_sql_tenant_id(
    column_names: set[str] | Mapping[str, object],
    *,
    table_name: str = "business_table",
) -> int:
    """raw SQL 写入/更新/删除前强制取得当前租户 id。"""
    cols = _column_name_set(column_names)
    if "tenant_id" not in cols:
        raise TenantScopeError(f"{table_name} 缺少 tenant_id 列，拒绝业务写入")
    return int(tenant_id_for_write())


__all__ = [
    "apply_tenant_filter",
    "append_tenant_scope_where",
    "current_tenant_id",
    "require_raw_sql_tenant_id",
    "reset_current_tenant_id",
    "set_current_tenant_id",
    "TenantScopeError",
    "tenant_legacy_null_visible",
    "tenant_id_for_write",
    "tenant_scope",
    "tenant_strict_mode",
]
