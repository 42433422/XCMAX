# -*- coding: utf-8 -*-
"""里程碑 G/G2：ERP 四领域 handler（编排层在 Mod；DB/Service 仍用宿主）。"""

from __future__ import annotations

from typing import Any

MOD_SOURCE = "mod:xcagi-erp-domain-bridge"
EXECUTION_PATH = "mod_domain_handler"

MOD_DOMAIN_IDS = frozenset({"products", "shipment", "customers"})


def _tag(out: Any) -> Any:
    if isinstance(out, dict):
        tagged = dict(out)
        inner = tagged.get("execution_path")
        if inner and inner != EXECUTION_PATH:
            tagged["handler_via"] = inner
        tagged["source"] = MOD_SOURCE
        tagged["execution_path"] = EXECUTION_PATH
        return tagged
    return out


def _use_products_service() -> bool:
    from app.mod_sdk.erp_products_facade import is_erp_products_via_service_enabled

    return is_erp_products_via_service_enabled()


def _products_list(**kw: Any) -> Any:
    import logging

    request = kw.get("request")
    page = int(kw.get("page") or 1)
    per_page = int(kw.get("per_page") or 20)
    keyword = kw.get("keyword")
    unit = kw.get("unit")
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_list as svc_list

        return _tag(
            svc_list(
                request,
                page=page,
                per_page=per_page,
                keyword=keyword,
                unit=unit,
            )
        )
    from app.mod_sdk.host_services import verify_db_read_token_header
    from app.mod_sdk.host_services import _load_products_list_impl_pg

    if request is not None:
        verify_db_read_token_header(request)
    try:
        items, total, schema_hint = _load_products_list_impl_pg(page, per_page, keyword, unit)
        out: dict[str, Any] = {"success": True, "data": items, "total": total}
        if schema_hint:
            out["schema_hint"] = schema_hint
        return _tag(out)
    except Exception as e:
        logging.getLogger(__name__).exception("products list failed (mod handler)")
        return _tag({"success": False, "message": str(e), "data": [], "total": 0})


def _products_get(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_get as svc_get

        return svc_get(**kw)
    from app.mod_sdk.host_services import products_get_by_id

    return products_get_by_id(**kw)


def _products_add(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_add as svc_add

        return _tag(svc_add(kw.get("request"), kw.get("body") or {}))
    from app.mod_sdk.host_services import products_add

    return _tag(products_add(**kw))


def _products_update(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_update as svc_update

        return _tag(svc_update(kw.get("request"), kw.get("body") or {}))
    from app.mod_sdk.host_services import products_update

    return _tag(products_update(**kw))


def _products_delete(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_delete as svc_delete

        return _tag(svc_delete(kw.get("request"), kw.get("body") or {}))
    from app.mod_sdk.host_services import products_delete

    return _tag(products_delete(**kw))


def _products_batch_delete(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_batch_delete as svc_batch_del

        return _tag(svc_batch_del(kw.get("request"), kw.get("body") or {}))
    from app.mod_sdk.host_services import products_batch_delete

    return _tag(products_batch_delete(**kw))


def _products_names(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_product_names

        return _tag(products_product_names())
    from app.mod_sdk.host_services import products_product_names

    return _tag(products_product_names(**kw))


def _products_names_search(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_product_names

        return _tag(products_product_names(keyword=str(kw.get("keyword") or "")))
    from app.mod_sdk.host_services import products_product_names_search

    return _tag(products_product_names_search(**kw))


def _products_batch(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_batch

        return _tag(products_batch(kw.get("body") or {}))
    from app.mod_sdk.host_services import products_batch

    return _tag(products_batch(**kw))


def _shipment_records_list(**kw: Any) -> Any:
    from app.mod_sdk.host_services import get_shipment_application_service_core

    unit = (kw.get("unit") or kw.get("unit_name") or "").strip() or None
    records = get_shipment_application_service_core().get_shipment_records(unit)
    return _tag({"success": True, "data": records})


def _shipment_records_units(**kw: Any) -> Any:
    from app.mod_sdk.host_services import shipment_records_units

    return _tag(shipment_records_units(**kw))


def _shipment_orders_list(**kw: Any) -> Any:
    from app.mod_sdk.host_services import get_shipment_application_service_core

    limit = int(kw.get("limit") or 100)
    orders_list = get_shipment_application_service_core().get_orders(limit=limit) or []
    inner = {"success": True, "data": orders_list, "count": len(orders_list)}
    return _tag({"success": True, "data": inner, "count": len(inner)})


def _use_customers_service() -> bool:
    from app.mod_sdk.erp_customers_facade import is_erp_customers_via_service_enabled

    return is_erp_customers_via_service_enabled()


def _customers_list(**kw: Any) -> Any:
    request = kw.get("request")
    page = int(kw.get("page") or 1)
    per_page = int(kw.get("per_page") or 20)
    keyword = kw.get("keyword")
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_list as svc_list

        return _tag(
            svc_list(request, page=page, per_page=per_page, keyword=keyword)
        )
    from app.mod_sdk.host_services import verify_db_read_token_header
    from app.mod_sdk.host_services import (
        _customer_row_matches_keyword,
        _customers_schema_hint_if_empty,
        _load_customers_rows,
    )

    if request is not None:
        verify_db_read_token_header(request)
    rows = _load_customers_rows()
    kw_str = (keyword or "").strip()
    if kw_str:
        rows = [r for r in rows if _customer_row_matches_keyword(r, kw_str)]
    total = len(rows)
    offset = (page - 1) * per_page
    out: dict[str, Any] = {
        "success": True,
        "data": rows[offset : offset + per_page],
        "total": total,
    }
    if total == 0:
        ch = _customers_schema_hint_if_empty()
        if ch:
            out["schema_hint"] = ch
    return _tag(out)


def _customers_get(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_get as svc_get

        return svc_get(**kw)
    from app.mod_sdk.host_services import customers_get_one

    return customers_get_one(**kw)


def _customers_create(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_create as svc_create

        return _tag(svc_create(kw.get("request"), kw.get("body") or {}))
    from app.mod_sdk.host_services import customers_create

    return _tag(customers_create(**kw))


def _customers_update(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_update as svc_update

        return _tag(
            svc_update(kw.get("request"), int(kw.get("customer_id")), kw.get("body") or {})
        )
    from app.mod_sdk.host_services import customers_update

    return _tag(customers_update(**kw))


def _customers_delete(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_delete as svc_delete

        return _tag(svc_delete(kw.get("request"), int(kw.get("customer_id"))))
    from app.mod_sdk.host_services import customers_delete

    return _tag(customers_delete(**kw))


# 微信 handler 已移至 xcagi-wechat-bridge Mod


_DISPATCH: dict[tuple[str, str], Any] = {
    ("products", "list"): _products_list,
    ("products", "get"): _products_get,
    ("products", "add"): _products_add,
    ("products", "update"): _products_update,
    ("products", "delete"): _products_delete,
    ("products", "batch_delete"): _products_batch_delete,
    ("products", "product_names"): _products_names,
    ("products", "product_names_search"): _products_names_search,
    ("products", "batch"): _products_batch,
    ("shipment", "records_list"): _shipment_records_list,
    ("shipment", "records_units"): _shipment_records_units,
    ("shipment", "orders_list"): _shipment_orders_list,
    ("customers", "list"): _customers_list,
    ("customers", "get"): _customers_get,
    ("customers", "create"): _customers_create,
    ("customers", "update"): _customers_update,
    ("customers", "delete"): _customers_delete,
    # wechat 域已移至 xcagi-wechat-bridge Mod
}


def list_registered_actions() -> list[str]:
    return [f"{d}.{a}" for d, a in sorted(_DISPATCH.keys())]


def run_domain_handler(domain: str, action: str, **kwargs: Any) -> Any | None:
    dom = str(domain or "").strip()
    act = str(action or "").strip()
    if dom not in MOD_DOMAIN_IDS:
        return None
    fn = _DISPATCH.get((dom, act))
    if not callable(fn):
        return None
    return fn(**kwargs)
