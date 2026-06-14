"""微信本地库自动配置状态。"""

from __future__ import annotations

from typing import Any


def get_wechat_decrypt_status() -> dict[str, Any]:
    return {"configured": False, "message": "wechat decrypt not configured"}
