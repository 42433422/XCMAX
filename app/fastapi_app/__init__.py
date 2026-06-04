"""
FastAPI 应用入口包。

历史代码 ``from app.fastapi_app import create_fastapi_app`` 仍有效；
实现已拆分为同目录下 ``cors`` / ``lifespan`` / ``factory`` 等子模块。
"""

from __future__ import annotations

from .cors import resolve_cors_allow_origin_regex, resolve_cors_allow_origins
from .factory import create_fastapi_app, get_fastapi_app
from .lifespan import lifespan

__all__ = [
    "create_fastapi_app",
    "get_fastapi_app",
    "lifespan",
    "resolve_cors_allow_origins",
    "resolve_cors_allow_origin_regex",
]
