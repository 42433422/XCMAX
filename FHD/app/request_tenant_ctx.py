"""请求级当前租户上下文（与 ``request_active_mod_ctx`` 同构）。

被 ``app/db/tenant_filter.py`` 的全局 ORM 事件读取，用于对继承
``TenantScopedMixin`` 的业务模型按租户自动过滤(读)与打标(写)。
后台任务 / 测试可用 ``with tenant_scope(tid): ...`` 显式设定当前租户。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_tenant_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "xcagi_request_tenant_id",
    default=None,
)


def _coerce(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def set_request_tenant_id(tenant_id: object) -> contextvars.Token:
    return _tenant_id_ctx.set(_coerce(tenant_id))


def reset_request_tenant_id(token: contextvars.Token) -> None:
    _tenant_id_ctx.reset(token)


def get_request_tenant_id() -> int | None:
    return _tenant_id_ctx.get()


@contextmanager
def tenant_scope(tenant_id: object) -> Iterator[None]:
    """在代码块内将当前租户设为 ``tenant_id``（None 表示不限定 → 过滤 no-op）。"""
    token = set_request_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_request_tenant_id(token)
