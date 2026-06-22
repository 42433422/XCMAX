"""Request-scoped ContextVar helpers (Phase 3 from app.legacy)."""

from app.infrastructure.request_context.client_mods import (
    get_request_client_mods_ui_off,
    parse_client_mods_off_header,
    reset_request_client_mods_ui_off,
    set_request_client_mods_ui_off,
)
from app.infrastructure.request_context.current_request import (
    get_current_request,
    reset_current_request,
    set_current_request,
)

__all__ = [
    "get_current_request",
    "get_request_client_mods_ui_off",
    "parse_client_mods_off_header",
    "reset_current_request",
    "reset_request_client_mods_ui_off",
    "set_current_request",
    "set_request_client_mods_ui_off",
]
