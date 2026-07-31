"""Application facade for WeChat local-db decrypt / autoconfig."""

from __future__ import annotations

from typing import Any


def get_wechat_decrypt_status() -> dict[str, Any]:
    from app.services.wechat_decrypt_autoconfig import get_wechat_decrypt_status as impl

    return impl()


def wechat_decrypt_auto_configure_response(body: dict | None = None) -> Any:
    from app.services.wechat_decrypt_http import wechat_decrypt_auto_configure_response as impl

    return impl(body)


def prepare_wechat_message_db_for_read(
    *,
    force_decrypt: bool = True,
    retry_key_scan: bool = False,
) -> dict[str, Any]:
    try:
        from app.services.wechat_decrypt_autoconfig import (
            prepare_wechat_message_db_for_read as impl,
        )
    except (ImportError, AttributeError):
        return {
            "success": False,
            "message": "wechat decrypt autoconfig helper not available",
        }

    return impl(force_decrypt=force_decrypt, retry_key_scan=retry_key_scan)


def sync_group_messages() -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import sync_group_messages as impl

    return impl()


__all__ = [
    "get_wechat_decrypt_status",
    "prepare_wechat_message_db_for_read",
    "sync_group_messages",
    "wechat_decrypt_auto_configure_response",
]
