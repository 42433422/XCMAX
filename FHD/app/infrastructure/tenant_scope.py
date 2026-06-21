"""多租户作用域：集中式 tenant_id 读取与查询过滤。

单一真相源 + 自动派生（账号体系 · 租户数据隔离）：
- 真相源：``User.tenant_id``（登录用户所属租户）
- 派生：登录请求由 IndustryContextMiddleware 注入 ``request.state.tenant_id``；
  仓储层用 ``apply_tenant_filter`` 自动按租户过滤业务查询。

安全策略（避免存量数据被隐藏）：
- 默认 **NULL 容忍**：``tenant_id == 当前租户 OR tenant_id IS NULL``，
  存量未打标数据对所有租户可见，新数据按租户隔离。
- ``XCAGI_TENANT_STRICT=1`` 切换为严格相等（数据回填完成后启用）。
- 当前租户为 None（管理员 / 未登录 / 无租户）时不过滤 —— 看全部。

后台任务（无请求上下文）用 ``with tenant_scope(tid): ...`` 显式设定租户。
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_current_tenant_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)


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
    """是否启用严格租户过滤（默认 NULL 容忍）。"""
    return (os.environ.get("XCAGI_TENANT_STRICT") or "").strip().lower() in ("1", "true", "yes")


def apply_tenant_filter(query: Any, model: Any, *, tenant_id: int | None = None) -> Any:
    """给 SQLAlchemy query 追加租户过滤。

    - model 无 ``tenant_id`` 列 → 原样返回（不支持隔离的表）。
    - 当前租户为 None → 原样返回（管理员看全部）。
    - 默认 NULL 容忍；``XCAGI_TENANT_STRICT=1`` 时严格相等。
    """
    column = getattr(model, "tenant_id", None)
    if column is None:
        return query
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    if tid is None:
        return query
    if tenant_strict_mode():
        return query.filter(column == tid)
    return query.filter((column == tid) | (column.is_(None)))


def tenant_id_for_write(tenant_id: int | None = None) -> int | None:
    """写入业务数据时应打标的租户 id（当前租户；可显式覆盖）。"""
    return tenant_id if tenant_id is not None else current_tenant_id()


__all__ = [
    "apply_tenant_filter",
    "current_tenant_id",
    "reset_current_tenant_id",
    "set_current_tenant_id",
    "tenant_id_for_write",
    "tenant_scope",
    "tenant_strict_mode",
]
