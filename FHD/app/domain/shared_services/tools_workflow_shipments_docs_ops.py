"""单据工具域工作流路由：Excel 分析器 / 工具箱 / 标签与文档模板。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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


def _runtime_int(value: object) -> int | None:
    try:
        number = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return number or None


def _clear_document_templates(runtime_context: dict) -> tuple[dict, int]:
    """清空模板库；工具 worker 没有请求态，必须用运行时上下文显式绑定租户与账号。"""
    from app.application import get_template_app_service
    from app.infrastructure.tenant_scope import tenant_scope
    from app.legacy.routes.document_templates_compat import run_archive_template_delete

    tenant_id = _runtime_int(runtime_context.get("tenant_id"))
    owner_id = _runtime_int(runtime_context.get("user_id"))
    service = get_template_app_service()
    deleted = skipped = 0
    base_dir = str(runtime_context.get("template_base_dir") or "") or None
    starter_ids: list[str] = []
    builtin_paths: list[str] = []
    with tenant_scope(tenant_id):
        listed = service.get_templates(tenant_id=tenant_id) or {}
        rows = listed.get("templates") if isinstance(listed, dict) else None
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            template_id = str(item.get("id") or "").strip()
            if not template_id:
                continue
            if template_id.startswith("seed:"):
                starter_ids.append(template_id)
                continue
            if not (
                template_id.startswith("fs:")
                or template_id.startswith("db:")
                or template_id.isdigit()
            ):
                skipped += 1
                continue
            item_data, item_status = run_archive_template_delete(
                {"id": template_id}, base_dir=base_dir
            )
            if item_status == 200 and item_data.get("success"):
                deleted += 1
                continue
            # 安装目录里的内置表格不能删字节；改为按租户隐藏，保证列表真的被清空。
            installed_path = str(item.get("path") or item.get("file_path") or "").strip()
            if item_status == 403 and installed_path:
                builtin_paths.append(installed_path)
                continue
            skipped += 1
        hidden = service.hide_templates(ids=starter_ids, paths=builtin_paths)
        # 模板库页面实际列出的是审阅归档（elt_archive_assets），只清 elt_templates
        # 会让「清理后页面仍满屏」；同一动作必须一并清掉当前账号的归档资产。
        deleted_archives = service.purge_archive_assets(
            tenant_id=tenant_id, owner_id=owner_id
        )
    if deleted or hidden:
        message = f"已清理 {deleted} 个自定义模板，隐藏 {hidden} 个内置模板"
    elif skipped:
        message = f"模板库未能清理：{skipped} 个模板不支持删除"
    else:
        message = "模板库已经是空的"
    if deleted_archives:
        message += f"，同时清掉 {deleted_archives} 个已归档模板"
    if skipped and (deleted or hidden):
        message += f"，{skipped} 个未能清理"
    return (
        {
            "success": not skipped or bool(deleted or hidden),
            "message": message,
            "deleted_templates": deleted,
            "hidden_templates": hidden,
            "deleted_archives": deleted_archives,
            "skipped_templates": skipped,
        },
        200,
    )


def _publish_document_template_change(action: str, result: dict) -> None:
    """模板库改动后通知已挂载的页面刷新，避免聊天清理完成后界面仍显示旧列表。"""
    try:
        from app.infrastructure.chat_stream_lifetime import publish_stream_tool_record
        from app.utils.operational_errors import BOUNDARY_ERRORS

        publish_stream_tool_record(
            {
                "node_id": f"document-template-{action or 'change'}",
                "tool_id": "document_template",
                "action": str(action or ""),
                "phase": "finished",
                "success": bool(result.get("success")),
                "output_preview": str(result.get("message") or "")[:200],
            }
        )
    except BOUNDARY_ERRORS:  # 观测通道失败不能改变工具结果
        pass


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
    elif action == "clear":
        data, status_code = _clear_document_templates(runtime_context)
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
    _publish_document_template_change(action, result)
    return result
