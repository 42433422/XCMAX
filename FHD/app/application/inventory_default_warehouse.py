"""租户默认仓库初始化（新装 / 旧版升级后没有仓库时的显式初始化）。

背景：销售闭环发货按 ``current_tenant_default`` 解析仓库，要求当前租户至少有
一个 active 仓库；而新装库与从旧版升级的库都不会自带仓库，桌面「库存管理」
页也没有建仓入口，用户只会看到「当前租户下无可用仓库」。

本模块只做一件事：在 **当前租户** 下幂等地确保存在一个 active 仓库。

- 已有任一 active 仓库 → 原样返回，不新建；
- 本租户的默认仓库曾被软删除 → 重新启用；
- 否则新建 ``默认仓库``，编码带租户号（``warehouses.code`` 全局唯一）。

租户隔离：调用方必须给出明确的 ``tenant_id``；所有读写都在 ``tenant_scope``
内进行，新仓库显式打标该租户，绝不复用或改写其他租户的仓库。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.db.models import Warehouse
from app.infrastructure.tenant_scope import tenant_scope

DEFAULT_WAREHOUSE_NAME = "默认仓库"


def default_warehouse_code(tenant_id: int) -> str:
    return f"WH-T{int(tenant_id)}-DEFAULT"


def _code_taken_globally(db: Any, code: str) -> bool:
    row = db.execute(
        Warehouse.__table__.select().where(Warehouse.__table__.c.code == code).limit(1),
        execution_options={"skip_tenant_filter": True},
    ).first()
    return row is not None


def ensure_default_warehouse(db: Any, tenant_id: int) -> tuple[Any, bool]:
    """确保 ``tenant_id`` 至少有一个 active 仓库；返回 ``(仓库, 是否本次新建或重新启用)``。

    只 ``flush`` 不 ``commit``，由调用方决定事务边界。
    """
    if tenant_id is None:
        raise ValueError("初始化仓库必须指定租户")
    tid = int(tenant_id)
    with tenant_scope(tid):
        existing = (
            db.query(Warehouse)
            .filter(Warehouse.status == "active", Warehouse.tenant_id == tid)
            .order_by(Warehouse.id.asc())
            .first()
        )
        if existing is not None:
            return existing, False
        code = default_warehouse_code(tid)
        previous = (
            db.query(Warehouse).filter(Warehouse.code == code, Warehouse.tenant_id == tid).first()
        )
        if previous is not None:
            previous.status = "active"
            previous.updated_at = datetime.now()
            db.flush()
            return previous, True
        if _code_taken_globally(db, code):
            code = f"{code}-{uuid.uuid4().hex[:6].upper()}"
        warehouse = Warehouse(
            code=code,
            name=DEFAULT_WAREHOUSE_NAME,
            type="normal",
            status="active",
            tenant_id=tid,
            created_at=datetime.now(),
        )
        db.add(warehouse)
        db.flush()
        return warehouse, True


def warehouse_setup_status(db: Any, tenant_id: int) -> dict[str, Any]:
    """当前租户的仓库初始化状态（只读）。"""
    tid = int(tenant_id)
    with tenant_scope(tid):
        active = (
            db.query(Warehouse)
            .filter(Warehouse.status == "active", Warehouse.tenant_id == tid)
            .count()
        )
    return {"initialized": active > 0, "active_warehouses": int(active)}


__all__ = [
    "DEFAULT_WAREHOUSE_NAME",
    "default_warehouse_code",
    "ensure_default_warehouse",
    "warehouse_setup_status",
]
