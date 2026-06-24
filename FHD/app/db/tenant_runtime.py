"""后台 / 员工任务的租户上下文助手（按 user_id 解析租户并设入上下文）。

员工 loops、定时任务等在无 HTTP 请求中间件的环境运行，默认不带租户上下文，
会绕过全局租户过滤（读全部、写打标为 NULL）。在这些入口用
``with tenant_scope_for_user_id(user_id): ...`` 包裹，可让"代某租户干活"的任务
正确隔离；user_id 为 0/解析不到时 no-op（平台级任务保持无上下文）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.request_tenant_ctx import reset_request_tenant_id, set_request_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS


def resolve_tenant_id_for_user_id(user_id: object, *, session_factory: object = None) -> int | None:
    """按 user_id 查 ``users.tenant_id``；失败/缺用户/平台账号 → None。

    ``session_factory`` 仅供测试注入；生产默认用宿主基库会话。
    """
    if not user_id:
        return None
    try:
        if session_factory is None:
            from app.db import HostSessionLocal

            session_factory = HostSessionLocal
        from app.db.models.user import User

        with session_factory() as s:  # type: ignore[operator]
            user = s.get(User, int(user_id))
            tid = getattr(user, "tenant_id", None) if user is not None else None
            return int(tid) if tid is not None else None
    except RECOVERABLE_ERRORS:
        return None


@contextmanager
def tenant_scope_for_user_id(user_id: object, *, session_factory: object = None) -> Iterator[None]:
    """将当前租户设为 user_id 所属租户；解析不到则 no-op（不阻断任务）。"""
    tid = resolve_tenant_id_for_user_id(user_id, session_factory=session_factory)
    token = set_request_tenant_id(tid) if tid is not None else None
    try:
        yield
    finally:
        if token is not None:
            reset_request_tenant_id(token)
