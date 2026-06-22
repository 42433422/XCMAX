"""OCR API（继承自归档 ocr 蓝图的端点契约）。"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.schemas.ocr_schema import (
    OcrAnalyzeResponse,
    OcrExtractResponse,
    OcrRecognizeAndExtractResponse,
    OcrRecognizeResponse,
    OcrTestResponse,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.upload_helpers import save_upload_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "tiff", "webp"}


@lru_cache(maxsize=1)
def _get_ocr_service():
    from app.application.facades.ocr_facade import get_ocr_service as _get

    return _get()


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ocr_user_id(request: Request | None) -> str:
    if request is None:
        return "ocr-route"
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or request.headers.get("X-Workspace-Id")
        or "ocr-route"
    ).strip()


def _run_ocr_agent(
    *,
    request: Request | None,
    action: str,
    node_id: str,
    message: str,
    params: dict[str, Any],
) -> Any:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id=f"ocr_{action}",
        intent=f"ocr_{action}",
        todo_steps=["通过 AgentOrchestrator 执行 OCR 工具"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="ocr",
                action=action,
                params=dict(params or {}),
                risk="low",
                idempotent=True,
                description="Execute OCR through the unified Agent runtime.",
            )
        ],
        risk_level="low",
        metadata={"source": "ocr_route", "route": "/api/ocr"},
    )
    return AgentOrchestrator().start_run_from_plan(
        user_id=_ocr_user_id(request),
        message=message,
        plan=plan,
        runtime_context={
            "source": "ocr_route",
            "route_action": action,
            "request_path": str(getattr(getattr(request, "url", None), "path", "") or ""),
        },
    )


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _ocr_status(payload: dict[str, Any]) -> int:
    if payload.get("success"):
        return 200
    if str(payload.get("error_code") or "") == "ocr_exception":
        return 500
    return 400


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
):
    try:
        resolved_path = await _resolve_ocr_path(file_path, image)
        if not resolved_path:
            return JSONResponse(
                {"success": False, "message": "请提供图像文件或文件路径"}, status_code=400
            )

        run = _run_ocr_agent(
            request=request,
            action="recognize",
            node_id="ocr_recognize",
            message=f"OCR recognize: {resolved_path}",
            params={"file_path": resolved_path},
        )
        result = _agent_node_output(run, "ocr_recognize")
        status_code = _ocr_status(result)
        return JSONResponse(result, status_code=status_code)
    except RECOVERABLE_ERRORS as e:
        logger.exception("OCR识别失败: %s", e)
        return JSONResponse({"success": False, "message": f"识别失败: {str(e)}"}, status_code=500)


@router.post("/extract", response_model=OcrExtractResponse)
def ocr_extract(request: Request, data: dict = Body(default_factory=dict)):
    try:
        text = data.get("text", "")
        if not text:
            return JSONResponse({"success": False, "message": "文本不能为空"}, status_code=400)
        run = _run_ocr_agent(
            request=request,
            action="extract",
            node_id="ocr_extract",
            message="OCR extract structured data",
            params={"text": str(text)},
        )
        result = _agent_node_output(run, "ocr_extract")
        return JSONResponse(result, status_code=_ocr_status(result))
    except RECOVERABLE_ERRORS as e:
        logger.exception("提取结构化数据失败: %s", e)
        return JSONResponse({"success": False, "message": f"提取失败: {str(e)}"}, status_code=500)


@router.post("/analyze", response_model=OcrAnalyzeResponse)
def ocr_analyze(request: Request, data: dict = Body(default_factory=dict)):
    try:
        text = data.get("text", "")
        if not text:
            return JSONResponse({"success": False, "message": "文本不能为空"}, status_code=400)
        run = _run_ocr_agent(
            request=request,
            action="analyze",
            node_id="ocr_analyze",
            message="OCR analyze text",
            params={"text": str(text)},
        )
        result = _agent_node_output(run, "ocr_analyze")
        return JSONResponse(result, status_code=_ocr_status(result))
    except RECOVERABLE_ERRORS as e:
        logger.exception("分析文本失败: %s", e)
        return JSONResponse({"success": False, "message": f"分析失败: {str(e)}"}, status_code=500)


@router.post("/recognize-and-extract", response_model=OcrRecognizeAndExtractResponse)
async def ocr_recognize_and_extract(
    request: Request,
    file_path: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
):
    try:
        resolved_path = await _resolve_ocr_path(file_path, image)
        if not resolved_path:
            return JSONResponse(
                {"success": False, "message": "请提供图像文件或文件路径"}, status_code=400
            )

        run = _run_ocr_agent(
            request=request,
            action="recognize_and_extract",
            node_id="ocr_recognize_and_extract",
            message=f"OCR recognize and extract: {resolved_path}",
            params={"file_path": resolved_path},
        )
        result = _agent_node_output(run, "ocr_recognize_and_extract")
        return JSONResponse(result, status_code=_ocr_status(result))
    except RECOVERABLE_ERRORS as e:
        logger.exception("OCR识别和提取失败: %s", e)
        return JSONResponse({"success": False, "message": f"处理失败: {str(e)}"}, status_code=500)


@router.get("/test", response_model=OcrTestResponse)
def ocr_test():
    try:
        svc = _get_ocr_service()
        backend = svc.get_active_ocr_backend()
    except RECOVERABLE_ERRORS:
        backend = "unknown"
    return OcrTestResponse(active_backend=backend)
