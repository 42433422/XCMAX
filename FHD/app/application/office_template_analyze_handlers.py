"""PPTX/PDF 模版 analyze 处理器（从 analyzer 拆出，控制巨型文件）。"""

from __future__ import annotations

import logging
from typing import Any

from app.services.document_templates.analyzer import (
    _cleanup_progress_tracking,
    _j,
    _mark_progress_completed,
    _safe_remove,
    _update_progress,
)
from app.services.document_templates.variables import (
    _get_template_scope_required_terms,
    _validate_required_terms,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def analyze_word_template(
    file_path: str,
    template_name: str,
    original_filename: str,
    task_id: str,
    template_scope: str = "",
) -> Any:
    try:
        from app.services.document_templates.analyzer import _extract_word_placeholder_fields

        _update_progress(task_id, 15, 1, "文件上传成功")
        _update_progress(task_id, 45, 2, "解析 Word 占位符...")

        fields, raw_placeholders, full_text = _extract_word_placeholder_fields(file_path)
        if not fields:
            _cleanup_progress_tracking(task_id)
            _safe_remove(file_path)
            return _j(
                {
                    "success": False,
                    "message": (
                        "未能从 Word 中识别占位符。请在正文、页眉或页脚中使用 "
                        "{{字段名}}、${字段名}、{% 字段名 %} 或 [[字段名]] 等形式后再上传。"
                    ),
                },
                400,
            )

        valid, missing_terms = _validate_required_terms({}, fields, template_scope)
        if not valid:
            _cleanup_progress_tracking(task_id)
            _safe_remove(file_path)
            return _j(
                {
                    "success": False,
                    "message": "模板缺少必备词条，请补全占位符后重试",
                    "required_terms": _get_template_scope_required_terms().get(template_scope, []),
                    "missing_terms": missing_terms,
                },
                400,
            )

        name = (
            template_name
            if template_name
            else original_filename.replace(".docx", "").replace(".doc", "")
        )

        snippet = full_text.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"

        _mark_progress_completed(task_id, 100, 3, "分析完成！")

        return _j(
            {
                "success": True,
                "task_id": task_id,
                "template_name": name,
                "template_type": "word",
                "fields": fields,
                "preview_data": {
                    "file_path": file_path,
                    "original_filename": original_filename,
                    "placeholders": raw_placeholders,
                    "text_snippet": snippet,
                },
            }
        )
    except RECOVERABLE_ERRORS as e:
        logger.error("分析 Word 模板失败：%s", e)
        _cleanup_progress_tracking(task_id)
        _safe_remove(file_path)
        return _j({"success": False, "message": "分析 Word 失败，请稍后重试"}, 500)


def analyze_pptx_template(
    file_path: str,
    template_name: str,
    original_filename: str,
    task_id: str,
    template_scope: str = "",
) -> Any:
    try:
        from app.application.office_template_media_bridge import build_pptx_template_analysis

        _update_progress(task_id, 15, 1, "文件上传成功")
        _update_progress(task_id, 45, 2, "解析 PPTX 正文与占位符...")
        analyzed = build_pptx_template_analysis(
            file_path,
            template_name=template_name,
            original_filename=original_filename,
        )
        if not analyzed.get("success"):
            _cleanup_progress_tracking(task_id)
            _safe_remove(file_path)
            return _j(
                {
                    "success": False,
                    "message": str(analyzed.get("message") or "PPTX 解析失败"),
                },
                400,
            )

        fields = analyzed.get("fields") if isinstance(analyzed.get("fields"), list) else []
        valid, missing_terms = _validate_required_terms({}, fields, template_scope)
        if not valid:
            _cleanup_progress_tracking(task_id)
            _safe_remove(file_path)
            return _j(
                {
                    "success": False,
                    "message": "模板缺少必备词条，请补全占位符后重试",
                    "required_terms": _get_template_scope_required_terms().get(template_scope, []),
                    "missing_terms": missing_terms,
                },
                400,
            )

        _mark_progress_completed(task_id, 100, 3, "分析完成！")
        return _j(
            {
                "success": True,
                "task_id": task_id,
                "template_name": analyzed.get("template_name"),
                "template_type": "pptx",
                "fields": fields,
                "preview_data": analyzed.get("preview_data") or {},
            }
        )
    except RECOVERABLE_ERRORS as e:
        logger.error("分析 PPTX 模板失败：%s", e)
        _cleanup_progress_tracking(task_id)
        _safe_remove(file_path)
        return _j({"success": False, "message": "分析 PPTX 失败，请稍后重试"}, 500)


def analyze_pdf_template(
    file_path: str,
    template_name: str,
    original_filename: str,
    task_id: str,
    template_scope: str = "",
) -> Any:
    try:
        from app.application.office_template_media_bridge import build_pdf_template_analysis

        _update_progress(task_id, 15, 1, "文件上传成功")
        _update_progress(task_id, 40, 2, "解析 PDF（文本 / OCR / 可选 VLM）...")
        analyzed = build_pdf_template_analysis(
            file_path,
            template_name=template_name,
            original_filename=original_filename,
        )
        if not analyzed.get("success"):
            _cleanup_progress_tracking(task_id)
            _safe_remove(file_path)
            return _j(
                {
                    "success": False,
                    "message": str(analyzed.get("message") or "PDF 解析失败"),
                    "warnings": analyzed.get("warnings") or [],
                    "vlm": analyzed.get("vlm"),
                },
                400,
            )

        fields = analyzed.get("fields") if isinstance(analyzed.get("fields"), list) else []
        valid, missing_terms = _validate_required_terms({}, fields, template_scope)
        if not valid:
            _cleanup_progress_tracking(task_id)
            _safe_remove(file_path)
            return _j(
                {
                    "success": False,
                    "message": "模板缺少必备词条，请补全占位符后重试",
                    "required_terms": _get_template_scope_required_terms().get(template_scope, []),
                    "missing_terms": missing_terms,
                },
                400,
            )

        _mark_progress_completed(task_id, 100, 3, "分析完成！")
        return _j(
            {
                "success": True,
                "task_id": task_id,
                "template_name": analyzed.get("template_name"),
                "template_type": "pdf",
                "fields": fields,
                "preview_data": analyzed.get("preview_data") or {},
            }
        )
    except RECOVERABLE_ERRORS as e:
        logger.error("分析 PDF 模板失败：%s", e)
        _cleanup_progress_tracking(task_id)
        _safe_remove(file_path)
        return _j({"success": False, "message": "分析 PDF 失败，请稍后重试"}, 500)
