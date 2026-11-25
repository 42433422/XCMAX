"""OCR API（继承自归档 ocr 蓝图的端点契约）。"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.fastapi_routes.tools_execute import run_tools_execute_agent
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.schemas.ocr_schema import (
    OcrAnalyzeResponse,
    OcrExtractResponse,
    OcrRecognizeAndExtractResponse,
    OcrRecognizeResponse,
    OcrTestResponse,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.upload_helpers import save_upload_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "tiff", "webp"}


@lru_cache(maxsize=1)
def _get_ocr_service():
    from app.application.facades.ocr_facade import get_ocr_service as _get

    return _get()


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ocr_user_id(user=Depends(get_logged_in_user)) -> str:
    """Bind OCR execution to the verified session, never identity headers."""
    user_id = getattr(user, "id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="请先登录后使用 OCR")
    return str(user_id)


def _run_ocr_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    return run_tools_execute_agent(
        request=request,
        body={"tool_id": "ocr", "action": action, "params": params},
        route_path=str(request.url.path),
    )


async def _resolve_ocr_path(
    file_path: str | None,
    image: UploadFile | None,
) -> str | None:
    if image is not None and image.filename:
        return await save_upload_file(image, subdir="ocr")
    return file_path


@router.post("/recognize", response_model=OcrRecognizeResponse)
async def ocr_recognize(
    request: Request,
    file_path: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    user_id: str = Depends(_ocr_user_id),
):
    try:
        resolved_path = await _resolve_ocr_path(file_path, image)
        if not resolved_path:
            return JSONResponse(
                {"success": False, "message": "请提供图像文件或文件路径"}, status_code=400
            )

        result, status_code = await run_in_threadpool(
            _run_ocr_agent,
            request=request,
            action="recognize",
            params={"file_path": resolved_path},
        )
        return JSONResponse(result, status_code=status_code)
    except RECOVERABLE_ERRORS:
        logger.exception("OCR识别失败")
        return JSONResponse({"success": False, "message": "识别服务暂时不可用"}, status_code=500)


@router.post("/extract", response_model=OcrExtractResponse)
def ocr_extract(
    request: Request,
    data: dict = Body(default_factory=dict),
    user_id: str = Depends(_ocr_user_id),
):
    try:
        text = data.get("text", "")
        if not text:
            return JSONResponse({"success": False, "message": "文本不能为空"}, status_code=400)
        result, status_code = _run_ocr_agent(
            request=request,
            action="extract",
            params={"text": str(text)},
        )
        return JSONResponse(result, status_code=status_code)
    except RECOVERABLE_ERRORS:
        logger.exception("提取结构化数据失败")
        return JSONResponse(
            {"success": False, "message": "数据提取服务暂时不可用"}, status_code=500
        )


@router.post("/analyze", response_model=OcrAnalyzeResponse)
def ocr_analyze(
    request: Request,
    data: dict = Body(default_factory=dict),
    user_id: str = Depends(_ocr_user_id),
):
    try:
        text = data.get("text", "")
        if not text:
            return JSONResponse({"success": False, "message": "文本不能为空"}, status_code=400)
        result, status_code = _run_ocr_agent(
            request=request,
            action="analyze",
            params={"text": str(text)},
        )
        return JSONResponse(result, status_code=status_code)
    except RECOVERABLE_ERRORS:
        logger.exception("分析文本失败")
        return JSONResponse(
            {"success": False, "message": "文本分析服务暂时不可用"}, status_code=500
        )


@router.post("/recognize-and-extract", response_model=OcrRecognizeAndExtractResponse)
async def ocr_recognize_and_extract(
    request: Request,
    file_path: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    user_id: str = Depends(_ocr_user_id),
):
    try:
        resolved_path = await _resolve_ocr_path(file_path, image)
        if not resolved_path:
            return JSONResponse(
                {"success": False, "message": "请提供图像文件或文件路径"}, status_code=400
            )

        result, status_code = await run_in_threadpool(
            _run_ocr_agent,
            request=request,
            action="recognize_and_extract",
            params={"file_path": resolved_path},
        )
        return JSONResponse(result, status_code=status_code)
    except RECOVERABLE_ERRORS:
        logger.exception("OCR识别和提取失败")
        return JSONResponse(
            {"success": False, "message": "OCR 处理服务暂时不可用"}, status_code=500
        )


@router.get("/test", response_model=OcrTestResponse)
def ocr_test():
    try:
        svc = _get_ocr_service()
        backend = svc.get_active_ocr_backend()
    except RECOVERABLE_ERRORS:
        backend = "unknown"
    return OcrTestResponse(active_backend=backend)
