"""全局多租户行级隔离：基于 SQLAlchemy ORM 事件，对继承 ``TenantScopedMixin``
的业务模型自动按当前租户过滤(读)与打标(写)。

设计要点（安全语义）——任一成立即 **完全 no-op**，确保不破坏既有部署：
- 当前租户上下文为 ``None``（桌面单租户 / 平台管理员 / 无租户后台任务）。
- 应急总开关 ``XCAGI_DISABLE_TENANT_FILTER=1``（排障 / 对照基线）。
- 逐查询逃生舱 ``session.execute(stmt, execution_options={"skip_tenant_filter": True})``。

默认 **NULL 容忍**（``tenant_id == 当前 OR IS NULL``），便于存量未打标数据平滑过渡；
``XCAGI_TENANT_STRICT=1`` 切换为严格相等。

局限：本机制只覆盖 ORM 语句（``select(Model)`` / ORM ``Query``）。直接 ``text()``
原生 SQL 不经过 ORM 事件，必须各自显式加租户作用域（见技术债清单 raw-SQL 项）。
"""

from __future__ import annotations

import os

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.mixins import TenantScopedMixin
from app.request_tenant_ctx import get_request_tenant_id

_TRUE = {"1", "true", "yes", "on"}


def tenant_filter_disabled() -> bool:
    return str(os.environ.get("XCAGI_DISABLE_TENANT_FILTER", "")).strip().lower() in _TRUE


def tenant_filter_strict() -> bool:
    return str(os.environ.get("XCAGI_TENANT_STRICT", "")).strip().lower() in _TRUE


_installed = False


def install_tenant_filter() -> None:
    """注册全局租户过滤 / 打标事件（幂等）。应在应用启动时调用一次。"""
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, "do_orm_execute")
    def _apply_tenant_read_filter(orm_execute_state: object) -> None:
        # 仅过滤主动 SELECT；放过关系/列的惰性加载与刷新，避免破坏 ORM 内部装载。
        if tenant_filter_disabled():
            return
        if not orm_execute_state.is_select:  # type: ignore[attr-defined]
            return
        if orm_execute_state.is_column_load or orm_execute_state.is_relationship_load:  # type: ignore[attr-defined]
            return
        if orm_execute_state.execution_options.get("skip_tenant_filter", False):  # type: ignore[attr-defined]
            return
        tid = get_request_tenant_id()
        if tid is None:
            return  # 无租户上下文 → no-op

        # with_loader_criteria 会分析 lambda 闭包以生成缓存键：tid 作字面量会被当作
        # 绑定参数（可缓存且按租户变化），但布尔 strict 控制的是 SQL 结构、不能作闭包
        # 变量。故按 strict 拆成两个各自只闭包 tid 的 lambda，避免缓存键报错与跨租户串缓存。
        if tenant_filter_strict():

            def _criteria(cls):  # noqa: ANN001, ANN202
                return cls.tenant_id == tid

        else:

            def _criteria(cls):  # noqa: ANN001, ANN202
                return (cls.tenant_id == tid) | (cls.tenant_id.is_(None))

        orm_execute_state.statement = orm_execute_state.statement.options(  # type: ignore[attr-defined]
            with_loader_criteria(TenantScopedMixin, _criteria, include_aliases=True)
        )

    @event.listens_for(Session, "before_flush")
    def _stamp_tenant_on_write(session: Session, flush_context: object, instances: object) -> None:
        # 新增对象若未显式带租户，则按当前租户自动打标，避免漏标导致后续读不到。
        if tenant_filter_disabled():
            return
        tid = get_request_tenant_id()
        if tid is None:
            return
        for obj in session.new:
            if isinstance(obj, TenantScopedMixin) and getattr(obj, "tenant_id", None) is None:
                obj.tenant_id = tid
