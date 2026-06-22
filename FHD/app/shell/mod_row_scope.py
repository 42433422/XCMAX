from __future__ import annotations

from collections.abc import Mapping


def _column_name_set(column_names: set[str] | Mapping[str, object]) -> set[str]:
    if isinstance(column_names, Mapping):
        return set(column_names.keys())
    return set(column_names)


def scoped_mod_id() -> str | None:
    try:
        from app.request_active_mod_ctx import get_request_active_mod_id
    except ModuleNotFoundError:
        return None
    v = get_request_active_mod_id().strip()
    return v or None


def append_mod_scope_where(
    where_parts: list[str],
    bind: dict[str, object],
    column_names: set[str] | Mapping[str, object],
) -> None:
    """若表含 xcagi_mod_id 且当前请求带有 X-XCAGI-Active-Mod-Id，则追加按包过滤条件。"""
    cols = _column_name_set(column_names)
    if "xcagi_mod_id" not in cols:
        return
    mid = scoped_mod_id()
    if not mid:
        return
    where_parts.append("xcagi_mod_id = :xmid")
    bind["xmid"] = mid


def append_tenant_scope_where(
    where_parts: list[str],
    bind: dict[str, object],
    column_names: set[str] | Mapping[str, object],
) -> None:
    """raw SQL 的租户行级过滤（与 ORM 全局过滤 app/db/tenant_filter.py 语义一致）。

    若表含 ``tenant_id`` 且当前请求带租户上下文，则追加 ``(tenant_id = :__tenant_id
    OR tenant_id IS NULL)``（默认 NULL 容忍；``XCAGI_TENANT_STRICT=1`` 切严格相等）。
    无租户上下文 / 应急开关开启 / 表无 tenant_id 列 → no-op。
    """
    cols = _column_name_set(column_names)
    if "tenant_id" not in cols:
        return
    from app.db.tenant_filter import tenant_filter_disabled, tenant_filter_strict
    from app.request_tenant_ctx import get_request_tenant_id

    if tenant_filter_disabled():
        return
    tid = get_request_tenant_id()
    if tid is None:
        return
    bind["__tenant_id"] = tid
    if tenant_filter_strict():
        where_parts.append("tenant_id = :__tenant_id")
    else:
        where_parts.append("(tenant_id = :__tenant_id OR tenant_id IS NULL)")


def append_tenant_insert_col(
    col_pairs: list[tuple[str, str]],
    bind: dict[str, object],
    column_names: set[str] | Mapping[str, object],
) -> None:
    """raw INSERT 时给业务表写入 ``tenant_id``（与 ORM before_flush 自动打标语义一致）。

    若表含 ``tenant_id`` 且当前请求带租户上下文，则把 ``tenant_id`` 加入插入列。
    无租户上下文 / 应急开关开启 / 表无该列 → no-op（写入 NULL，由 NULL 容忍兜底）。
    """
    cols = _column_name_set(column_names)
    if "tenant_id" not in cols:
        return
    from app.db.tenant_filter import tenant_filter_disabled
    from app.request_tenant_ctx import get_request_tenant_id

    if tenant_filter_disabled():
        return
    tid = get_request_tenant_id()
    if tid is None:
        return
    if any(c == "tenant_id" for c, _ in col_pairs):
        return
    col_pairs.append(("tenant_id", "__tenant_id"))
    bind["__tenant_id"] = tid


def append_tenant_insert_ident(
    icols: list[str],
    bind: dict[str, object],
    column_names: set[str] | Mapping[str, object],
) -> None:
    """raw INSERT（``icols`` 列名列表 + ``bind[col]=值`` 形态）的租户打标。"""
    cols = _column_name_set(column_names)
    if "tenant_id" not in cols or "tenant_id" in icols:
        return
    from app.db.tenant_filter import tenant_filter_disabled
    from app.request_tenant_ctx import get_request_tenant_id

    if tenant_filter_disabled():
        return
    tid = get_request_tenant_id()
    if tid is None:
        return
    icols.append("tenant_id")
    bind["tenant_id"] = tid


def products_update_or_delete_mod_and(pcols: set[str], params: dict[str, object]) -> str:
    """UPDATE/DELETE products（及同类按包隔离表）时追加 AND 片段；与 append_mod_scope_where 共用 :xmid。"""
    if "xcagi_mod_id" not in pcols:
        return ""
    mid = scoped_mod_id()
    if not mid:
        return ""
    params["xmid"] = mid
    return " AND xcagi_mod_id = :xmid"
