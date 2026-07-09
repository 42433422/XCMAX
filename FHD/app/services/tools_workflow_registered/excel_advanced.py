"""Advanced excel/OCR/import workflow routers."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

def _registered_router_excel_analysis(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        excel_ctx = (
            runtime_context.get("excel_analysis")
            if isinstance(runtime_context.get("excel_analysis"), dict)
            else None
        )
        if not excel_ctx:
            last_ctx = runtime_context.get("last_excel_analysis_context")
            if isinstance(last_ctx, dict):
                excel_ctx = (
                    last_ctx.get("result") if isinstance(last_ctx.get("result"), dict) else last_ctx
                )
        if isinstance(excel_ctx, dict):
            file_path = str(excel_ctx.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": "excel_analysis 缺少 file_path 参数"}

    question = str(params.get("question") or "").strip()

    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (
            get_excel_analyzer_skill,
        )
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {"success": False, "message": "Excel Skill 未正确安装"}

    toolkit_skill = get_excel_toolkit_skill()
    analyzer_skill = get_excel_analyzer_skill()

    if action == "read":
        result = toolkit_skill.execute(file_path=file_path, action="view")
        return result

    if action == "structure":
        result = analyzer_skill.execute(file_path=file_path)
        return result

    if action == "statistics":
        view_result = toolkit_skill.execute(file_path=file_path, action="view")
        if not view_result.get("success"):
            return view_result
        content = view_result.get("content") or []
        total_rows = view_result.get("row_count") or 0
        all_values = []
        for row in content:
            for cell in row.get("cells") or []:
                v = cell.get("value")
                if v is not None:
                    try:
                        all_values.append(float(v))
                    except (TypeError, ValueError):
                        pass
        if all_values:
            stats = {
                "count": len(all_values),
                "sum": round(sum(all_values), 4),
                "avg": round(sum(all_values) / len(all_values), 4),
                "min": min(all_values),
                "max": max(all_values),
            }
        else:
            stats = {"count": 0}
        return {
            "success": True,
            "file_path": file_path,
            "total_rows": total_rows,
            "statistics": stats,
        }

    if action == "query":
        view_result = toolkit_skill.execute(file_path=file_path, action="view")
        if not view_result.get("success"):
            return view_result
        content = view_result.get("content") or []
        if not question:
            return {"success": True, "data": content[:20]}
        question_lower = question.lower()
        if any(kw in question_lower for kw in ["多少", "总和", "总计", "total", "sum"]):
            all_vals = []
            for row in content:
                for cell in row.get("cells") or []:
                    try:
                        all_vals.append(float(cell.get("value")))
                    except (TypeError, ValueError):
                        pass
            total = sum(all_vals) if all_vals else 0
            return {"success": True, "answer": f"所有数值总和为 {round(total, 4)}", "total": total}
        if any(kw in question_lower for kw in ["最大", "最高", "max"]):
            all_vals = [
                float(c.get("value"))
                for row in content
                for c in (row.get("cells") or [])
                if c.get("value") is not None
            ]
            try:
                mx = max(all_vals)
                return {"success": True, "answer": f"最大值为 {mx}", "max": mx}
            except ValueError:
                return {"success": True, "answer": "未找到数值"}
        return {
            "success": True,
            "data": content[:20],
            "message": f"已读取前 {min(20, len(content))} 行数据",
        }

    return {"success": False, "message": f"未知 excel_analysis action: {action}"}


def _registered_router_generate_office_document(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute":
        return {"success": False, "message": f"未知 generate_office_document action: {action}"}

    payload = dict(params or {})
    payload.setdefault("user_request", user_message)
    try:
        import json

        from app.application.tools.workflow import execute_workflow_tool

        raw = execute_workflow_tool(
            "generate_office_document",
            payload,
            workspace_root=runtime_context.get("workspace_root"),
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {"success": False, "message": str(raw)}
    except RECOVERABLE_ERRORS as err:
        logger.error("generate_office_document 执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"文档生成失败：{str(err)}"}


def _registered_router_excel_vector_index(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "execute":
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"success": False, "message": "缺少 file_path"}
        index_name = str(params.get("index_name") or "").strip() or None
        index_id = str(params.get("index_id") or "").strip() or None
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_ingest_app_service

            result = get_excel_vector_ingest_app_service().ingest_excel(
                file_path=file_path,
                index_name=index_name,
                index_id=index_id,
            )
        except RECOVERABLE_ERRORS as err:
            logger.error("excel_vector_index 执行失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}
        payload = dict(result or {})
        if payload.get("success") and payload.get("index_id"):
            payload["excel_vector_index_id"] = payload.get("index_id")
            payload["excel_index_id"] = payload.get("index_id")
        return payload

    if action == "query":
        index_id = str(params.get("index_id") or "").strip()
        query_text = str(params.get("query") or params.get("query_text") or "").strip()
        if not index_id:
            return {"success": False, "message": "缺少 index_id"}
        if not query_text:
            return {"success": False, "message": "缺少 query"}
        try:
            top_k = int(params.get("top_k", 5))
        except (TypeError, ValueError):
            top_k = 5
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_search_app_service

            return dict(
                get_excel_vector_search_app_service().query(
                    index_id=index_id,
                    query_text=query_text,
                    top_k=top_k,
                )
                or {}
            )
        except RECOVERABLE_ERRORS as err:
            logger.error("excel_vector_index query 失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}

    return {"success": False, "message": f"未知 excel_vector_index action: {action}"}


def _ocr_artifact_payload(
    *,
    text: str,
    file_path: str = "",
    structured_data: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: Any = 0,
) -> dict[str, Any]:
    return {
        "artifact_type": "ocr_text",
        "name": "ocr_result",
        "source": "ocr.recognize",
        "uri": file_path,
        "mime_type": "image/*",
        "summary": "OCR 解析结果",
        "fields": [
            {"name": key, "value": value}
            for key, value in dict(structured_data or {}).items()
            if value not in (None, "", [], {})
        ][:20],
        "preview": {
            "text": text[:1000],
            "confidence": confidence,
            "structured_data": dict(structured_data or {}),
            "analysis": dict(analysis or {}),
        },
        "metadata": {
            "parser_used": "ocr",
            "text": text,
            "success": True,
        },
    }


def _registered_router_ocr(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    try:
        from app.fastapi_routes.ocr import _get_ocr_service

        if action == "request":
            request_id = str(params.get("request_id") or "").strip()
            image_url = str(params.get("image_url") or "").strip()
            if not request_id:
                return {"success": False, "message": "缺少 request_id"}
            if not image_url:
                return {"success": False, "message": "缺少 image_url"}
            ocr_type = str(params.get("ocr_type") or "general").strip() or "general"
            user_id = str(
                params.get("user_id") or runtime_context.get("user_id") or "system"
            ).strip()
            from app.neuro_bus.domains.ocr_domain import get_ocr_domain

            ok = get_ocr_domain().emit_ocr_requested(
                request_id=request_id,
                image_url=image_url,
                ocr_type=ocr_type,
                user_id=user_id or "system",
            )
            return {
                "success": bool(ok),
                "message": "OCR 请求已发布" if ok else "OCR 请求发布失败",
                "request_id": request_id,
                "image_url": image_url,
                "ocr_type": ocr_type,
                "user_id": user_id or "system",
                "event": "ocr.requested",
                "published": bool(ok),
            }
        service = _get_ocr_service()
        if action == "recognize":
            file_path = str(params.get("file_path") or "").strip()
            if not file_path:
                return {"success": False, "message": "缺少 file_path"}
            result = dict(service.recognize_file(file_path) or {})
            if result.get("success"):
                text = str(result.get("text") or "")
                result.setdefault("artifacts", [])
                result["artifacts"] = list(result["artifacts"]) + [
                    _ocr_artifact_payload(
                        text=text,
                        file_path=str(result.get("file_path") or file_path),
                        confidence=result.get("confidence", result.get("ocr_confidence", 0)),
                    )
                ]
            return result

        if action == "extract":
            text = str(params.get("text") or "").strip()
            if not text:
                return {"success": False, "message": "缺少 text"}
            data = dict(service.extract_structured_data(text) or {})
            return {"success": True, "message": "提取成功", "data": data}

        if action == "analyze":
            text = str(params.get("text") or "").strip()
            if not text:
                return {"success": False, "message": "缺少 text"}
            data = dict(service.analyze_text(text) or {})
            return {"success": True, "message": "分析成功", "data": data}

        if action == "recognize_and_extract":
            file_path = str(params.get("file_path") or "").strip()
            if not file_path:
                return {"success": False, "message": "缺少 file_path"}
            recognize_result = dict(service.recognize_file(file_path) or {})
            if not recognize_result.get("success"):
                return recognize_result
            text = str(recognize_result.get("text") or "")
            structured_data = dict(service.extract_structured_data(text) or {})
            analysis = dict(service.analyze_text(text) or {})
            return {
                "success": True,
                "message": "识别和提取成功",
                "text": text,
                "data": structured_data,
                "analysis": analysis,
                "artifacts": [
                    _ocr_artifact_payload(
                        text=text,
                        file_path=str(recognize_result.get("file_path") or file_path),
                        structured_data=structured_data,
                        analysis=analysis,
                        confidence=analysis.get("confidence", 0),
                    )
                ],
            }
    except RECOVERABLE_ERRORS as err:
        logger.error("ocr 工具执行失败: %s", err, exc_info=True)
        return {"success": False, "message": str(err), "error_code": "ocr_exception"}

    return {"success": False, "message": f"未知 ocr action: {action}"}


def _execute_excel_import_records(records: list[dict[str, Any]]) -> dict:
    if not records:
        return {"success": False, "message": "没有可导入的记录"}

    try:
        from app.bootstrap import get_products_service

        products_service = get_products_service()
        customer_service = None
        customer_service_error = ""
        try:
            from app.bootstrap import get_customer_app_service

            customer_service = get_customer_app_service()
        except RECOVERABLE_ERRORS as customer_err:
            customer_service_error = str(customer_err)
            logger.warning("客户服务不可用，降级为仅产品入库: %s", customer_err)

        created_units = 0
        created_products = 0
        skipped_products = 0
        touched_units: set[str] = set()

        for row in records:
            unit_name = str(row.get("unit_name") or "").strip()
            product_name = str(row.get("product_name") or "").strip()
            model_number = str(row.get("model_number") or "").strip().upper()
            unit_price = float(row.get("unit_price") or 0.0)
            touched_units.add(unit_name)

            if customer_service is not None:
                matched = customer_service.match_purchase_unit(unit_name)
                if not matched:
                    create_unit = customer_service.create({"customer_name": unit_name})
                    if create_unit.get("success"):
                        created_units += 1

            exists_result = products_service.get_products(
                unit_name=unit_name,
                model_number=model_number or None,
                keyword=(product_name or model_number or None),
                page=1,
                per_page=5,
            )
            existed = False
            if exists_result.get("success"):
                rows_data = exists_result.get("data") or []
                for item in rows_data:
                    item_name = str(item.get("name") or item.get("product_name") or "").strip()
                    item_model = str(item.get("model_number") or "").strip().upper()
                    if model_number and item_model == model_number:
                        existed = True
                        break
                    if product_name and item_name == product_name:
                        existed = True
                        break
            if existed:
                skipped_products += 1
                continue

            create_product = products_service.create_product(
                {
                    "name": product_name or model_number,
                    "product_name": product_name or model_number,
                    "product_code": model_number or None,
                    "model_number": model_number or None,
                    "unit_price": unit_price,
                    "price": unit_price,
                    "unit": unit_name,
                }
            )
            if create_product.get("success"):
                created_products += 1

        return {
            "success": True,
            "message": "Excel 导入完成",
            "imported_count": len(records),
            "data": {
                "result": {
                    "records": len(records),
                    "touched_units": len(touched_units),
                    "created_units": created_units,
                    "created_products": created_products,
                    "skipped_products": skipped_products,
                    "unit_service_available": customer_service is not None,
                    "unit_service_error": customer_service_error,
                }
            },
        }
    except RECOVERABLE_ERRORS as err:
        logger.error("Excel 导入执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"导入执行失败：{str(err)}"}


def _registered_router_excel_import(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "execute_import":
        pending_import_id = str(params.get("pending_import_id") or "").strip()
        if not pending_import_id:
            return {"success": False, "message": "缺少 pending_import_id 参数"}

        from app.application import get_ai_chat_app_service

        ai_chat_service = get_ai_chat_app_service()
        pending_imports = getattr(ai_chat_service, "_pending_excel_imports", {})
        import_data = pending_imports.get(pending_import_id)

        if not import_data:
            return {"success": False, "message": "未找到待处理的导入数据或已过期"}

        records = import_data.get("records", [])
        if not isinstance(records, list):
            return {"success": False, "message": "待导入记录格式错误"}
        result = _execute_excel_import_records([r for r in records if isinstance(r, dict)])
        if result.get("success"):
            pending_imports.pop(pending_import_id, None)
        return result

    if action == "import_records":
        records = params.get("records")
        if not isinstance(records, list):
            return {"success": False, "message": "records 必须是数组"}
        return _execute_excel_import_records([r for r in records if isinstance(r, dict)])

    return {"success": False, "message": f"未知 excel_import action: {action}"}


def _registered_router_unit_products_import(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute_import":
        return {"success": False, "message": f"未知 unit_products_import action: {action}"}

    saved_name = str(params.get("saved_name") or "").strip()
    unit_name = str(params.get("unit_name") or "").strip()
    if not saved_name:
        return {"success": False, "message": "缺少 saved_name 参数"}
    if not unit_name:
        return {"success": False, "message": "缺少 unit_name 参数"}

    try:
        from app.application import get_unit_products_import_app_service

        service = get_unit_products_import_app_service()
        result = service.import_unit_products(
            saved_name=saved_name,
            unit_name=unit_name,
            create_purchase_unit=bool(params.get("create_purchase_unit", True)),
            skip_duplicates=bool(params.get("skip_duplicates", True)),
        )
        if result.get("success"):
            created_unit = bool(result.get("created_unit", False))
            imported_count = int(result.get("created_products") or result.get("imported") or 0)
            result.setdefault("created_customers", 1 if created_unit else 0)
            result.setdefault("created_products", imported_count)
            data = result.get("data")
            if not isinstance(data, dict):
                data = {}
            data.setdefault("unit_name", unit_name)
            data.setdefault("saved_name", saved_name)
            data.setdefault("created_unit", created_unit)
            data.setdefault("imported", int(result.get("imported") or imported_count))
            data.setdefault("skipped_duplicates", int(result.get("skipped_duplicates") or 0))
            result["data"] = data
        return result
    except RECOVERABLE_ERRORS as err:
        logger.error("unit products 导入执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"导入执行失败：{str(err)}"}

