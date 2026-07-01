"""产品主数据只读查询辅助。

Phase 3B 从 ``app.legacy.product_db_read`` 吸收。
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import inspect, text

from app.infrastructure.db.sync_engine import get_read_sync_engine, get_sync_engine
from app.infrastructure.tenant_scope import append_tenant_scope_where


def _read_engine():
    if (os.environ.get("DATABASE_READ_URL") or "").strip():
        return get_read_sync_engine()
    return get_sync_engine()


def find_matching_customer_unified(customer_name: str) -> str | None:
    name = (customer_name or "").strip()
    if not name:
        return None
    return name


def load_products_for_price_list_by_customer(customer_name: str, _ctx: Any) -> list[dict[str, Any]]:
    eng = _read_engine()
    insp = inspect(eng)
    if "products" not in insp.get_table_names():
        return []
    col_names = {c["name"] for c in insp.get_columns("products")}
    where_parts = ["unit = :u"]
    bind: dict[str, object] = {"u": customer_name}
    append_tenant_scope_where(where_parts, bind, col_names, table_name="products")
    with eng.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT model_number, name, specification, unit, price FROM products "
                    "WHERE " + " AND ".join(where_parts) + " ORDER BY id LIMIT 200"
                ),
                bind,
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def load_products_price_table_rows(customer_name: str) -> list[dict[str, Any]]:
    return load_products_for_price_list_by_customer(customer_name, None)


__all__ = [
    "find_matching_customer_unified",
    "load_products_for_price_list_by_customer",
    "load_products_price_table_rows",
]
