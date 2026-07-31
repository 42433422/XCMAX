"""微信桌面自动化服务（从 app/desktop_automation/service.py 迁移）。

安全占位实现：所有动作型方法返回 ``{"success": False, ...}``。
真实桌面构建可用同名模块覆盖本文件，提供真实 RPA 驱动。
"""

from __future__ import annotations

from typing import Any

_UNAVAILABLE = "wechat automation mod installed but no real driver backend provided"


class DesktopAutomationService:
    """安全占位：永远报告「驱动未实现」，绝不伪造执行结果。

    真实驱动实现应覆盖本类，``available = True`` 并实现各动作方法。
    """

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
    """返回进程级单例服务。"""
    global _service
    if _service is None:
        _service = DesktopAutomationService()
    return _service
