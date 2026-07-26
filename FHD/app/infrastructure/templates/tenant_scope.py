"""模板库多租户隔离辅助（raw SQL 路径）。"""

from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    tenant_id_for_write,
    tenant_legacy_null_visible,
)

logger = logging.getLogger(__name__)


def templates_tenant_where_sql(*, table_alias: str = "") -> tuple[str, dict[str, Any]]:
    """返回 ``(sql_fragment, bind)``；无租户时 fail-closed ``1=0``。"""
    prefix = f"{table_alias}." if table_alias else ""
    tid = current_tenant_id()
    if tid is None:
        return "1 = 0", {}
    if tenant_legacy_null_visible():
        return (
            f"({prefix}tenant_id = :tenant_id OR {prefix}tenant_id IS NULL)",
            {"tenant_id": int(tid)},
        )
    return f"{prefix}tenant_id = :tenant_id", {"tenant_id": int(tid)}


def templates_tenant_id_for_insert() -> int:
    """创建模板必须打标当前租户。"""
    try:
        return int(tenant_id_for_write())
    except TenantScopeError:
        logger.warning("创建模板缺少 tenant_id 上下文")
        raise
