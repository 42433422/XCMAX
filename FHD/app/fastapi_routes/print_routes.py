"""打印 API（继承自归档 print 蓝图的端点契约）。"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.fastapi_routes.print_agent_helpers import (
    run_print_agent as _run_print_agent,
)
from app.infrastructure.auth.business_scope_gate import require_print_permission
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.security.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)

logger = logging.getLogger(__name__)

from app.fastapi_routes.label_jobs import router as label_jobs_router

router = APIRouter(
    prefix="/api/print",
    tags=["print"],
    dependencies=[Depends(require_print_permission())],
)
router.include_router(label_jobs_router)

__all__ = [
    "_run_print_agent",
    "router",
]

_PRINT_UNAVAILABLE = "打印服务暂时不可用，请稍后重试"


def _resolve_print_input_path(file_arg: object) -> Path | None:
    """Resolve a print input below app-owned or explicitly configured roots."""
    from app.utils.path_io.path_utils import get_app_data_dir

    roots = {
        Path(get_app_data_dir()).resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    configured = os.environ.get("XCAGI_PRINT_ALLOWED_ROOTS", "")
    roots.update(
        Path(value.strip()).expanduser().resolve()
        for value in configured.split(os.pathsep)
        if value.strip()
    )
    try:
        candidate = resolve_under_allowed_dirs(str(file_arg or ""), sorted(roots, key=str))
    except (OSError, UnsafeDownloadPathError):
        return None
    return candidate if candidate.is_file() else None


def _svc():
    # 仅打印相关接口应保持轻量，避免 `import app.services` 触发重型依赖/循环导入导致卡死。
    from app.application.facades.print_facade import printer_service

    return printer_service


@router.get("/printers")
def get_printers():
    try:
        result = _svc().get_printers()
        return JSONResponse(result)
    except RECOVERABLE_ERRORS:
        logger.exception("获取打印机列表失败")
        return JSONResponse(
            {
                "success": False,
                "message": _PRINT_UNAVAILABLE,
                "printers": [],
            },
            status_code=500,
        )


@router.get("/printer-selection")
def get_printer_selection():
    try:
        selection = _svc().get_printer_selection()
        return JSONResponse({"success": True, "selection": selection})
    except RECOVERABLE_ERRORS:
        logger.exception("获取打印机选择失败")
        return JSONResponse(
            {"success": False, "message": _PRINT_UNAVAILABLE},
            status_code=500,
        )


@router.put("/printer-selection")
def save_printer_selection(
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
):
    try:
        result, status = _run_print_agent(
            request=request,
            action="save_printer_selection",
            params={key: data[key] for key in ("document_printer", "label_printer") if key in data},
            route_path="/api/print/printer-selection",
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("保存打印机选择失败")
        return JSONResponse(
            {"success": False, "message": _PRINT_UNAVAILABLE},
            status_code=500,
        )


@router.get("/default")
def get_default_printer():
    try:
        result = _svc().get_default_printer()
        return JSONResponse(result)
    except RECOVERABLE_ERRORS:
        logger.exception("获取默认打印机失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.post("/document")
def print_document(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        file_path = data.get("file_path", "")
        use_automation = data.get("use_automation", False)
        if not file_path:
            return JSONResponse({"success": False, "message": "文件路径不能为空"}, status_code=400)
        resolved_file = _resolve_print_input_path(file_path)
        if resolved_file is None:
            return JSONResponse({"success": False, "message": "文件不存在"}, status_code=400)
        result, status = _run_print_agent(
            request=request,
            action="print_document",
            params={
                "file_path": str(resolved_file),
                **({"printer_name": data["printer_name"]} if "printer_name" in data else {}),
                "use_automation": use_automation,
            },
            route_path="/api/print/document",
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("打印文档失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.post("/label")
def print_label(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        file_path = data.get("file_path", "")
        copies = data.get("copies", 1)
        try:
            copies = int(copies)
        except RECOVERABLE_ERRORS:
            copies = 0
        if not file_path:
            return JSONResponse({"success": False, "message": "文件路径不能为空"}, status_code=400)
        if copies < 1 or copies > 100:
            return JSONResponse(
                {"success": False, "message": "打印份数必须在1-100之间"}, status_code=400
            )

        result, status = _run_print_agent(
            request=request,
            action="print_label",
            params={
                "file_path": str(file_path),
                **({"printer_name": data["printer_name"]} if "printer_name" in data else {}),
                "copies": copies,
            },
            route_path="/api/print/label",
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("打印标签失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.post("/test")
def test_printer_post(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        printer_name = data.get("printer_name", "")
        if not printer_name:
            return JSONResponse(
                {"success": False, "message": "打印机名称不能为空"}, status_code=400
            )
        result, status = _run_print_agent(
            request=request,
            action="test",
            params={"printer_name": str(printer_name)},
            route_path="/api/print/test",
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("测试打印机失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.get("/validate")
def validate_printer_separation():
    try:
        result = _svc().validate_printer_separation()
        return JSONResponse({"success": True, **result})
    except RECOVERABLE_ERRORS:
        logger.exception("验证打印机分离失败")
        return JSONResponse(
            {"success": False, "valid": False, "error": _PRINT_UNAVAILABLE},
            status_code=500,
        )


@router.get("/document-printer")
def get_document_printer():
    try:
        printer = _svc().get_document_printer()
        if printer:
            return JSONResponse({"success": True, "printer": printer})
        return JSONResponse({"success": False, "message": "未找到发货单打印机"})
    except RECOVERABLE_ERRORS:
        logger.exception("获取发货单打印机失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.get("/label-printer")
def get_label_printer():
    try:
        printer = _svc().get_label_printer()
        if printer:
            return JSONResponse({"success": True, "printer": printer})
        return JSONResponse({"success": False, "message": "未找到标签打印机"})
    except RECOVERABLE_ERRORS:
        logger.exception("获取标签打印机失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.get("/test")
def test_print_service_get():
    return JSONResponse(
        {
            "success": True,
            "message": "打印服务运行正常",
        }
    )


@router.post("/workflow/label-print/dispatch")
def workflow_label_print_dispatch(
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
):
    """同一 client key 复用持久工具回执；未知结果不能重复打印或改称成功。"""
    idempotency_key = str(data.get("idempotency_key") or "").strip()
    model_number = str(data.get("model_number") or "").strip()
    quantity = max(1, min(100, int(data.get("quantity") or 1)))

    if not model_number:
        return JSONResponse({"success": False, "message": "model_number 不能为空"}, status_code=400)

    try:
        result, status = _run_print_agent(
            request=request,
            action="workflow_label_dispatch",
            params={
                "model_number": model_number,
                "quantity": quantity,
                "idempotency_key": idempotency_key,
            },
            route_path="/api/print/workflow/label-print/dispatch",
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("workflow_label_print_dispatch 失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.get("/list_labels")
def list_labels(limit: int = Query(default=2, ge=1, le=20)):
    try:
        from app.utils.path_io.path_utils import get_resource_path

        labels_dir = get_resource_path("ai_assistant", "商标导出")
        if not os.path.isdir(labels_dir):
            return JSONResponse(
                {
                    "success": True,
                    "labels": [],
                    "message": "商标导出目录不存在",
                }
            )

        image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}
        labels: list[dict[str, str]] = []

        for filename in os.listdir(labels_dir):
            ext = os.path.splitext(filename.lower())[1]
            if ext not in image_extensions:
                continue
            file_path = os.path.join(labels_dir, filename)
            if not os.path.isfile(file_path):
                continue
            match = re.match(r"(.+?)_?第？?(\d+)?项？\.png", filename, re.IGNORECASE)
            order_number = match.group(1) if match else os.path.splitext(filename)[0]
            label_number = match.group(2) if match and match.group(2) else "1"
            labels.append(
                {
                    "filename": filename,
                    "order_number": order_number.strip() if order_number else "",
                    "label_number": label_number.strip() if label_number else "1",
                }
            )

        labels.sort(key=lambda x: x.get("filename", ""), reverse=True)
        labels = labels[:limit]
        return JSONResponse({"success": True, "labels": labels})
    except RECOVERABLE_ERRORS:
        logger.exception("获取标签列表失败")
        return JSONResponse(
            {"success": False, "labels": [], "message": _PRINT_UNAVAILABLE}, status_code=500
        )


@router.get("/label/{filename}")
def serve_label_image(filename: str):
    try:
        from app.infrastructure.workspace import resolve_existing_file_under_root
        from app.utils.path_io.path_utils import get_resource_path

        labels_dir = get_resource_path("ai_assistant", "商标导出")
        raw_name = str(filename or "").replace("\\", "/")
        base_name = os.path.basename(raw_name)
        if not base_name or raw_name != base_name:
            return JSONResponse({"success": False, "message": "文件名无效"}, status_code=400)
        if Path(base_name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
            return JSONResponse({"success": False, "message": "文件名无效"}, status_code=400)
        try:
            file_path = resolve_existing_file_under_root(Path(labels_dir), base_name)
        except FileNotFoundError:
            logger.warning("标签文件不存在: %s", base_name)
            return JSONResponse({"success": False, "message": "文件不存在"}, status_code=404)
        except ValueError:
            return JSONResponse({"success": False, "message": "文件名无效"}, status_code=400)
        return FileResponse(file_path, media_type="image/png")
    except RECOVERABLE_ERRORS:
        logger.exception("获取标签图片失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)
