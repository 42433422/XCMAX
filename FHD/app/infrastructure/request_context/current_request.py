"""当前请求的 ContextVar 存储（请求级隔离）。

供中间件在 dispatch 时 set，业务层（如 value_objects_industry）在无 Request
参数的旧代码路径中 get，实现"当前请求"的隐式传递。
"""

from __future__ import annotations

import contextvars
from typing import Optional

from starlette.requests import Request

_current_request_ctx: contextvars.ContextVar[Optional[Request]] = contextvars.ContextVar(
    "xcagi_current_request",
    default=None,
)


def set_current_request(request: Request):
    """设置当前请求到 ContextVar，返回 token 用于复位。"""
    return _current_request_ctx.set(request)


def reset_current_request(token) -> None:
    """复位当前请求 ContextVar 到上一个值。"""
    _current_request_ctx.reset(token)


def get_current_request() -> Optional[Request]:
    """获取当前请求；无请求上下文时返回 None。"""
    return _current_request_ctx.get()


__all__ = [
    "get_current_request",
    "reset_current_request",
    "set_current_request",
]
