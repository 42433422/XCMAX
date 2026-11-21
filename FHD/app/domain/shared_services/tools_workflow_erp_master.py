"""ERP 主数据域工作流路由：产品 / 物料。"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from app.domain.product.entities import TRIVIAL_MEASURE_UNITS
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _registered_router_products(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "import_price_list_template":
        from app.application.product_app_service import import_price_list_template

        return import_price_list_template(params, runtime_context)
    from app.services import get_products_service

    svc = get_products_service()
    explicit_measure_unit = str(params.get("unit") or params.get("measure_unit") or "").strip()
    legacy_unit_name = str(params.get("unit_name") or "").strip()
    legacy_measure_unit = legacy_unit_name if legacy_unit_name in TRIVIAL_MEASURE_UNITS else ""
    measure_unit = explicit_measure_unit or legacy_measure_unit or "个"
    model_number = (
        str(params.get("model_number") or params.get("product_code") or "").strip().upper()
    )
    product_name = str(params.get("product_name") or params.get("name") or "").strip()
    keyword = str(params.get("keyword") or product_name or model_number or "").strip()
    if action == "query":
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
        if isinstance(result, dict) and result.get("success") is False:
            return result
        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or not isinstance(result.get("data"), list)
            or any(not isinstance(row, dict) for row in result["data"])
        ):
            return {"success": False, "error_code": "product_query_invalid_response"}
        rows = result["data"]
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
        name_or_model = str(params.get("name_or_model") or product_name or model_number).strip()
        if not name_or_model:
            return {"success": False, "message": "缺少 name_or_model"}
        price = params.get("unit_price", params.get("price", 0.0))
        try:
            price = float(price)
        except RECOVERABLE_ERRORS:
            price = 0.0
        payload = dict(params)
        payload.update(
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
        create_result = svc.create_product(payload)
        if create_result.get("success"):
            return {**create_result, "success": True, "created": True, "raw": create_result}
        return {
            **create_result,
            "success": False,
            "message": create_result.get("message") or "创建失败",
        }
    if action == "update":
        product_id = int(params.get("id") or 0)
        payload = {k: v for k, v in params.items() if k != "id"}
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
        return cast("dict[Any, Any]", svc.update_product(product_id, payload))
    if action == "delete":
        return cast("dict[Any, Any]", svc.delete_product(int(params.get("id") or 0)))
    if action == "batch_create":
        raw_products = params.get("products") or []
        if not isinstance(raw_products, list) or not raw_products:
            return {"success": False, "message": "products 必须为非空数组"}
        return cast(
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
            except RECOVERABLE_ERRORS:
                skipped.append(raw_id)
        if not ids:
            return {"success": False, "message": "ids 须包含有效数字", "skipped": skipped}
        result = dict(svc.batch_delete_products(ids) or {})
        if skipped:
            result["skipped"] = list(result.get("skipped") or []) + skipped
        return result
    if action == "clear":
        listed = svc.get_products(page=1, per_page=100000) or {}
        rows = listed.get("data") if isinstance(listed, dict) else None
        ids = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                product_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if product_id > 0:
                ids.append(product_id)
        if not ids:
            return {"success": True, "message": "产品列表为空，无需清理", "deleted_count": 0}
        return dict(svc.batch_delete_products(ids) or {})
    return {"success": False, "message": f"未注册的 products 动作: {action}"}


def _registered_router_materials(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application import get_material_application_service

    svc = get_material_application_service()
    if action in ("list", "query"):
        result = svc.get_all_materials(
            search=str(params.get("search") or params.get("keyword") or "").strip(),
            category=str(params.get("category") or "").strip() or None,
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 20),
        )
        return cast("dict[Any, Any]", result)
    if action == "create":
        payload = dict(params or {})
        payload.setdefault(
            "name", str(payload.get("name") or payload.get("material_name") or "").strip()
        )
        payload.setdefault("material_code", f"MAT-{uuid.uuid4().hex[:12].upper()}")
        return cast("dict[Any, Any]", svc.create_material(payload))
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
    if action in {"batch_delete", "clear"}:
        if action == "clear":
            listed = svc.get_all_materials(page=1, per_page=100000)
            if isinstance(listed, dict) and listed.get("success") is False:
                return listed
            rows = listed.get("data") if isinstance(listed, dict) else None
            if (
                not isinstance(listed, dict)
                or listed.get("success") is not True
                or not isinstance(rows, list)
            ):
                return {
                    "success": False,
                    "message": "读取原材料列表失败",
                    "execution_state": "not_started",
                }
            ids = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    material_id = int(row.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if material_id > 0:
                    ids.append(material_id)
            if not ids:
                return {"success": True, "message": "原材料列表为空，无需清理", "deleted_count": 0}
        else:
            raw_ids = params.get("ids") or params.get("material_ids") or []
            ids = [int(x) for x in raw_ids if str(x).strip()]
        delete_receipt: dict[str, Any] | None
        try:
            delete_receipt = svc.batch_delete_materials(ids)
        except RECOVERABLE_ERRORS as err:
            logger.error("原材料 %s 执行异常：%s", action, err)
            delete_receipt = None
        if isinstance(delete_receipt, dict) and (
            delete_receipt.get("success") is False
            or (
                delete_receipt.get("success") is True
                and type(delete_receipt.get("deleted_count")) is int
                and 0 <= delete_receipt["deleted_count"] <= len(ids)
            )
        ):
            return delete_receipt
        return {
            "success": False,
            "message": "原材料删除结果待核对",
            "error_code": "material_delete_outcome_unknown",
            "execution_state": "unknown",
            "retryable": False,
            "reconciliation_required": True,
        }
    if action == "export":
        return cast(
            "dict[Any, Any]",
            svc.export_to_excel(
                search=str(params.get("search") or params.get("keyword") or "").strip() or None,
                category=str(params.get("category") or "").strip() or None,
                template_id=params.get("template_id"),
            ),
        )
    return {"success": False, "message": f"未注册的 materials 动作: {action}"}
