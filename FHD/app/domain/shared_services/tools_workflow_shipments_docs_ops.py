"""单据工具域工作流路由：Excel 分析器 / 工具箱 / 标签与文档模板。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

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


def _clear_document_templates(runtime_context: dict) -> tuple[dict, int]:
    from app.application.template_app_service import clear_document_templates

    return clear_document_templates(runtime_context)


def _read_owned_template_input(file_path: str, runtime_context: dict) -> bytes | None:
    """Verify staged input ownership and content; ordinary workspace files retain their gate."""
    from app.utils.path_io.upload_helpers import (
        _capability_upload_directory,
        get_upload_dir,
        read_capability_upload,
    )

    root = Path(os.path.abspath(get_upload_dir())) / "capability-inputs"
    requested = Path(os.path.abspath(file_path))
    resolved = requested.resolve()
    try:
        relative = requested.relative_to(root)
    except ValueError:
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            return None
    if len(relative.parts) != 3:
        raise PermissionError("模板上传路径无效")
    namespace, _, filename = relative.parts
    expected = _capability_upload_directory(runtime_context, namespace) / filename
    if resolved != expected.resolve():
        raise PermissionError("模板上传不属于当前账号")
    source = Path(filename)
    return read_capability_upload(
        {"saved_name": filename, "sha256": source.stem},
        runtime_context,
        namespace=namespace,
        suffixes=frozenset({source.suffix.lower()}),
    )


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

        data, status_code = run_archive_template_delete(payload)
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
        if file_path:
            try:
                verified_body = _read_owned_template_input(file_path, runtime_context)
            except (ValueError, PermissionError, OSError):
                return {
                    "success": False,
                    "error_code": "template_input_unavailable",
                    "message": "原始模板输入不可用或已变化，请重新上传",
                    "execution_status": "not_started",
                    "retryable": False,
                }
            if verified_body is not None:
                file_body = verified_body
                payload.setdefault("filename", Path(file_path).name)
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
    from app.application.template_app_service import publish_document_template_change

    result = dict(data or {})
    result["http_status_code"] = int(status_code or (200 if result.get("success") else 400))
    publish_document_template_change(action, result)
    return result
