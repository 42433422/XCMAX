"""微信本地库自动配置 HTTP 响应。"""

from __future__ import annotations

from typing import Any


def wechat_decrypt_auto_configure_response(body: dict[str, Any] | None) -> dict[str, Any]:
    return {"success": False, "message": "wechat decrypt autoconfig unavailable", "body": body}
