# -*- coding: utf-8 -*-
"""桌面自动化服务的安全占位实现。

见 :mod:`app.desktop_automation` 的包级说明。本占位**不连接任何真实桌面**：所有动作型
方法返回 ``{"success": False, ...}``。真实桌面构建可用同名模块覆盖。
"""

from __future__ import annotations

from typing import Any

_UNAVAILABLE = "desktop automation backend not installed in this build"


class DesktopAutomationService:
    """安全占位：永远报告「后端不可用」，绝不伪造执行结果。"""

    available: bool = False

    def list_profiles(self) -> list[dict[str, Any]]:
        return []

    def get_profile(self, app_id: str) -> dict[str, Any] | None:
        return None

    def register_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    def run_workflow(
        self,
        app_id: str,
        workflow: str,
        params: dict[str, Any] | None = None,
        *,
        driver: str | None = None,
    ) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    def find_element(self, app_id: str, element_id: str) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    async def bootstrap_app(self, app_id: str, *, vision_call: Any = None) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    def export_yolo(self, app_id: str) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    def send_wechat_message(self, contact: str, text: str) -> dict[str, Any]:
        return {"success": False, "message_sent": False, "error": _UNAVAILABLE}


_service: DesktopAutomationService | None = None


def get_desktop_automation_service() -> DesktopAutomationService:
    """返回进程级单例占位服务。"""
    global _service
    if _service is None:
        _service = DesktopAutomationService()
    return _service
