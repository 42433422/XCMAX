# -*- coding: utf-8 -*-
"""里程碑 G/G2：ERP 四领域 handler（编排层在 Mod；DB/Service 仍用宿主）。"""

from __future__ import annotations

from typing import Any

MOD_SOURCE = "mod:xcagi-erp-domain-bridge"
EXECUTION_PATH = "mod_domain_handler"

MOD_DOMAIN_IDS = frozenset({"products", "shipment", "customers", "wechat", "etl"})


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
    from app.infrastructure.auth.db_token import verify_db_read_token_header
    from app.fastapi_routes.domains.db.product_queries import _load_products_list_impl_pg

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
    from app.fastapi_routes.domains.product.compat_routes import products_get_by_id

    return products_get_by_id(**kw)


def _products_add(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_add as svc_add

        return _tag(svc_add(kw.get("request"), kw.get("body") or {}))
    from app.fastapi_routes.domains.product.compat_routes import products_add

    return _tag(products_add(**kw))


def _products_update(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_update as svc_update

        return _tag(svc_update(kw.get("request"), kw.get("body") or {}))
    from app.fastapi_routes.domains.product.compat_routes import products_update

    return _tag(products_update(**kw))


def _products_delete(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_delete as svc_delete

        return _tag(svc_delete(kw.get("request"), kw.get("body") or {}))
    from app.fastapi_routes.domains.product.compat_routes import products_delete

    return _tag(products_delete(**kw))


def _products_batch_delete(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_batch_delete as svc_batch_del

        return _tag(svc_batch_del(kw.get("request"), kw.get("body") or {}))
    from app.fastapi_routes.domains.product.compat_routes import products_batch_delete

    return _tag(products_batch_delete(**kw))


def _products_names(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_product_names

        return _tag(products_product_names())
    from app.fastapi_routes.domains.product.routes import products_product_names

    return _tag(products_product_names(**kw))


def _products_names_search(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_product_names

        return _tag(products_product_names(keyword=str(kw.get("keyword") or "")))
    from app.fastapi_routes.domains.product.routes import products_product_names_search

    return _tag(products_product_names_search(**kw))


def _products_batch(**kw: Any) -> Any:
    if _use_products_service():
        from app.mod_sdk.erp_products_facade import products_batch

        return _tag(products_batch(kw.get("body") or {}))
    from app.fastapi_routes.domains.product.routes import products_batch

    return _tag(products_batch(**kw))


def _shipment_records_list(**kw: Any) -> Any:
    from app.bootstrap import get_shipment_application_service_core

    unit = (kw.get("unit") or kw.get("unit_name") or "").strip() or None
    records = get_shipment_application_service_core().get_shipment_records(unit)
    return _tag({"success": True, "data": records})


def _shipment_records_units(**kw: Any) -> Any:
    from app.fastapi_routes.domains.product.compat_routes import shipment_records_units

    return _tag(shipment_records_units(**kw))


def _shipment_orders_list(**kw: Any) -> Any:
    from app.bootstrap import get_shipment_application_service_core

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
    from app.infrastructure.auth.db_token import verify_db_read_token_header
    from app.fastapi_routes.domains.db.queries import (
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
    from app.fastapi_routes.domains.customer.routes import customers_get_one

    return customers_get_one(**kw)


def _customers_create(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_create as svc_create

        return _tag(svc_create(kw.get("request"), kw.get("body") or {}))
    from app.fastapi_routes.domains.customer.routes import customers_create

    return _tag(customers_create(**kw))


def _customers_update(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_update as svc_update

        return _tag(
            svc_update(kw.get("request"), int(kw.get("customer_id")), kw.get("body") or {})
        )
    from app.fastapi_routes.domains.customer.routes import customers_update

    return _tag(customers_update(**kw))


def _customers_delete(**kw: Any) -> Any:
    if _use_customers_service():
        from app.mod_sdk.erp_customers_facade import customers_delete as svc_delete

        return _tag(svc_delete(kw.get("request"), int(kw.get("customer_id"))))
    from app.fastapi_routes.domains.customer.routes import customers_delete

    return _tag(customers_delete(**kw))


def _wechat_contacts_list(**kw: Any) -> Any:
    from app.application import get_wechat_contact_app_service

    keyword = kw.get("keyword")
    contact_type = str(kw.get("type") or "all")
    starred = str(kw.get("starred") or "false")
    limit = int(kw.get("limit") or 100)
    service = get_wechat_contact_app_service()
    contacts = service.get_contacts(
        keyword=keyword,
        contact_type=contact_type if contact_type != "all" else None,
        starred_only=starred.lower() == "true",
        limit=limit,
    )
    return _tag({"success": True, "data": contacts, "total": len(contacts)})


def _wechat_contact_get(**kw: Any) -> Any:
    from fastapi.responses import JSONResponse

    from app.application import get_wechat_contact_app_service

    contact_id = int(kw.get("contact_id") or 0)
    service = get_wechat_contact_app_service()
    contact = service.get_contact_by_id(contact_id)
    if contact:
        return _tag({"success": True, "data": contact})
    return JSONResponse({"success": False, "message": "联系人不存在"}, status_code=404)


def _wechat_tasks(**kw: Any) -> Any:
    from fastapi.responses import JSONResponse

    from app.application import get_wechat_task_app_service

    status = str(kw.get("status") or "pending")
    contact_id = kw.get("contact_id")
    limit = int(kw.get("limit") or 20)
    try:
        service = get_wechat_task_app_service()
        tasks = service.get_tasks(contact_id=contact_id, status=status, limit=limit)
        return _tag({"success": True, "data": tasks, "total": len(tasks)})
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


# ── ETL 数据对接中心 ──────────────────────────────────────────

ETL_SUPPORTED_SOURCES = ("excel", "csv", "manual")
ETL_TARGET_ENTITIES = ("products", "customers", "orders", "shipment-records")


def _etl_sources(**kw: Any) -> Any:
    """返回数据对接中心支持的数据源类型与目标实体。"""
    return _tag({
        "success": True,
        "data": {
            "sources": ETL_SUPPORTED_SOURCES,
            "targets": ETL_TARGET_ENTITIES,
            "capabilities": ["extract", "transform", "load", "preview"],
        },
    })


def _etl_preview(**kw: Any) -> Any:
    """Extract + Transform 预览：解析文件并返回字段映射结果，不写库。"""
    file_body = kw.get("file_body") or b""
    filename = str(kw.get("filename") or "upload.xlsx")
    target_entity = str(kw.get("target_entity") or "").strip()

    if not file_body:
        return _tag({"success": False, "message": "未提供文件内容"})

    # 直接调 analyze-only 入口，避免 ingest_* 把模板写入 templates 表（preview 不应有副作用）
    from app.fastapi_routes.document_templates_compat import run_archive_template_analyze

    analyzed, _code = run_archive_template_analyze(
        file_body=file_body,
        filename=filename,
        template_scope=target_entity,
    )
    if not analyzed.get("success"):
        return _tag(analyzed)

    fields = analyzed.get("fields") or []
    preview_data = analyzed.get("preview_data") or {}
    mapping = _infer_field_mapping(fields, target_entity)
    return _tag({
        "success": True,
        "data": {
            "filename": filename,
            "fields": fields,
            "preview_data": preview_data,
            "field_mapping": mapping,
            "target_entity": target_entity or mapping.get("_inferred_scope", ""),
            "task_id": analyzed.get("task_id"),
        },
    })


def _etl_execute(**kw: Any) -> Any:
    """Extract + Transform + Load：解析文件、转换字段、写入目标实体表。"""
    file_body = kw.get("file_body") or b""
    filename = str(kw.get("filename") or "upload.xlsx")
    target_entity = str(kw.get("target_entity") or "").strip()
    sheet_name = str(kw.get("sheet_name") or "").strip() or None

    if not file_body:
        return _tag({"success": False, "message": "未提供文件内容"})

    # 1. Extract：复用 shipment_excel_etl 的解析能力（发货单/业务单据）
    if target_entity in ("orders", "shipment-records", ""):
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )

        svc = get_shipment_excel_etl_app_service()
        result = svc.execute(
            file_bytes=file_body,
            filename=filename,
            sheet_name=sheet_name,
            skip_user_confirm=True,
        )
        return _tag(result)

    # 2. Extract + Transform + Load：产品/客户走通用解析 → domain_handler 入库
    from app.application.office_template_ingest_app_service import (
        ingest_office_bytes_to_template_library,
    )

    analyzed, _ = ingest_office_bytes_to_template_library(
        file_body=file_body,
        filename=filename,
        template_scope=target_entity,
        source="etl_execute",
    )
    if not analyzed.get("success"):
        return _tag(analyzed)

    # ingest_* 返回结构：{"success": ..., "analyzed": {fields, preview_data, ...}, "task_id": ..., "template": {...}}
    inner = analyzed.get("analyzed") or {}
    fields = inner.get("fields") or analyzed.get("fields") or []
    sample_rows = (inner.get("preview_data") or analyzed.get("preview_data") or {}).get("sample_rows") or []
    loaded = _load_to_entity(target_entity or "products", fields, sample_rows, kw.get("request"))
    return _tag({
        "success": True,
        "data": {
            "filename": filename,
            "target_entity": target_entity,
            "fields_count": len(fields),
            "rows_loaded": loaded,
            "task_id": analyzed.get("task_id"),
            "template_id": (analyzed.get("template") or {}).get("id"),
        },
    })


_FIELD_EQUIVALENTS = {
    "products": {
        "name": ["产品名称", "名称", "品名", "entity_name"],
        "model_number": ["型号", "产品型号", "产品编码", "model"],
        "specification": ["规格", "规格型号", "spec"],
        "price": ["单价", "价格", "price"],
        "unit": ["单位", "计量单位"],
    },
    "customers": {
        "customer_name": ["客户名称", "购买单位", "单位名称", "厂名", "entity_name"],
        "contact_person": ["联系人", "联系人姓名"],
        "contact_phone": ["联系电话", "电话", "手机号"],
        "contact_address": ["地址", "联系地址"],
    },
}


def _infer_field_mapping(fields: list, target_entity: str) -> dict:
    """根据同义词表推断源列 → 目标字段的映射。"""
    if not target_entity or target_entity not in _FIELD_EQUIVALENTS:
        # 自动推断 scope
        field_labels = {str(f.get("label") or f.get("name") or "").strip().lower() for f in fields}
        for entity, equiv in _FIELD_EQUIVALENTS.items():
            for _, aliases in equiv.items():
                if any(str(a).lower() in field_labels for a in aliases):
                    target_entity = entity
                    break
            if target_entity:
                break
        if not target_entity:
            return {"_inferred_scope": ""}

    equiv = _FIELD_EQUIVALENTS.get(target_entity, {})
    mapping: dict[str, str] = {}
    for target_field, aliases in equiv.items():
        for f in fields:
            label = str(f.get("label") or f.get("name") or "").strip().lower()
            for alias in aliases:
                if alias.lower() == label or alias.lower() in label:
                    mapping[target_field] = str(f.get("label") or f.get("name") or "")
                    break
            if target_field in mapping:
                break
    mapping["_inferred_scope"] = target_entity
    return mapping


def _load_to_entity(entity: str, fields: list, sample_rows: list, request: Any) -> int:
    """将解析后的数据行通过 domain_handler 写入目标实体表。"""
    if not sample_rows:
        return 0

    mapping = _infer_field_mapping(fields, entity)
    entity = mapping.get("_inferred_scope") or entity
    count = 0

    for row in sample_rows:
        body: dict[str, Any] = {}
        for target_field, source_label in mapping.items():
            if target_field.startswith("_"):
                continue
            for key in (source_label, source_label.lower()):
                if key in row:
                    body[target_field] = row[key]
                    break

        if not body:
            continue

        try:
            if entity == "products":
                _products_add(request=request, body=body)
            elif entity == "customers":
                _customers_create(request=request, body=body)
            count += 1
        except Exception:
            pass

    return count


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
    ("wechat", "contacts_list"): _wechat_contacts_list,
    ("wechat", "contact_get"): _wechat_contact_get,
    ("wechat", "tasks"): _wechat_tasks,
    # ── ETL 数据对接中心 ──────────────────────────────────────────
    ("etl", "sources"): _etl_sources,
    ("etl", "preview"): _etl_preview,
    ("etl", "execute"): _etl_execute,
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
