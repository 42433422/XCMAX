"""打印 API（继承自归档 print 蓝图的端点契约）。"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.fastapi_routes.print_agent_helpers import (
    agent_node_output as _agent_node_output,
)
from app.fastapi_routes.print_agent_helpers import (
    print_agent_status_code as _print_agent_status_code,
)
from app.fastapi_routes.print_agent_helpers import (
    print_agent_user_id as _print_agent_user_id,
)
from app.fastapi_routes.print_agent_helpers import (
    run_print_agent as _run_print_agent,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.security.secure_filename import secure_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/print", tags=["print"])

__all__ = [
    "_agent_node_output",
    "_print_agent_status_code",
    "_print_agent_user_id",
    "_run_print_agent",
    "router",
]

_PRINT_CONFIRM_TTL_SECONDS = 300
_PRINT_UNAVAILABLE = "打印服务暂时不可用，请稍后重试"
_print_confirm_cache: dict[str, dict[str, Any]] = {}


def _cleanup_print_confirm_cache() -> None:
    now = time.time()
    expired = [
        token
        for token, payload in _print_confirm_cache.items()
        if float(payload.get("expires_at", 0.0)) <= now
    ]
    for token in expired:
        _print_confirm_cache.pop(token, None)


def _create_print_confirm_token(payload: dict[str, Any]) -> str:
    _cleanup_print_confirm_cache()
    token = uuid.uuid4().hex
    _print_confirm_cache[token] = {
        **payload,
        "expires_at": time.time() + _PRINT_CONFIRM_TTL_SECONDS,
    }
    return token


def _consume_print_confirm_token(token: str) -> dict[str, Any]:
    _cleanup_print_confirm_cache()
    return _print_confirm_cache.pop(token, {})


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
        result = _run_print_agent(
            request=request,
            action="save_printer_selection",
            params={
                "document_printer": data.get("document_printer"),
                "label_printer": data.get("label_printer"),
            },
            route_path="/api/print/printer-selection",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
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
        printer_name = data.get("printer_name")
        use_automation = data.get("use_automation", False)
        if not file_path:
            return JSONResponse({"success": False, "message": "文件路径不能为空"}, status_code=400)
        result = _run_print_agent(
            request=request,
            action="print_document",
            params={
                "file_path": str(file_path),
                "printer_name": printer_name,
                "use_automation": use_automation,
            },
            route_path="/api/print/document",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
    except RECOVERABLE_ERRORS:
        logger.exception("打印文档失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)


@router.post("/label")
def print_label(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        file_path = data.get("file_path", "")
        printer_name = data.get("printer_name")
        copies = data.get("copies", 1)
        require_confirm = bool(data.get("require_confirm", True))
        confirm_token = str(data.get("confirm_token") or "").strip()
        confirm_action = str(data.get("confirm_action") or "").strip().lower()
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

        service = _svc()
        if require_confirm:
            if confirm_action == "cancel":
                if confirm_token:
                    _consume_print_confirm_token(confirm_token)
                return JSONResponse(
                    {"success": True, "status": "print_cancelled", "message": "已取消打印"},
                    status_code=200,
                )
            if not confirm_token:
                resolved_printer = printer_name or service.get_label_printer()
                token = _create_print_confirm_token(
                    {
                        "file_path": file_path,
                        "printer_name": resolved_printer,
                        "copies": copies,
                    }
                )
                return JSONResponse(
                    {
                        "success": True,
                        "status": "print_confirm_required",
                        "require_confirm": True,
                        "confirm_token": token,
                        "confirm_prompt": (
                            f"已准备打印 {copies} 份标签，是否立即打印到【{resolved_printer or '自动选择打印机'}】？"
                        ),
                        "preview": {
                            "file_path": file_path,
                            "label_count": copies,
                            "printer": resolved_printer,
                        },
                        "message": "已生成标签，等待打印确认",
                    },
                    status_code=200,
                )
            token_payload = _consume_print_confirm_token(confirm_token)
            if not token_payload:
                return JSONResponse(
                    {
                        "success": False,
                        "status": "print_confirm_required",
                        "error_code": "print_confirm_required",
                        "message": "打印确认已过期或无效，请重新发起打印请求",
                    },
                    status_code=400,
                )
            file_path = str(token_payload.get("file_path") or file_path)
            copies = int(token_payload.get("copies") or copies)
            printer_name = token_payload.get("printer_name") or printer_name

        result = _run_print_agent(
            request=request,
            action="print_label",
            params={
                "file_path": str(file_path),
                "printer_name": printer_name,
                "copies": copies,
            },
            route_path="/api/print/label",
        )
        if isinstance(result, dict):
            result.setdefault("status", "printed")
            result.setdefault("require_confirm", False)
        return JSONResponse(result, status_code=_print_agent_status_code(result))
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
        result = _run_print_agent(
            request=request,
            action="test",
            params={"printer_name": str(printer_name)},
            route_path="/api/print/test",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
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
    """工作流标签打印调度接口——幂等，同一 idempotency_key 重复调用仅执行一次打印。"""
    idempotency_key = str(data.get("idempotency_key") or "").strip()
    model_number = str(data.get("model_number") or "").strip()
    quantity = max(1, min(100, int(data.get("quantity") or 1)))

    if not model_number:
        return JSONResponse({"success": False, "message": "model_number 不能为空"}, status_code=400)

    # 检查幂等缓存（5 分钟 TTL，与打印确认 token 同机制）
    if idempotency_key:
        cached = _print_confirm_cache.get(f"wf_lp:{idempotency_key}")
        if cached and float(cached.get("expires_at", 0)) > time.time():
            return JSONResponse(
                {"success": True, "message": "已在幂等窗口内执行过，跳过重复打印", "skipped": True},
                status_code=200,
            )
        # 写入幂等标记
        _print_confirm_cache[f"wf_lp:{idempotency_key}"] = {
            "model_number": model_number,
            "expires_at": time.time() + _PRINT_CONFIRM_TTL_SECONDS,
        }

    try:
        result = _run_print_agent(
            request=request,
            action="workflow_label_dispatch",
            params={
                "model_number": model_number,
                "quantity": quantity,
                "idempotency_key": idempotency_key,
            },
            route_path="/api/print/workflow/label-print/dispatch",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
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
        from app.utils.path_io.path_utils import get_resource_path

        labels_dir = get_resource_path("ai_assistant", "商标导出")
        base_name = os.path.basename(str(filename or "").replace("\\", "/"))
        safe_filename = secure_filename(base_name)
        if not safe_filename or safe_filename != base_name:
            return JSONResponse({"success": False, "message": "文件名无效"}, status_code=400)
        file_path = os.path.join(labels_dir, safe_filename)
        if not os.path.exists(file_path):
            logger.warning("标签文件不存在: %s", file_path)
            return JSONResponse({"success": False, "message": "文件不存在"}, status_code=404)
        return FileResponse(file_path, media_type="image/png")
    except RECOVERABLE_ERRORS:
        logger.exception("获取标签图片失败")
        return JSONResponse({"success": False, "message": _PRINT_UNAVAILABLE}, status_code=500)
