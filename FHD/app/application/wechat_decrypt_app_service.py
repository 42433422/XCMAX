"""Application facade for WeChat local-db decrypt / autoconfig."""

from __future__ import annotations

from typing import Any


def get_wechat_decrypt_status() -> dict[str, Any]:
    from app.services.wechat_decrypt_autoconfig import get_wechat_decrypt_status as impl

    return impl()


def wechat_decrypt_auto_configure_response(body: dict | None = None) -> Any:
    from app.services.wechat_decrypt_http import wechat_decrypt_auto_configure_response as impl

    return impl(body)


def sync_group_messages() -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import sync_group_messages as impl

    return impl()


__all__ = [
    "get_wechat_decrypt_status",
    "sync_group_messages",
    "wechat_decrypt_auto_configure_response",
]
