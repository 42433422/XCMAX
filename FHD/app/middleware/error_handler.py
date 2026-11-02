"""
FastAPI 错误处理器

集中处理所有 API 异常
"""

import logging
import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import AppError
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)


def _reviewed_excel_context(request: Request) -> dict:
    """Bound diagnostics to server stages and a safe correlation id, never workbook data."""
    if not request.url.path.startswith("/api/templates/reviewed-excel/"):
        return {}
    raw_id = str(getattr(request.state, "request_id", ""))
    request_id = raw_id if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", raw_id) else uuid4().hex
    request.state.request_id = request_id
    stage = str(getattr(request.state, "elt_stage", ""))
    if stage not in {
        "read_workbook",
        "extract_document",
        "generate_candidates",
        "model_candidates",
        "render_candidates",
        "save_preview",
    }:
        tail = request.url.path.rsplit("/", 1)[-1]
        stage = (
            tail
            if tail
            in {
                "archive-classify",
                "classify",
                "analyze",
                "confirm",
                "preview",
                "refine",
                "save",
                "intake-preview",
            }
            else "request"
        )
    return {"request_id": request_id, "stage": stage}


def _log_reviewed_excel(context: dict, exc: Exception, level=logging.WARNING):
    logger.log(
        level,
        "ELT processing failed stage=%s request_id=%s error_type=%s",
        context["stage"],
        context["request_id"],
        type(exc).__name__,
    )


def _reviewed_excel_failure(request: Request, exc: Exception):
    context = _reviewed_excel_context(request)
    _log_reviewed_excel(context, exc, logging.ERROR)
    return JSONResponse(
        status_code=500,
        headers={"X-Request-ID": context["request_id"]},
        content={
            "success": False,
            "error_code": "elt_processing_failed",
            "message": "文件处理失败，请核对当前处理状态后重试；若仍失败，请提供请求编号。",
            **context,
        },
    )


class ReviewedExcelRoute(APIRoute):
    """Stop raw file/provider exceptions before ASGI logs their sensitive messages."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except (AppError, StarletteHTTPException, RequestValidationError):
                raise
            except BOUNDARY_ERRORS as exc:
                return _reviewed_excel_failure(request, exc)

        return handle


_ELT_MODEL_MESSAGES = {
    "model_required": "数据对接须先完成当前已授权平台模型处理，未写入任何数据；请重新开始处理。",
    "notice_not_published": "登录数据处理条款尚未正式发布，未调用模型；请联系管理员发布后重新登录。",
    "login_notice_required": "当前登录会话缺少有效的模型处理授权，请阅读登录说明后重新登录。",
    "model_configuration_error": "模型连接异常：平台模型配置或登录连接未就绪，或接收方不在已披露范围；未调用模型，请联系管理员。",
    "model_connection_error": "模型连接异常，未能建立模型处理授权；请检查平台模型连接后重新登录。",
    "model_processing_failed": "模型处理未完成，结果可能已产生费用；请先核对处理状态，勿重复提交。",
}


def _elt_model_error(detail: object) -> dict:
    """Only expose fixed messages and boolean state for the bounded ELT error contract."""
    if not isinstance(detail, dict):
        return {}
    code = detail.get("code")
    if not isinstance(code, str) or code not in _ELT_MODEL_MESSAGES:
        return {}
    valid = set(detail) <= {"code", "message", "retryable", "outcome_unknown"} and all(
        isinstance(detail.get(key, False), bool) for key in ("retryable", "outcome_unknown")
    )
    unknown = code == "model_processing_failed" or detail.get("outcome_unknown") is True
    return {
        "error_code": code,
        "message": _ELT_MODEL_MESSAGES[code],
        "retryable": valid
        and not unknown
        and code in {"model_configuration_error", "model_connection_error"}
        and detail.get("retryable") is True,
        "outcome_unknown": unknown,
    }


def register_exception_handlers(app: FastAPI) -> None:
    logger.info("Registering exception handlers...")

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        context = _reviewed_excel_context(request)
        request_id = getattr(request.state, "request_id", "")
        if context:
            _log_reviewed_excel(context, exc)
        else:
            logger.warning(
                "AppError %s: %s (request_id=%s, path=%s)",
                exc.code.value,
                exc.message,
                request_id,
                request.url.path,
            )
        return JSONResponse(
            status_code=exc.status_code,
            headers={"X-Request-ID": context["request_id"]} if context else None,
            content={**exc.to_dict(request_id=request_id), **context},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        context = _reviewed_excel_context(request)
        if context:
            _log_reviewed_excel(context, exc)
        else:
            logger.warning(
                "HTTP Exception %s: %s - Path: %s", exc.status_code, exc.detail, request.url.path
            )
        return JSONResponse(
            status_code=exc.status_code,
            headers={"X-Request-ID": context["request_id"]} if context else None,
            content={
                "success": False,
                "error_code": f"http_{exc.status_code}",
                "message": str(exc.detail),
                **(_elt_model_error(exc.detail) if context else {}),
                "path": request.url.path,
                **context,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        context = _reviewed_excel_context(request)
        if context:
            _log_reviewed_excel(context, exc)
        else:
            logger.warning("Validation Error: %s - Path: %s", exc.errors(), request.url.path)
        errors = []
        for error in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(loc) for loc in error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
            )
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": context["request_id"]} if context else None,
            content={
                "success": False,
                "error_code": "validation_error",
                "message": "请求参数验证失败",
                "errors": errors,
                "path": request.url.path,
                **context,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        context = _reviewed_excel_context(request)
        if context:
            return _reviewed_excel_failure(request, exc)
        logger.exception("Unhandled Exception: %s - Path: %s", exc, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_code": "internal_error",
                "message": "服务器内部错误",
                "path": request.url.path,
            },
        )

    logger.info("Exception handlers registered successfully")
