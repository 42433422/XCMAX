"""Product write operations for the compatibility persistence facade."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from app.infrastructure.persistence.compat_db.base import _sql_ident, _sql_insert_returning


def _compat_module() -> Any:
    # Resolve lazily so legacy tests and integrations patching the facade keep
    # controlling the dependencies used by these extracted implementations.
    from app.infrastructure.persistence.compat_db import writes

    return writes


def products_pg_col_names() -> set[str]:
    compat = _compat_module()
    engine = compat.get_sync_engine()
    inspector = compat.inspect(engine)
    return {column["name"] for column in inspector.get_columns("products")}


def products_pg_update_row(
    pid: int,
    body: dict,
    *,
    parse_price,
    parse_quantity,
    parse_is_active,
) -> None:
    compat = _compat_module()
    engine = compat.get_sync_engine()
    column_names = compat._products_pg_col_names()
    if not {"id", "model_number", "name"}.issubset(column_names):
        raise HTTPException(
            status_code=503,
            detail="products 表缺少必要列（至少需要 id、model_number、name）。",
        )
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="产品名称不能为空")
    sets: list[str] = []
    params: dict[str, object] = {"pid": pid}
    if "model_number" in column_names:
        model_number = body.get("model_number")
        sets.append("model_number = :model_number")
        params["model_number"] = (str(model_number).strip() if model_number is not None else "")[
            :120
        ]
    sets.append("name = :name")
    params["name"] = name[:500]
    if "specification" in column_names:
        specification = body.get("specification")
        sets.append("specification = :specification")
        params["specification"] = None if specification is None else str(specification)
    if "price" in column_names:
        sets.append("price = :price")
        params["price"] = parse_price(body.get("price"))
    if "quantity" in column_names:
        sets.append("quantity = :quantity")
        params["quantity"] = parse_quantity(body.get("quantity"))
    if "unit" in column_names:
        unit = body.get("unit")
        sets.append("unit = :unit")
        params["unit"] = (str(unit).strip() if unit is not None else "")[:200]
    if "description" in column_names:
        description = body.get("description")
        sets.append("description = :description")
        params["description"] = None if description is None else str(description)
    if "category" in column_names:
        category = body.get("category")
        sets.append("category = :category")
        params["category"] = None if category is None else str(category)[:200]
    if "brand" in column_names:
        brand = body.get("brand")
        sets.append("brand = :brand")
        params["brand"] = None if brand is None else str(brand)[:200]
    if "is_active" in column_names:
        is_active = parse_is_active(body.get("is_active"))
        if is_active is not None:
            sets.append("is_active = :is_active")
            params["is_active"] = is_active
    if "updated_at" in column_names:
        sets.append("updated_at = NOW()")
    if not sets:
        raise HTTPException(status_code=400, detail="没有可更新的列")
    params["tenant_id"] = compat._require_tenant_id_or_raise(column_names, table_name="products")
    mod_and = compat.products_update_or_delete_mod_and(column_names, params)
    sql = (
        "UPDATE products SET "
        + ", ".join(sets)
        + " WHERE id = :pid AND tenant_id = :tenant_id"
        + mod_and
    )
    with engine.begin() as connection:
        result = connection.execute(text(sql), params)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="产品不存在")


def products_pg_insert_row(
    body: dict,
    *,
    parse_price,
    parse_quantity,
    parse_is_active,
) -> int:
    from app.application.excel_imports import _norm_model

    compat = _compat_module()
    engine = compat.get_sync_engine()
    column_names = compat._products_pg_col_names()
    if not {"model_number", "name"}.issubset(column_names):
        raise HTTPException(
            status_code=503,
            detail="products 表缺少必要列（至少需要 model_number、name）。",
        )
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="产品名称不能为空")
    specification = str(body.get("specification") or "").strip()
    model_number_raw = body.get("model_number")
    model_number = str(model_number_raw).strip() if model_number_raw is not None else ""
    if not model_number:
        model_number = _norm_model("", name, specification)
    insert_columns: list[str] = []
    params: dict[str, object] = {}

    def add(column: str, value: object) -> None:
        if column in column_names:
            insert_columns.append(column)
            params[column] = value

    add("model_number", model_number[:120])
    add("name", name[:500])
    add("specification", specification or None)
    add("price", parse_price(body.get("price")))
    add("quantity", parse_quantity(body.get("quantity")))
    add("unit", str(body.get("unit") or "").strip()[:200])
    add(
        "description",
        str(body.get("description") or "") if body.get("description") is not None else None,
    )
    add(
        "category",
        str(body.get("category") or "")[:200] if body.get("category") is not None else None,
    )
    add(
        "brand",
        str(body.get("brand") or "")[:200] if body.get("brand") is not None else None,
    )
    is_active = parse_is_active(body.get("is_active"))
    if is_active is not None and "is_active" in column_names:
        add("is_active", is_active)
    if not insert_columns:
        raise HTTPException(status_code=500, detail="无法构造 INSERT 列")
    tenant_id = compat._require_tenant_id_or_raise(column_names, table_name="products")
    insert_columns.append("tenant_id")
    params["tenant_id"] = tenant_id
    mod_id = compat.scoped_mod_id()
    if "xcagi_mod_id" in column_names and mod_id:
        insert_columns.append("xcagi_mod_id")
        params["xcagi_mod_id"] = mod_id
    quoted = ", ".join(_sql_ident(column) for column in insert_columns)
    placeholders = ", ".join(":" + column for column in insert_columns)
    sql = _sql_insert_returning("products", quoted, placeholders)
    with engine.begin() as connection:
        new_id = connection.execute(text(sql), params).scalar_one()
    return int(new_id)


def products_pg_delete_row(pid: int) -> None:
    compat = _compat_module()
    engine = compat.get_sync_engine()
    columns = compat._products_pg_col_names()
    delete_params: dict[str, object] = {
        "pid": pid,
        "tenant_id": compat._require_tenant_id_or_raise(columns, table_name="products"),
    }
    mod_and = compat.products_update_or_delete_mod_and(columns, delete_params)
    sql = "DELETE FROM products WHERE id = :pid AND tenant_id = :tenant_id" + mod_and
    with engine.begin() as connection:
        result = connection.execute(text(sql), delete_params)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="产品不存在")


def products_pg_batch_delete_rows(raw_ids: list) -> tuple[int, list[str]]:
    compat = _compat_module()
    engine = compat.get_sync_engine()
    columns = compat._products_pg_col_names()
    deleted = 0
    skipped: list[str] = []
    with engine.begin() as connection:
        for raw in raw_ids:
            product_id = compat._product_parse_id(raw)
            if product_id is None:
                skipped.append(str(raw))
                continue
            delete_params: dict[str, object] = {
                "pid": product_id,
                "tenant_id": compat._require_tenant_id_or_raise(columns, table_name="products"),
            }
            mod_and = compat.products_update_or_delete_mod_and(columns, delete_params)
            sql = "DELETE FROM products WHERE id = :pid AND tenant_id = :tenant_id" + mod_and
            result = connection.execute(text(sql), delete_params)
            if result.rowcount:
                deleted += 1
            else:
                skipped.append(str(raw))
    return deleted, skipped
