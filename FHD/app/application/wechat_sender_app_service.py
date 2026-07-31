"""Application facade for WeChat outbound message sending."""

from __future__ import annotations

from typing import Any, Dict


def send_wechat_message(contact_name: str, message: str) -> Dict[str, Any]:
    from app.services.wechat_sender import send_wechat_message as impl

    return impl(contact_name, message)


__all__ = ["send_wechat_message"]
