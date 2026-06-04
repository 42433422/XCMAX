"""通用桌面自动化：VLM 切图建库 + 模板/YOLO 快执行 + MCP 可插拔。"""

from app.desktop_automation.service import DesktopAutomationService, get_desktop_automation_service

__all__ = ["DesktopAutomationService", "get_desktop_automation_service"]
