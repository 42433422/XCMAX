"""Application service for WeChat outbound message sending."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def send_wechat_message(contact_name: str, message: str) -> Dict[str, Any]:
    """Send a WeChat message.

    1. Run outbound safety check.
    2. Fallback to ``wechat_cv_send`` on Windows when automation mod is unavailable.
    3. Return a structured result dict.
    """
    try:
        from app.services.wechat_passive_group_monitor import (
            assert_safe_outbound_group_reply,
        )
    except RECOVERABLE_ERRORS:
        # Security check unavailable: continue with current message.
        pass
    else:
        safe = assert_safe_outbound_group_reply(message)
        if not safe:
            return {
                "success": False,
                "message": "消息内容未通过客服发送安全校验（疑似思考过程或任务复述），已拦截",
            }
        message = safe

    if not sys.platform.startswith("win"):
        return {
            "success": False,
            "message": "wechat automation mod not installed and CV fallback is Windows-only",
        }

    try:
        # FHD/ 已通过 app 包加载进入 sys.path，resources.wechat_cv 可直接导入。
        from resources.wechat_cv.wechat_cv_send import search_and_send_by_cv

        result = search_and_send_by_cv(contact_name, message, delay=1.0, use_ocr=True)
        if result.get("status") == "success":
            return {
                "success": True,
                "message": f"已发送给 {contact_name}",
                "result": result,
            }
        return {
            "success": False,
            "message": f"发送失败: {result.get('message', '未知错误')}",
            "result": result,
        }
    except RECOVERABLE_ERRORS as exc:
        return {
            "success": False,
            "message": f"发送失败：{exc}",
        }


__all__ = ["send_wechat_message"]
