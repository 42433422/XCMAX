"""统一的微信消息发送入口。

主代码侧只保留「安全校验 + Windows CV 回退」能力。真实的 RPA 驱动（操控微信桌面版
UI 自动化）由可选的 ``xcagi-wechat-automation`` Mod 提供，未安装时本模块仍可通过
``wechat_cv_send`` 完成发送（仅 Windows）。

历史：本模块从 ``app/fastapi_routes/domains/wechat/routes.py`` 的
``_send_wechat_via_automation`` 提取，去除对已迁移的
``app.desktop_automation.service`` 的依赖。
"""

from __future__ import annotations

import logging
import sys

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def send_wechat_message(contact_name: str, message: str) -> dict:
    """发送微信消息给指定联系人。

    流程：
    1. 客服发送安全校验（拦截思考过程/任务复述）
    2. Windows 下回退到 ``wechat_cv_send`` 的 CV+OCR 方案
    3. 非 Windows 直接返回失败

    返回 dict 形如 ``{"success": bool, "message": str, "result": dict}``。
    """
    try:
        from app.services.wechat_passive_group_monitor import (
            assert_safe_outbound_group_reply,
        )
    except RECOVERABLE_ERRORS:
        # 安全校验不可用时放行，但不做后续处理
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
        from app.utils.path_utils import get_resource_path

        sys_path = get_resource_path("wechat-decrypt")
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)

        from resources.wechat_cv.wechat_cv_send import search_and_send_by_cv

        result = search_and_send_by_cv(contact_name, message, delay=1.0, use_ocr=True)
        if result.get("status") == "success":
            return {"success": True, "message": f"已发送给 {contact_name}", "result": result}
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
