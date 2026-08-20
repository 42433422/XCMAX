# mypy: disable-error-code="no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _registered_router_normal_slot_dispatch(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.normal_chat_dispatch import (
        run_normal_slot_product_query_from_message,
        run_normal_slot_shipment_preview,
    )

    if action == "product_query":
        text = user_message or str(params.get("message") or "").strip()
        return run_normal_slot_product_query_from_message(text)
    if action == "shipment_preview":
        order_text = str(params.get("order_text") or user_message or "").strip()
        return run_normal_slot_shipment_preview(order_text)
    return {"success": False, "message": f"未注册的 normal_slot_dispatch 动作: {action}"}


def _registered_router_customers(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_customer_route":
        from app.fastapi_routes.domains.customer import routes as customer_routes

        return customer_routes._execute_customers_route_action(action, dict(params or {}))
    from app.application import get_customer_app_service

    svc = get_customer_app_service()
    unit_name = str(
        params.get("unit_name") or params.get("customer_name") or params.get("name") or ""
    ).strip()
    if action in {"create", "ensure_exists", "upsert"}:
        from app.services.business_db_customer_mutations import execute_customer_create_like

        return execute_customer_create_like(
            action, params, svc=svc, resolve_targets=_facade()._business_db_target_candidates
        )
    if action == "query":
        keyword = str(params.get("keyword") or unit_name or "").strip()
        result = svc.get_all(keyword=keyword, page=1, per_page=20)
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
        }
    if action == "update":
        customer_id = int(params.get("id") or params.get("customer_id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 id"}
        payload = {
            "customer_name": unit_name,
            "contact_person": params.get("contact_person", ""),
            "contact_phone": params.get("contact_phone", ""),
            "contact_address": params.get("contact_address", params.get("address", "")),
        }
        payload = {k: v for k, v in payload.items() if v not in (None, "")}
        update_result = svc.update(customer_id, payload)
        if update_result.get("success"):
            return {"success": True, "data": update_result.get("data", {})}
        return {"success": False, "message": update_result.get("message") or "更新失败"}
    if action == "delete":
        customer_id = int(params.get("id") or params.get("customer_id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 id"}
        return dict(svc.delete(customer_id, force=bool(params.get("force", False))) or {})
    if action == "batch_delete":
        raw_ids = params.get("ids") or params.get("customer_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return {"success": False, "message": "ids 须为非空数组"}
        ids: list[int] = []
        skipped: list[str] = []
        for raw in raw_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                skipped.append(str(raw))
        if not ids:
            return {"success": False, "message": "ids 须包含有效数字"}
        result = dict(svc.batch_delete(ids, force=bool(params.get("force", False))) or {})
        if skipped:
            result["skipped"] = list(result.get("skipped") or []) + skipped
        return result
    if action == "add_address":
        payload = dict(params or {})
        return dict(svc.add_address(payload) or {})
    if action == "set_credit_limit":
        customer_id = int(params.get("customer_id") or params.get("id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 customer_id"}
        return dict(
            svc.set_credit_limit(
                customer_id, params.get("credit_limit") or params.get("limit") or 0
            )
            or {}
        )
    if action == "get_addresses":
        customer_id = int(params.get("customer_id") or params.get("id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 customer_id"}
        return dict(svc.get_addresses(customer_id) or {})
    return {"success": False, "message": f"未注册的 customers 动作: {action}"}


def _registered_router_products(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.normal_chat_dispatch import run_workflow_products_query_normal_profile

    if str(runtime_context.get("service_source") or "") == "fastapi_product_compat_route":
        import importlib

        route_module = str(
            runtime_context.get("route_module") or "app.legacy.routes.product.compat_routes"
        )
        module = importlib.import_module(route_module)
        execute_action = module._execute_products_compat_action
        return dict(execute_action(action, params) or {})
    is_fastapi_product_route = (
        str(runtime_context.get("service_source") or "") == "fastapi_product_route"
    )
    if is_fastapi_product_route:
        from app.fastapi_routes.domains.product import routes as product_routes

        svc = product_routes._svc()
    else:
        from app.services import get_products_service

        svc = get_products_service()
    explicit_measure_unit = str(params.get("unit") or params.get("measure_unit") or "").strip()
    legacy_unit_name = str(params.get("unit_name") or "").strip()
    try:
        from app.infrastructure.repositories.product_query_helpers import TRIVIAL_MEASURE_UNITS

        legacy_measure_unit = legacy_unit_name if legacy_unit_name in TRIVIAL_MEASURE_UNITS else ""
    except _facade().RECOVERABLE_ERRORS:
        legacy_measure_unit = (
            legacy_unit_name if legacy_unit_name in {"个", "件", "桶", "箱", "kg", "公斤"} else ""
        )
    measure_unit = explicit_measure_unit or legacy_measure_unit or "个"
    model_number = str(params.get("model_number") or "").strip().upper()
    product_name = str(params.get("product_name") or params.get("name") or "").strip()
    keyword = str(params.get("keyword") or product_name or model_number or "").strip()
    if action == "query":
        if profile == "normal":
            return run_workflow_products_query_normal_profile(
                user_message, node_params=params, per_page=20
            )
        result = svc.get_products(
            unit_name=measure_unit if explicit_measure_unit or legacy_measure_unit else None,
            model_number=model_number or None,
            keyword=keyword or None,
            page=1,
            per_page=20,
        )
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
        }
    if action == "exists":
        result = svc.get_products(
            unit_name=measure_unit if explicit_measure_unit or legacy_measure_unit else None,
            model_number=model_number or None,
            keyword=keyword or None,
            page=1,
            per_page=10,
        )
        rows = result.get("data") or []
        exists = False
        for row in rows:
            row_name = str(row.get("name") or row.get("product_name") or "").strip()
            row_model = str(row.get("model_number") or "").strip().upper()
            if model_number and row_model == model_number:
                exists = True
                break
            if product_name and row_name == product_name:
                exists = True
                break
        return {"success": True, "exists": exists, "matched_count": len(rows)}
    if action == "create":
        if str(runtime_context.get("service_source") or "") == "fastapi_product_route":
            payload = dict(params or {})
            return _facade().cast("dict[Any, Any]", svc.create_product(payload))
        name_or_model = str(params.get("name_or_model") or product_name or model_number).strip()
        if not name_or_model:
            return {"success": False, "message": "缺少 name_or_model"}
        price = params.get("unit_price", params.get("price", 0.0))
        try:
            price = float(price)
        except _facade().RECOVERABLE_ERRORS:
            price = 0.0
        create_result = svc.create_product(
            {
                "name": name_or_model,
                "product_name": name_or_model,
                "product_code": model_number or None,
                "model_number": model_number or None,
                "specification": params.get("specification"),
                "unit_price": price,
                "price": price,
                "unit": measure_unit,
            }
        )
        if create_result.get("success"):
            return {"success": True, "created": True, "raw": create_result}
        return {"success": False, "message": create_result.get("message") or "创建失败"}
    if action == "update":
        product_id = int(params.get("id") or 0)
        payload = {k: v for k, v in params.items() if k != "id"}
        if is_fastapi_product_route:
            return _facade().cast("dict[Any, Any]", svc.update_product(product_id, payload))
        if "product_name" in payload and "name" not in payload:
            payload["name"] = payload.pop("product_name")
        if "unit_price" in payload and "price" not in payload:
            payload["price"] = payload.pop("unit_price")
        if "product_code" in payload and "model_number" not in payload:
            payload["model_number"] = payload.pop("product_code")
        if "measure_unit" in payload and "unit" not in payload:
            payload["unit"] = payload.pop("measure_unit")
        legacy_update_unit = str(payload.pop("unit_name", "") or "").strip()
        if legacy_update_unit and "unit" not in payload:
            payload["unit"] = (
                legacy_update_unit
                if legacy_update_unit in {"个", "件", "桶", "箱", "kg", "公斤", "吨", "米", "升"}
                else "个"
            )
        return _facade().cast("dict[Any, Any]", svc.update_product(product_id, payload))
    if action == "delete":
        return _facade().cast("dict[Any, Any]", svc.delete_product(int(params.get("id") or 0)))
    if action == "batch_create":
        raw_products = params.get("products") or []
        if not isinstance(raw_products, list) or not raw_products:
            return {"success": False, "message": "products 必须为非空数组"}
        return _facade().cast(
            "dict[Any, Any]",
            svc.batch_add_products([dict(item) for item in raw_products if isinstance(item, dict)]),
        )
    if action == "batch_delete":
        raw_ids = params.get("ids") or params.get("product_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return {"success": False, "message": "ids 须为非空数组"}
        ids: list[int] = []
        skipped: list = []
        for raw_id in raw_ids:
            try:
                ids.append(int(raw_id))
            except _facade().RECOVERABLE_ERRORS:
                skipped.append(raw_id)
        if not ids:
            return {"success": False, "message": "ids 须包含有效数字", "skipped": skipped}
        batch_delete = getattr(svc, "batch_delete_products", None)
        if callable(batch_delete):
            result = dict(batch_delete(ids) or {})
        else:
            result = dict(svc.batch_delete(ids) or {})
        if skipped:
            result["skipped"] = list(result.get("skipped") or []) + skipped
        return result
    return {"success": False, "message": f"未注册的 products 动作: {action}"}


def _registered_router_materials(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_materials_route":
        from app.fastapi_routes import materials as materials_route

        svc = materials_route._svc()
    else:
        from app.application import get_material_application_service

        svc = get_material_application_service()
    if action in ("list", "query"):
        result = svc.get_all_materials(
            search=str(params.get("search") or params.get("keyword") or "").strip(),
            category=str(params.get("category") or "").strip() or None,
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 20),
        )
        return _facade().cast("dict[Any, Any]", result)
    if action == "create":
        payload = dict(params or {})
        payload.setdefault(
            "name", str(payload.get("name") or payload.get("material_name") or "").strip()
        )
        payload.setdefault("material_code", f"MAT-{_facade().uuid.uuid4().hex[:12].upper()}")
        return _facade().cast("dict[Any, Any]", svc.create_material(payload))
    if action == "update":
        material_id = int(params.get("id") or 0)
        payload = {k: v for k, v in params.items() if k != "id"}
        result = svc.update_material(material_id, **payload)
        if isinstance(result, dict):
            return result
        return {"success": True, "message": "更新成功", "data": {"id": material_id}}
    if action == "delete":
        material_id = int(params.get("id") or 0)
        result = svc.delete_material(material_id)
        if isinstance(result, dict):
            result.setdefault("message", "删除成功")
            return result
        return {"success": True, "message": "删除成功", "data": {"id": material_id}}
    if action == "batch_delete":
        raw_ids = params.get("ids") or params.get("material_ids") or []
        ids = [int(x) for x in raw_ids if str(x).strip()]
        try:
            result = svc.batch_delete_materials(ids)
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error("批量删除原材料时 service 执行异常：%s", err)
            return {
                "success": True,
                "message": f"已删除 {len(ids)} 条记录",
                "deleted_count": len(ids),
                "warning": str(err),
            }
        if isinstance(result, dict):
            result.setdefault("success", True)
            result.setdefault("deleted_count", len(ids))
            return result
        return {"success": True, "message": f"已删除 {len(ids)} 条记录", "deleted_count": len(ids)}
    if action == "export":
        return _facade().cast(
            "dict[Any, Any]",
            svc.export_to_excel(
                search=str(params.get("search") or params.get("keyword") or "").strip() or None,
                category=str(params.get("category") or "").strip() or None,
                template_id=params.get("template_id"),
            ),
        )
    return {"success": False, "message": f"未注册的 materials 动作: {action}"}
