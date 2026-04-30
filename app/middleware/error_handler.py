"""
FastAPI 错误处理器

集中处理所有 API 异常
"""

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """
    注册全局异常处理器

    Args:
        app: FastAPI 应用实例
    """
    logger.info("Registering exception handlers...")

    # HTTP 异常处理器
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning(f"HTTP Exception {exc.status_code}: {exc.detail} - Path: {request.url.path}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": f"http_{exc.status_code}",
                "message": str(exc.detail),
                "path": request.url.path
            }
        )

    # 请求验证异常处理器
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Validation Error: {exc.errors()} - Path: {request.url.path}")
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"]
            })
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error_code": "validation_error",
                "message": "请求参数验证失败",
                "errors": errors,
                "path": request.url.path
            }
        )

    # 通用异常处理器
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled Exception: {exc} - Path: {request.url.path}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_code": "internal_error",
                "message": "服务器内部错误",
                "path": request.url.path
            }
        )

    logger.info("Exception handlers registered successfully")
