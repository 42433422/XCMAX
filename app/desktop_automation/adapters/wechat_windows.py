"""WeChat Windows 适配器 — 薄封装 wechat_cv_send，保持 legacy API 行为。"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


class WeChatWindowsAdapter:
    """将现有 CV 发送栈接入 DesktopAutomation 抽象层。"""

    def __init__(self):
        self._ensure_cv_path()

    @staticmethod
    def _ensure_cv_path() -> None:
        try:
            from app.infrastructure.plugins.wechat_plugin import get_wechat_plugin

            get_wechat_plugin().add_to_sys_path()
        except Exception:
            from app.utils.path_utils import get_resource_path

            cv_path = get_resource_path("wechat_cv")
            if cv_path and cv_path not in sys.path:
                sys.path.insert(0, cv_path)

    def is_available(self) -> bool:
        try:
            import win32gui  # noqa: F401

            return True
        except ImportError:
            return False

    def find_wechat_handle(self):
        from wechat_cv_send import _find_wechat_handle

        return _find_wechat_handle()

    def open_chat(self, contact_name: str, *, use_ocr: bool = True) -> dict[str, Any]:
        from wechat_cv_send import open_chat_by_cv

        out = open_chat_by_cv(contact_name, use_ocr=use_ocr)
        return {"success": out.get("status") == "success", **out}

    def send_to_current(
        self, message: str, *, delay: float = 1.2, use_ocr: bool = True
    ) -> dict[str, Any]:
        from wechat_cv_send import send_to_current_chat_by_cv

        out = send_to_current_chat_by_cv(message, delay=delay, use_ocr=use_ocr)
        if isinstance(out, dict):
            return {"success": out.get("status") == "success", **out}
        return {"success": bool(out), "message": str(out)}

    def search_and_send(
        self, contact_name: str, message: str, *, delay: float = 1.2, use_ocr: bool = True
    ) -> dict[str, Any]:
        from wechat_cv_send import search_and_send_by_cv

        out = search_and_send_by_cv(contact_name, message, delay=delay, use_ocr=use_ocr)
        if isinstance(out, dict):
            ok = out.get("status") == "success" or out.get("success") is True
            return {"success": ok, "message_sent": ok, **out}
        return {"success": bool(out), "message": str(out)}

    def get_current_contact(self, *, use_ocr: bool = True) -> dict[str, Any]:
        from wechat_cv_send import get_current_chat_contact_name

        return get_current_chat_contact_name(use_ocr=use_ocr)
