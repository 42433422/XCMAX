"""模板库多租户隔离辅助（raw SQL 路径）。"""

from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    tenant_id_for_write,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def ensure_templates_tenant_column() -> None:
    """幂等补齐 templates.tenant_id（SQLite / PG）。"""
    try:
        from app.db.init_db import ensure_business_tenant_id_columns

        ensure_business_tenant_id_columns()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("补齐 templates.tenant_id 失败: %s", exc)


def templates_tenant_where_sql(*, table_alias: str = "") -> tuple[str, dict[str, Any]]:
    """返回 ``(sql_fragment, bind)``。

    约定：``tenant_id IS NULL`` 表示系统/开箱种子，对所有上下文可见；
    租户私有模板仅本租户可见。无租户时只暴露系统模板，不泄露任何租户数据。
    """
    prefix = f"{table_alias}." if table_alias else ""
    tid = current_tenant_id()
    if tid is None:
        return f"{prefix}tenant_id IS NULL", {}
    return (
        f"({prefix}tenant_id = :tenant_id OR {prefix}tenant_id IS NULL)",
        {"tenant_id": int(tid)},
    )


def templates_tenant_id_for_insert() -> int:
    """创建模板必须打标当前租户。"""
    ensure_templates_tenant_column()
    try:
        return int(tenant_id_for_write())
    except TenantScopeError:
        logger.warning("创建模板缺少 tenant_id 上下文")
        raise
