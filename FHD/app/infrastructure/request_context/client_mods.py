"""客户端 Mod UI 关闭标记的请求级 ContextVar。

Phase 3 从 ``app.legacy.request_client_mods_ctx`` 迁入。
"""

from __future__ import annotations

import contextvars
from collections.abc import Mapping

_client_mods_ui_off_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "xcagi_request_client_mods_ui_off",
    default=False,
)


def parse_client_mods_off_header(headers: Mapping[str, str]) -> bool:
    for k in ("x-client-mods-off", "X-Client-Mods-Off"):
        if k in headers:
            v = str(headers.get(k) or "").strip().lower()
            return v in ("1", "true", "yes", "on")
    return False


def set_request_client_mods_ui_off(off: bool):
    return _client_mods_ui_off_ctx.set(bool(off))


def reset_request_client_mods_ui_off(token) -> None:
    _client_mods_ui_off_ctx.reset(token)


def get_request_client_mods_ui_off() -> bool:
    return bool(_client_mods_ui_off_ctx.get())


__all__ = [
    "parse_client_mods_off_header",
    "set_request_client_mods_ui_off",
    "reset_request_client_mods_ui_off",
    "get_request_client_mods_ui_off",
]
