"""Existing tenant-scoped customer insertion used by shipment recording."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import DateTime, bindparam, text

from app.infrastructure.persistence.compat_db.compat_db_base import (
    _customer_pg_engine_insp,
    _pg_purchase_unit_active_sql,
    _sql_ident,
    _sql_insert_returning,
    _sql_select_from_where,
)
from app.infrastructure.persistence.compat_db.queries import (
    _customer_row_for_api,
)
from app.infrastructure.tenant_scope import (
    TenantScopeError,
    append_tenant_scope_where,
    require_raw_sql_tenant_id,
)
from app.shell.mod_row_scope import (
    append_mod_scope_where,
    scoped_mod_id,
)
from app.utils.time import utc_now_naive


def _tenant_scope_http_error(exc: TenantScopeError) -> HTTPException:
    return HTTPException(status_code=403, detail=str(exc))


def _append_tenant_scope_or_raise(
    where_parts: list[str],
    bind: dict[str, object],
    column_names: set[str] | dict[str, object],
    *,
    table_name: str,
) -> None:
    if not append_tenant_scope_where(where_parts, bind, column_names, table_name=table_name):
        raise _tenant_scope_http_error(
            TenantScopeError(f"{table_name} 缺少租户上下文或 tenant_id 列，拒绝业务写入")
        )


def _require_tenant_id_or_raise(
    column_names: set[str] | dict[str, object],
    *,
    table_name: str,
) -> int:
    try:
        return require_raw_sql_tenant_id(column_names, table_name=table_name)
    except TenantScopeError as exc:
        raise _tenant_scope_http_error(exc) from exc


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
    _append_tenant_scope_or_raise(where_parts, params, pu_cols, table_name="purchase_units")
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
        _append_tenant_scope_or_raise(dup_parts, dup_bind, pu_cols, table_name="purchase_units")
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
        tid = _require_tenant_id_or_raise(pu_cols, table_name="purchase_units")
        col_pairs.append(("tenant_id", "tenant_id"))
        bind["tenant_id"] = tid
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
        statement = text(_sql_insert_returning("purchase_units", cols_sql, vals_sql))
        for timestamp in ("ca", "ua"):
            if timestamp in bind:
                statement = statement.bindparams(bindparam(timestamp, type_=DateTime()))
        r = conn.execute(statement, bind)
        new_id = int(r.scalar_one())
        conn.commit()
    return _customer_pg_fetch_by_id(eng, insp, new_id)
