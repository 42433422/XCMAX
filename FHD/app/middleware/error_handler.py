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
from app.middleware.request_id import ensure_request_id
from app.security.log_redaction import redact_log_text
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
    "model_required": "数据对接须先完成模型处理，未写入任何数据；请重新开始处理。",
    "notice_not_published": "登录数据处理条款尚未正式发布，未调用模型；请联系管理员发布后重新登录。",
    "login_notice_required": "当前登录会话缺少有效的模型处理授权，请阅读登录说明后重新登录。",
    "model_configuration_error": "当前账户的模型连接或配置不可用，未调用模型；请检查智能对话的模型设置。",
    "model_connection_error": "当前账户的模型连接不可用，未调用模型；请检查智能对话的模型连接。",
    "model_processing_failed": "模型处理未完成，结果可能已产生费用；请先核对处理状态，勿重复提交。",
    "model_answer_rejected": "模型已回答，但答案未通过校验，未写入任何数据。",
    "model_answer_truncated": "模型输出达到长度上限被截断，未写入任何数据，也未原样重发。",
}
_ELT_OUTCOME_MESSAGES = {
    "rejected": "模型供应商拒绝了本次请求，未产生答案，也未自动重发。",
}
_ELT_OUTCOMES = {"not_sent", "rejected", "answered_invalid", "truncated", "unknown"}


def _elt_model_error(detail: object) -> dict:
    """Only expose fixed messages, the sanitized reason and boolean state for the ELT error contract."""
    if not isinstance(detail, dict):
        return {}
    code = detail.get("code")
    if not isinstance(code, str) or code not in _ELT_MODEL_MESSAGES:
        return {}
    outcome, reason = detail.get("outcome"), detail.get("reason")
    valid = (
        set(detail) <= {"code", "message", "retryable", "outcome_unknown", "outcome", "reason"}
        and all(
            isinstance(detail.get(key, False), bool) for key in ("retryable", "outcome_unknown")
        )
        and outcome in {None, *_ELT_OUTCOMES}
        and isinstance(reason, str | None)
    )
    unknown = code == "model_processing_failed" or detail.get("outcome_unknown") is True
    message = (_ELT_OUTCOME_MESSAGES.get(outcome) if outcome else None) or _ELT_MODEL_MESSAGES[code]
    reason = " ".join((reason or "").split()) if valid else ""
    if reason:
        message = f"{message}原因：{reason[:180]}"
    return {
        "error_code": code,
        "message": message,
        "retryable": valid
        and not unknown
        and code in {"model_configuration_error", "model_connection_error", "model_answer_rejected"}
        and detail.get("retryable") is True,
        **({"outcome": outcome} if valid and outcome else {}),
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
        detail = exc.detail
        message = str(detail)
        redacted = redact_log_text(message)
        if not context and ("Traceback" in message or "\n" in message):
            message = "请求失败"
        elif redacted != message:
            message = redacted
        return JSONResponse(
            status_code=exc.status_code,
            headers={
                "X-Request-ID": context["request_id"] if context else ensure_request_id(request)
            },
            content={
                "success": False,
                "error_code": f"http_{exc.status_code}",
                "message": message,
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
        request_id = ensure_request_id(request)
        logger.error(
            "Unhandled %s request_id=%s path=%s detail=%s",
            type(exc).__name__,
            request_id,
            request.url.path,
            redact_log_text(str(exc))[:300],
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content={
                "success": False,
                "error_code": "internal_error",
                "message": "服务器内部错误",
                "request_id": request_id,
                "path": request.url.path,
            },
        )

    logger.info("Exception handlers registered successfully")
