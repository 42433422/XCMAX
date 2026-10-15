"""全局多租户 ORM 过滤：对继承 ``TenantScopedMixin`` 的业务模型自动隔离。

机制（注册在 SQLAlchemy 基类 ``Session`` 上，全进程生效）：
- 读（``do_orm_execute`` SELECT）：``with_loader_criteria`` 注入 tenant 条件，
  自动覆盖主查询、JOIN 与关系加载。
- 写（``before_flush``）：新对象未显式设 tenant_id 时自动打标当前租户。

安全：
- ``User`` / ``Session`` 等不继承 mixin → 永不被过滤（登录 / 会话校验不受影响）。
- 当前租户为 None → fail-closed，业务模型读空，业务写入拒绝。
- 默认严格相等；``XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE=1`` 仅迁移期允许 NULL 旧数据可见。
- 逃生舱：``session.execute(stmt, execution_options={"skip_tenant_filter": True})``。
"""

from __future__ import annotations

import os

from sqlalchemy import event, false, or_
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.mixins import TenantScopedMixin
from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    tenant_legacy_null_visible,
)

_INSTALLED = False


def install_tenant_filter() -> None:
    """安装全局租户过滤事件（幂等）。

    应急开关：设 ``XCAGI_DISABLE_TENANT_FILTER=1`` 可完全禁用（不安装事件）。
    """
    global _INSTALLED
    if _INSTALLED or (os.environ.get("XCAGI_DISABLE_TENANT_FILTER") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    _INSTALLED = True

    @event.listens_for(Session, "do_orm_execute")
    def _tenant_read_filter(execute_state):  # noqa: ANN001
        if not execute_state.is_select:
            return
        if execute_state.execution_options.get("skip_tenant_filter"):
            return
        tid = current_tenant_id()
        if tid is None:
            criteria = lambda cls: false()
        elif tenant_legacy_null_visible():
            criteria = lambda cls: or_(cls.tenant_id == tid, cls.tenant_id.is_(None))
        else:
            criteria = lambda cls: cls.tenant_id == tid
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(TenantScopedMixin, criteria, include_aliases=True)
        )

    @event.listens_for(Session, "before_flush")
    def _tenant_write_tag(session, flush_context, instances):  # noqa: ANN001
        tid = current_tenant_id()
        for obj in session.new:
            if isinstance(obj, TenantScopedMixin) and getattr(obj, "tenant_id", None) is None:
                if tid is None:
                    if (
                        os.environ.get("XCAGI_TENANT_ALLOW_UNSCOPED_WRITE") or ""
                    ).strip().lower() in (
                        "1",
                        "true",
                        "yes",
                        "on",
                    ):
                        continue
                    raise TenantScopeError(f"{obj.__class__.__name__} 写入缺少 tenant_id，已拒绝")
                obj.tenant_id = tid


# 模块导入即安装（models/__init__ 在所有模型映射后导入本模块）。
install_tenant_filter()

__all__ = ["install_tenant_filter"]
