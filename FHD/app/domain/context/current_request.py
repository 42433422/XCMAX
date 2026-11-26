"""当前请求的 ContextVar 存储（请求级隔离）。

供中间件在 dispatch 时 set，业务层（如 value_objects_industry）在无 Request
参数的旧代码路径中 get，实现"当前请求"的隐式传递。

本模块是纯粹的"请求上下文持有器"，无任何基础设施依赖，故落于 domain 层；
``app.infrastructure.request_context.current_request`` 保留向后兼容 re-export。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

from starlette.requests import Request

_current_request_ctx: contextvars.ContextVar[Optional[Request]] = contextvars.ContextVar(
    "xcagi_current_request",
    default=None,
)


def set_current_request(request: Request | None):
    """设置或清空当前请求到 ContextVar，返回 token 用于复位。"""
    return _current_request_ctx.set(request)


def reset_current_request(token) -> None:
    """复位当前请求 ContextVar 到上一个值。"""
    _current_request_ctx.reset(token)


def get_current_request() -> Optional[Request]:
    """获取当前请求；无请求上下文时返回 None。"""
    return _current_request_ctx.get()


_current_tenant_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)


_owned_tenant_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "owned_business_tenant", default=None
)


class TenantScopeError(RuntimeError):
    """业务数据读写缺少租户上下文。"""


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
    owned = owned_tenant_id()
    if owned is not None:
        return owned
    tid = _current_tenant_id.get()
    if tid is not None:
        return tid
    try:
        request = get_current_request()
        if request is not None:
            value = getattr(request.state, "tenant_id", None)
            return int(value) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None
    return None


@contextmanager
def tenant_scope(tenant_id: int | None) -> Iterator[None]:
    """临时设定当前租户（后台任务 / 跨上下文调用）。"""
    token = set_current_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_current_tenant_id(token)


def owned_tenant_id() -> int | None:
    """Internal scope, established only after server actor/permission validation."""
    return _owned_tenant_id.get()


@contextmanager
def owned_tenant_scope(tenant_id: int) -> Iterator[None]:
    """Strict owned rows only; never exposes/adopts migration NULL rows.

    This is not authorization. The caller must validate the authenticated actor.
    ORM flush ownership is checked separately; arbitrary raw/bulk DML is not covered.
    """
    if type(tenant_id) is not int or tenant_id <= 0:
        raise TenantScopeError("已授权企业范围无效")
    token = _owned_tenant_id.set(tenant_id)
    try:
        with tenant_scope(tenant_id):
            yield
    finally:
        _owned_tenant_id.reset(token)


__all__ = [
    "get_current_request",
    "reset_current_request",
    "set_current_request",
]
