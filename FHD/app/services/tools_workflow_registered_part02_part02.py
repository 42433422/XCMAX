"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _registered_router_business_event(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "print_label":
        from app.neuro_bus.domains.print_domain import get_print_domain

        job_id = str(params.get("job_id") or "").strip() or str(_facade().uuid.uuid4())
        document_name = str(params.get("document_name") or "document").strip() or "document"
        printer_id = str(params.get("printer_id") or "default").strip() or "default"
        copies = max(1, int(params.get("copies") or 1))
        ok = get_print_domain().emit_job_submitted(
            job_id=job_id, document_name=document_name, printer_id=printer_id, copies=copies
        )
        return {"success": bool(ok), "job_id": job_id, "event": "print.job.submitted"}
    if action == "inventory_update":
        from app.neuro_bus.domains.inventory_domain import get_inventory_domain

        ok = get_inventory_domain().emit_stock_changed(
            product_id=str(params.get("product_id") or "").strip(),
            warehouse_id=str(params.get("warehouse_id") or "default").strip() or "default",
            delta=int(params.get("delta") or 0),
            reason=str(params.get("reason") or "api_business"),
            new_quantity=int(params.get("new_quantity") or 0),
        )
        return {"success": bool(ok), "event": "inventory.changed"}
    if action == "shipment_create":
        from app.neuro_bus.application_neuro_bridge import publish_neuro_event

        payload = {
            "unit_name": str(params.get("unit_name") or "").strip(),
            "items": list(params.get("items") or []),
            "contact_person": str(params.get("contact_person") or "").strip(),
            "contact_phone": str(params.get("contact_phone") or "").strip(),
        }
        ok = publish_neuro_event("shipment.created", payload, "shipment")
        if not ok:
            _facade().logger.info(
                "business shipment.create: neuro publish skipped or failed (stack off?)"
            )
        return {"success": bool(ok), "published": ok, "event": "shipment.created"}
    return {"success": False, "message": f"未知 business_event action: {action}"}


def _registered_router_system_maintenance(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action in {"set_default_printer", "enable_startup", "disable_startup"}:
        from app.application.facades.session_facade import get_system_service

        system_svc = get_system_service()
        if action == "set_default_printer":
            result = dict(
                system_svc.set_default_printer(str(params.get("printer_name") or "").strip())
            )
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        if action == "enable_startup":
            result = dict(system_svc.enable_startup())
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        result = dict(system_svc.disable_startup())
        result["http_status_code"] = 200 if result.get("success") else 500
        return result
    if action in {"backup_database", "delete_database_backup", "restore_database"}:
        from app.application.facades.session_facade import get_database_service

        database_svc = get_database_service()
        if action == "backup_database":
            result = dict(database_svc.backup_database())
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        if action == "delete_database_backup":
            result = dict(database_svc.delete_backup(str(params.get("backup_file") or "").strip()))
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        result = dict(database_svc.restore_database(str(params.get("backup_file") or "").strip()))
        result["http_status_code"] = 200 if result.get("success") else 400
        return result
    if action == "clear_performance_cache":
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return {"success": False, "message": "Redis 缓存未初始化", "http_status_code": 503}
        pattern = str(params.get("pattern") or "").strip()
        if pattern:
            cleared = optimizer.redis_cache.clear_pattern(pattern)
            message = f"已清除模式 '{pattern}' 的缓存 ({cleared} 个键)"
        else:
            optimizer.redis_cache.clear_local_cache()
            message = "已清除本地缓存"
        return {"success": True, "message": message, "http_status_code": 200}
    if action == "invalidate_performance_cache":
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return {"success": False, "message": "Redis 缓存未初始化", "http_status_code": 503}
        keys = list(params.get("keys") or [])
        deleted = optimizer.redis_cache.delete(*keys)
        return {
            "success": True,
            "data": {"deleted_count": deleted, "requested_keys": len(keys)},
            "message": f"已删除 {deleted} 个缓存键",
            "http_status_code": 200,
        }
    if action == "reinitialize_performance":
        from app.utils.performance.performance_initializer import init_performance_optimization

        optimizer = init_performance_optimization()
        return {
            "success": True,
            "message": "性能优化系统已重新初始化",
            "data": optimizer.get_status(),
            "http_status_code": 200,
        }
    return {"success": False, "message": f"未知 system_maintenance action: {action}"}


def _registered_router_excel_analyzer(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "analyze":
        return {"success": False, "message": f"未知 excel_analyzer action: {action}"}
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": "excel_analyzer.analyze 缺少 file_path 参数"}
    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (
            get_excel_analyzer_skill,
        )
    except ImportError:
        return {"success": False, "message": "Excel Analyzer Skill 未正确安装"}
    result = get_excel_analyzer_skill().execute(
        file_path=file_path,
        sheet_name=params.get("sheet_name"),
        output_json=params.get("output_json"),
    )
    if isinstance(result, dict):
        result.setdefault("file_path", file_path)
    return result if isinstance(result, dict) else {"success": False, "message": "技能返回值无效"}


def _registered_router_excel_toolkit(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    normalized = str(action or "view").strip().lower() or "view"
    if normalized not in {"view", "merged", "styles", "structure"}:
        return {"success": False, "message": f"未知 excel_toolkit action: {action}"}
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": f"excel_toolkit.{normalized} 缺少 file_path 参数"}
    try:
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {"success": False, "message": "Excel Toolkit Skill 未正确安装"}
    kwargs = {}
    if params.get("max_rows") is not None:
        kwargs["max_rows"] = params.get("max_rows")
    result = get_excel_toolkit_skill().execute(
        file_path=file_path, action=normalized, sheet_name=params.get("sheet_name"), **kwargs
    )
    if isinstance(result, dict):
        result.setdefault("file_path", file_path)
    return result if isinstance(result, dict) else {"success": False, "message": "技能返回值无效"}


def _registered_router_label_template_generator(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute":
        return {"success": False, "message": f"未知 label_template_generator action: {action}"}
    image_path = str(params.get("image_path") or "").strip()
    if not image_path:
        return {
            "success": False,
            "message": "label_template_generator.execute 缺少 image_path 参数",
        }
    try:
        from app.infrastructure.skills.label_template_generator import (
            get_label_template_generator_skill,
        )
    except ImportError:
        return {"success": False, "message": "Label Template Generator Skill 未正确安装"}
    result = get_label_template_generator_skill().execute(
        image_path=image_path,
        class_name=params.get("class_name") or "LabelTemplateGenerator",
        output_file=params.get("output_file"),
        enable_ocr=bool(params.get("enable_ocr", True)),
        verbose=bool(params.get("verbose", False)),
    )
    if isinstance(result, dict):
        result.setdefault("image_path", image_path)
    return result if isinstance(result, dict) else {"success": False, "message": "技能返回值无效"}


def _registered_router_document_template(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    payload = dict(params or {})
    if action == "create":
        from app.legacy.routes.document_templates_compat import run_archive_template_create

        data, status_code = run_archive_template_create(payload)
    elif action == "update":
        from app.legacy.routes.document_templates_compat import run_archive_template_update

        data, status_code = run_archive_template_update(payload)
    elif action == "delete":
        from app.legacy.routes.document_templates_compat import run_archive_template_delete

        data, status_code = run_archive_template_delete(
            payload, base_dir=str(runtime_context.get("template_base_dir") or "") or None
        )
    elif action in ("ingest", "upload"):
        from app.application.office_template_ingest_app_service import (
            ingest_office_bytes_to_template_library,
            ingest_office_path_to_template_library,
        )

        file_path = str(payload.get("file_path") or payload.get("original_file_path") or "").strip()
        file_body = payload.get("file_body")
        template_name = str(payload.get("template_name") or payload.get("name") or "").strip()
        template_scope = str(
            payload.get("template_scope") or payload.get("business_scope") or ""
        ).strip()
        source = (
            str(payload.get("source") or "document_template_ingest").strip()
            or "document_template_ingest"
        )
        if isinstance(file_body, (bytes, bytearray)):
            data, status_code = ingest_office_bytes_to_template_library(
                file_body=bytes(file_body),
                filename=str(payload.get("filename") or "upload.bin"),
                template_name=template_name,
                template_scope=template_scope,
                source=source,
            )
        elif file_path:
            data, status_code = ingest_office_path_to_template_library(
                file_path, template_name=template_name, template_scope=template_scope, source=source
            )
        else:
            return {"success": False, "message": "缺少 file_path 或 file_body"}
    else:
        return {"success": False, "message": f"未知 document_template action: {action}"}
    result = dict(data or {})
    result["http_status_code"] = int(status_code or (200 if result.get("success") else 400))
    return result
