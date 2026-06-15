"""
xcagi_compat 共享 DB 写入 / 更新 / 删除辅助函数。

供 xcagi_compat_customer / product 等路由子模块复用。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.infrastructure.db.sync_engine import get_sync_engine
from app.infrastructure.persistence.compat_db.base import (
    _customer_pg_engine_insp,
    _customer_pg_products_has_unit,
    _pg_expr_norm_unit,
    _pg_purchase_unit_active_sql,
    _product_parse_id,
    _sql_delete_where,
    _sql_ident,
    _sql_insert_returning,
    _sql_select_from_where,
    _sql_update_set_where,
)
from app.infrastructure.persistence.compat_db.queries import (
    _customer_row_for_api,
)
from app.shell.mod_row_scope import (
    append_mod_scope_where,
    products_update_or_delete_mod_and,
    scoped_mod_id,
)
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)


def _products_delete_by_unit_pg(eng, unit_name: str) -> int:
    un = (unit_name or "").strip()
    if not un:
        return 0
    insp = inspect(eng)
    if not _customer_pg_products_has_unit(insp):
        return 0
    pcols = {c["name"] for c in insp.get_columns("products")}
    col = _pg_expr_norm_unit("CAST(unit AS TEXT)")
    prm = _pg_expr_norm_unit("CAST(:u AS TEXT)")
    where_parts = [f"{col} = {prm}"]
    params: dict[str, object] = {"u": un}
    append_mod_scope_where(where_parts, params, pcols)
    where_sql = " AND ".join(where_parts)
    with eng.begin() as conn:
        r = conn.execute(
            text(_sql_delete_where("products", where_sql)),
            params,
        )
        return int(r.rowcount or 0)


def _purchase_units_delete_by_norm_unit_pg(eng, unit_name: str) -> int:
    un = (unit_name or "").strip()
    if not un:
        return 0
    insp = inspect(eng)
    if "purchase_units" not in insp.get_table_names():
        return 0
    cols = {c["name"] for c in insp.get_columns("purchase_units")}
    if "unit_name" not in cols:
        return 0
    col = _pg_expr_norm_unit("CAST(unit_name AS TEXT)")
    prm = _pg_expr_norm_unit("CAST(:u AS TEXT)")
    where_parts = [f"{col} = {prm}"]
    params: dict[str, object] = {"u": un}
    append_mod_scope_where(where_parts, params, cols)
    where_sql = " AND ".join(where_parts)
    with eng.begin() as conn:
        r = conn.execute(
            text(_sql_delete_where("purchase_units", where_sql)),
            params,
        )
        return int(r.rowcount or 0)


def _customers_delete_by_norm_name_pg(eng, insp, customer_name: str) -> int:
    cn = (customer_name or "").strip()
    if not cn or "customers" not in insp.get_table_names():
        return 0
    cols_names = {c["name"] for c in insp.get_columns("customers")}
    name_col = next(
        (c for c in ("customer_name", "name", "客户名称") if c in cols_names),
        None,
    )
    if not name_col:
        return 0
    col = _pg_expr_norm_unit(f"CAST({_sql_ident(name_col)} AS TEXT)")
    prm = _pg_expr_norm_unit("CAST(:u AS TEXT)")
    where_parts = [f"{col} = {prm}"]
    params: dict[str, object] = {"u": cn}
    append_mod_scope_where(where_parts, params, cols_names)
    where_sql = " AND ".join(where_parts)
    with eng.begin() as conn:
        r = conn.execute(
            text(_sql_delete_where(_sql_ident("customers"), where_sql)),
            params,
        )
        return int(r.rowcount or 0)


def _purchase_units_delete_by_id_pg(eng, customer_id: int) -> int:
    insp = inspect(eng)
    if "purchase_units" not in insp.get_table_names():
        return 0
    cols = {c["name"] for c in insp.get_columns("purchase_units")}
    if "id" not in cols:
        return 0
    where_parts = ["id = :id"]
    params: dict[str, object] = {"id": int(customer_id)}
    append_mod_scope_where(where_parts, params, cols)
    where_sql = " AND ".join(where_parts)
    with eng.begin() as conn:
        r = conn.execute(
            text(_sql_delete_where("purchase_units", where_sql)),
            params,
        )
        return int(r.rowcount or 0)


def _customers_delete_by_id_pg(eng, insp, customer_id: int) -> int:
    if "customers" not in insp.get_table_names():
        return 0
    cols = {c["name"] for c in insp.get_columns("customers")}
    id_col = "id" if "id" in cols else ("customer_id" if "customer_id" in cols else None)
    if not id_col:
        return 0
    where_parts = [f"{_sql_ident(id_col)} = :id"]
    params: dict[str, object] = {"id": int(customer_id)}
    append_mod_scope_where(where_parts, params, cols)
    where_sql = " AND ".join(where_parts)
    with eng.begin() as conn:
        r = conn.execute(
            text(_sql_delete_where(_sql_ident("customers"), where_sql)),
            params,
        )
        return int(r.rowcount or 0)


def _products_unit_replace_pg(eng, old_name: str, new_name: str) -> None:
    o = (old_name or "").strip()
    n = (new_name or "").strip()
    if not o or not n or o == n:
        return
    insp = inspect(eng)
    if not _customer_pg_products_has_unit(insp):
        return
    pcols = {c["name"] for c in insp.get_columns("products")}
    col = _pg_expr_norm_unit("CAST(unit AS TEXT)")
    prm = _pg_expr_norm_unit("CAST(:oo AS TEXT)")
    where_parts = [f"{col} = {prm}"]
    params: dict[str, object] = {"nn": n, "oo": o}
    append_mod_scope_where(where_parts, params, pcols)
    where_sql = " AND ".join(where_parts)
    with eng.connect() as conn:
        conn.execute(
            text(_sql_update_set_where("products", "unit = :nn", where_sql)),
            params,
        )
        conn.commit()


def _customer_pg_row_select_sql(insp) -> tuple[str, list[str]]:
    have = {c["name"] for c in insp.get_columns("purchase_units")}
    want = [
        "id",
        "unit_name",
        "contact_person",
        "contact_phone",
        "address",
        "is_active",
        "created_at",
        "updated_at",
    ]
    sel = [c for c in want if c in have]
    if not sel or "id" not in sel:
        raise HTTPException(status_code=503, detail="purchase_units 表结构不完整（缺少 id）。")
    parts = []
    for c in sel:
        if c == "unit_name":
            parts.append(f"{_sql_ident(c)} AS unit_name")
        else:
            parts.append(_sql_ident(c))
    return ", ".join(parts), sel


def _customer_pg_fetch_by_id(eng, insp, customer_id: int) -> dict:
    sel_sql, _ = _customer_pg_row_select_sql(insp)
    pu_cols = {c["name"] for c in insp.get_columns("purchase_units")}
    where_parts = ["id = :id"]
    params: dict[str, object] = {"id": int(customer_id)}
    append_mod_scope_where(where_parts, params, pu_cols)
    where_sql = " AND ".join(where_parts)
    with eng.connect() as conn:
        r = (
            conn.execute(
                text(_sql_select_from_where(sel_sql, "purchase_units", where_sql)),
                params,
            )
            .mappings()
            .first()
        )
    if not r:
        raise HTTPException(status_code=404, detail="客户不存在")
    d = dict(r)
    d["customer_name"] = d.get("unit_name") or ""
    return _customer_row_for_api(d)


def _customer_pg_insert(name: str, cp: str, ph: str, addr: str) -> dict:
    eng, insp = _customer_pg_engine_insp()
    pu_cols = {c["name"]: c for c in insp.get_columns("purchase_units")}
    if "unit_name" not in pu_cols:
        raise HTTPException(status_code=503, detail="purchase_units 缺少 unit_name 列。")
    now = utc_now_naive()
    with eng.connect() as conn:
        dup_parts = ["unit_name = :n", _pg_purchase_unit_active_sql()]
        dup_bind: dict[str, object] = {"n": name}
        append_mod_scope_where(dup_parts, dup_bind, pu_cols)
        dup_sql = " AND ".join(dup_parts)
        dup = conn.execute(
            text(_sql_select_from_where("id", "purchase_units", dup_sql)),
            dup_bind,
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="客户名称已存在")
        col_pairs: list[tuple[str, str]] = [
            ("unit_name", "un"),
            ("contact_person", "cp"),
            ("contact_phone", "ph"),
            ("address", "addr"),
        ]
        bind: dict = {"un": name, "cp": cp, "ph": ph, "addr": addr}
        mid = scoped_mod_id()
        if "xcagi_mod_id" in pu_cols and mid:
            col_pairs.append(("xcagi_mod_id", "xmid"))
            bind["xmid"] = mid
        if "is_active" in pu_cols:
            col_pairs.append(("is_active", "ia"))
            t = str(pu_cols["is_active"].get("type") or "").lower()
            bind["ia"] = True if "bool" in t else 1
        if "created_at" in pu_cols:
            col_pairs.append(("created_at", "ca"))
            bind["ca"] = now
        if "updated_at" in pu_cols:
            col_pairs.append(("updated_at", "ua"))
            bind["ua"] = now
        cols_sql = ", ".join(_sql_ident(c) for c, _ in col_pairs)
        vals_sql = ", ".join(f":{bk}" for _, bk in col_pairs)
        r = conn.execute(
            text(_sql_insert_returning("purchase_units", cols_sql, vals_sql)),
            bind,
        )
        new_id = int(r.scalar_one())
        conn.commit()
    return _customer_pg_fetch_by_id(eng, insp, new_id)


def _customer_pg_update(customer_id: int, name: str, cp: str, ph: str, addr: str) -> dict:
    eng, insp = _customer_pg_engine_insp()
    pu_cols = {c["name"] for c in insp.get_columns("purchase_units")}
    with eng.connect() as conn:
        prev_parts = ["id = :id", _pg_purchase_unit_active_sql()]
        prev_bind: dict[str, object] = {"id": int(customer_id)}
        append_mod_scope_where(prev_parts, prev_bind, pu_cols)
        prev = (
            conn.execute(
                text(
                    _sql_select_from_where(
                        "id, unit_name",
                        "purchase_units",
                        " AND ".join(prev_parts),
                    )
                ),
                prev_bind,
            )
            .mappings()
            .first()
        )
        if not prev:
            raise HTTPException(status_code=404, detail="客户不存在或已删除")
        old_name = str(prev["unit_name"] or "").strip()
        clash_parts = [
            "unit_name = :n",
            "id != :id",
            _pg_purchase_unit_active_sql(),
        ]
        clash_bind: dict[str, object] = {"n": name, "id": int(customer_id)}
        append_mod_scope_where(clash_parts, clash_bind, pu_cols)
        clash = conn.execute(
            text(_sql_select_from_where("id", "purchase_units", " AND ".join(clash_parts))),
            clash_bind,
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="客户名称与其他记录冲突")
        now = utc_now_naive()
        upd_bind = {
            "un": name,
            "cp": cp,
            "ph": ph,
            "addr": addr,
            "id": int(customer_id),
        }
        mod_and = products_update_or_delete_mod_and(pu_cols, upd_bind)
        if "updated_at" in pu_cols:
            upd_bind["ua"] = now
            conn.execute(
                text(
                    "UPDATE purchase_units SET unit_name = :un, contact_person = :cp, "
                    "contact_phone = :ph, address = :addr, updated_at = :ua WHERE id = :id"
                    + mod_and
                ),
                upd_bind,
            )
        else:
            conn.execute(
                text(
                    "UPDATE purchase_units SET unit_name = :un, contact_person = :cp, "
                    "contact_phone = :ph, address = :addr WHERE id = :id" + mod_and
                ),
                upd_bind,
            )
        conn.commit()
    if old_name and old_name != name.strip():
        _products_unit_replace_pg(eng, old_name, name.strip())
    return _customer_pg_fetch_by_id(eng, insp, customer_id)


def _customer_pg_select_customers_name_by_id(eng, insp, customer_id: int) -> tuple[str, str] | None:
    if "customers" not in insp.get_table_names():
        return None
    cols = {c["name"] for c in insp.get_columns("customers")}
    id_col = "id" if "id" in cols else ("customer_id" if "customer_id" in cols else None)
    name_col = next(
        (c for c in ("customer_name", "name", "客户名称") if c in cols),
        None,
    )
    if not id_col or not name_col:
        return None
    where_parts = [f"{_sql_ident(id_col)} = :id"]
    cbind: dict[str, object] = {"id": int(customer_id)}
    append_mod_scope_where(where_parts, cbind, cols)
    where_clause = " AND ".join(where_parts)
    select_sql = (
        "SELECT "
        + _sql_ident(name_col)
        + " AS nm FROM "
        + _sql_ident("customers")
        + " WHERE "
        + where_clause
    )
    with eng.connect() as conn:
        r = (
            conn.execute(
                text(select_sql),
                cbind,
            )
            .mappings()
            .first()
        )
        if not r:
            return None
        nm = str(r["nm"] or "").strip()
        return (nm, id_col)


def _customer_pg_delete_anywhere(customer_id: int) -> None:
    eng, insp = _customer_pg_engine_insp()
    cid = int(customer_id)
    resolved_name: str | None = None

    if "purchase_units" in insp.get_table_names():
        pu_cols = {c["name"] for c in insp.get_columns("purchase_units")}
        where_parts = ["id = :id"]
        pbind: dict[str, object] = {"id": cid}
        append_mod_scope_where(where_parts, pbind, pu_cols)
        with eng.connect() as conn:
            r = conn.execute(
                text(
                    _sql_select_from_where("unit_name", "purchase_units", " AND ".join(where_parts))
                ),
                pbind,
            ).first()
            if r:
                resolved_name = str(r[0] or "").strip() or None

    if not resolved_name:
        csel = _customer_pg_select_customers_name_by_id(eng, insp, cid)
        if csel:
            nm, _id_col = csel
            resolved_name = (nm or "").strip() or None

    if not resolved_name:
        from app.infrastructure.persistence.compat_db.queries import _customer_find_by_id

        hint = _customer_find_by_id(cid)
        if hint and int(hint.get("id") or 0) == cid:
            resolved_name = str(hint.get("customer_name") or "").strip() or None

    n_prod = 0
    n_pu = 0
    n_cu = 0
    if resolved_name:
        n_prod += _products_delete_by_unit_pg(eng, resolved_name)
        n_pu += _purchase_units_delete_by_norm_unit_pg(eng, resolved_name)
        n_cu += _customers_delete_by_norm_name_pg(eng, insp, resolved_name)

    n_pu += _purchase_units_delete_by_id_pg(eng, cid)
    n_cu += _customers_delete_by_id_pg(eng, insp, cid)

    if n_prod == 0 and n_pu == 0 and n_cu == 0:
        raise HTTPException(status_code=404, detail="客户不存在")


def _customer_delete_unified(customer_id: int) -> None:
    _customer_pg_delete_anywhere(customer_id)


def _products_pg_col_names() -> set[str]:
    eng = get_sync_engine()
    insp = inspect(eng)
    return {c["name"] for c in insp.get_columns("products")}


def products_pg_update_row(
    pid: int,
    body: dict,
    *,
    parse_price,
    parse_quantity,
    parse_is_active,
) -> None:
    eng = get_sync_engine()
    col_names = _products_pg_col_names()
    if not {"id", "model_number", "name"}.issubset(col_names):
        raise HTTPException(
            status_code=503,
            detail="products 表缺少必要列（至少需要 id、model_number、name）。",
        )
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="产品名称不能为空")

    sets: list[str] = []
    params: dict[str, object] = {"pid": pid}

    if "model_number" in col_names:
        mn = body.get("model_number")
        sets.append("model_number = :model_number")
        params["model_number"] = (str(mn).strip() if mn is not None else "")[:120]
    sets.append("name = :name")
    params["name"] = name[:500]
    if "specification" in col_names:
        sp = body.get("specification")
        sets.append("specification = :specification")
        params["specification"] = None if sp is None else str(sp)
    if "price" in col_names:
        sets.append("price = :price")
        params["price"] = parse_price(body.get("price"))
    if "quantity" in col_names:
        sets.append("quantity = :quantity")
        params["quantity"] = parse_quantity(body.get("quantity"))
    if "unit" in col_names:
        un = body.get("unit")
        sets.append("unit = :unit")
        params["unit"] = (str(un).strip() if un is not None else "")[:200]
    if "description" in col_names:
        dv = body.get("description")
        sets.append("description = :description")
        params["description"] = None if dv is None else str(dv)
    if "category" in col_names:
        cv = body.get("category")
        sets.append("category = :category")
        params["category"] = None if cv is None else str(cv)[:200]
    if "brand" in col_names:
        bv = body.get("brand")
        sets.append("brand = :brand")
        params["brand"] = None if bv is None else str(bv)[:200]
    if "is_active" in col_names:
        ia = parse_is_active(body.get("is_active"))
        if ia is not None:
            sets.append("is_active = :is_active")
            params["is_active"] = ia
    if "updated_at" in col_names:
        sets.append("updated_at = NOW()")
    if not sets:
        raise HTTPException(status_code=400, detail="没有可更新的列")

    mod_and = products_update_or_delete_mod_and(col_names, params)
    sql = "UPDATE products SET " + ", ".join(sets) + " WHERE id = :pid" + mod_and
    with eng.begin() as conn:
        r = conn.execute(text(sql), params)
        if r.rowcount == 0:
            raise HTTPException(status_code=404, detail="产品不存在")


def products_pg_insert_row(
    body: dict,
    *,
    parse_price,
    parse_quantity,
    parse_is_active,
) -> int:
    from app.application.excel_imports import _norm_model

    eng = get_sync_engine()
    col_names = _products_pg_col_names()
    if not {"model_number", "name"}.issubset(col_names):
        raise HTTPException(
            status_code=503,
            detail="products 表缺少必要列（至少需要 model_number、name）。",
        )
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="产品名称不能为空")
    spec = str(body.get("specification") or "").strip()
    mn_raw = body.get("model_number")
    model_number = str(mn_raw).strip() if mn_raw is not None else ""
    if not model_number:
        model_number = _norm_model("", name, spec)

    icols: list[str] = []
    params: dict[str, object] = {}

    def _add(col: str, val: object) -> None:
        if col in col_names:
            icols.append(col)
            params[col] = val

    _add("model_number", model_number[:120])
    _add("name", name[:500])
    _add("specification", spec or None)
    _add("price", parse_price(body.get("price")))
    _add("quantity", parse_quantity(body.get("quantity")))
    unit = str(body.get("unit") or "").strip()[:200]
    _add("unit", unit)
    _add(
        "description",
        str(body.get("description") or "") if body.get("description") is not None else None,
    )
    _add(
        "category",
        str(body.get("category") or "")[:200] if body.get("category") is not None else None,
    )
    _add("brand", str(body.get("brand") or "")[:200] if body.get("brand") is not None else None)
    ia = parse_is_active(body.get("is_active"))
    if ia is not None and "is_active" in col_names:
        _add("is_active", ia)
    if not icols:
        raise HTTPException(status_code=500, detail="无法构造 INSERT 列")
    mid = scoped_mod_id()
    if "xcagi_mod_id" in col_names and mid:
        icols.append("xcagi_mod_id")
        params["xcagi_mod_id"] = mid
    quoted = ", ".join(_sql_ident(c) for c in icols)
    ph = ", ".join(":" + c for c in icols)
    sql = _sql_insert_returning("products", quoted, ph)
    with eng.begin() as conn:
        new_id = conn.execute(text(sql), params).scalar_one()
    return int(new_id)


def products_pg_delete_row(pid: int) -> None:
    eng = get_sync_engine()
    pcols = _products_pg_col_names()
    del_params: dict[str, object] = {"pid": pid}
    mod_and = products_update_or_delete_mod_and(pcols, del_params)
    sql = "DELETE FROM products WHERE id = :pid" + mod_and
    with eng.begin() as conn:
        r = conn.execute(text(sql), del_params)
        if r.rowcount == 0:
            raise HTTPException(status_code=404, detail="产品不存在")


def products_pg_batch_delete_rows(raw_ids: list) -> tuple[int, list[str]]:
    eng = get_sync_engine()
    pcols = _products_pg_col_names()
    deleted = 0
    skipped: list[str] = []
    with eng.begin() as conn:
        for raw in raw_ids:
            pid = _product_parse_id(raw)
            if pid is None:
                skipped.append(str(raw))
                continue
            del_params = {"pid": pid}
            mod_and = products_update_or_delete_mod_and(pcols, del_params)
            sql = "DELETE FROM products WHERE id = :pid" + mod_and
            r = conn.execute(text(sql), del_params)
            if r.rowcount:
                deleted += 1
            else:
                skipped.append(str(raw))
    return deleted, skipped
