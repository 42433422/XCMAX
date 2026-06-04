"""MCP 驱动：委托外部 WeChat CV MCP 或自定义 MCP 工具。"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

from app.desktop_automation.deps import wechat_cv_fallback_allowed
from app.desktop_automation.drivers.base import DesktopDriver
from app.desktop_automation.models import WindowInfo

logger = logging.getLogger(__name__)


class MCPDriver(DesktopDriver):
    platform = "mcp"

    def __init__(self, mcp_kind: str = "wechat_cv"):
        self.mcp_kind = mcp_kind

    def is_available(self) -> bool:
        if self.mcp_kind == "wechat_cv":
            if not wechat_cv_fallback_allowed():
                return False
            try:
                from app.utils.path_utils import get_resource_path

                cv_path = get_resource_path("wechat_cv")
                return bool(cv_path and os.path.isdir(cv_path))
            except Exception:
                return False
        return bool(os.environ.get("DESKTOP_MCP_COMMAND"))

    def find_window(
        self, window_match: dict[str, list[str]], *, title_hint: str = ""
    ) -> WindowInfo | None:
        return WindowInfo(
            platform="mcp", x=0, y=0, width=1280, height=800, title=title_hint or "mcp"
        )

    def focus_window(self, window: WindowInfo) -> bool:
        return True

    def capture_window(self, window: WindowInfo) -> Any:
        return None

    def click(self, x: int, y: int, *, delay: float = 0.15) -> None:
        raise NotImplementedError("MCPDriver does not support direct click; use run_workflow")

    def paste_text(self, text: str) -> None:
        raise NotImplementedError("MCPDriver does not support direct paste; use run_workflow")

    def press_key(self, key: str) -> None:
        raise NotImplementedError("MCPDriver does not support direct key; use run_workflow")

    def send_wechat_message(self, contact_name: str, message: str) -> dict[str, Any]:
        if self.mcp_kind == "wechat_cv":
            return self._wechat_cv_send(contact_name, message)
        cmd = os.environ.get("DESKTOP_MCP_COMMAND", "").strip()
        if not cmd:
            return {"success": False, "error": "DESKTOP_MCP_COMMAND 未配置"}
        return self._invoke_external(cmd, contact_name, message)

    def _wechat_cv_send(self, contact_name: str, message: str) -> dict[str, Any]:
        try:
            from app.desktop_automation.adapters.wechat_windows import WeChatWindowsAdapter

            return WeChatWindowsAdapter().search_and_send(contact_name, message)
        except Exception as exc:
            logger.exception("mcp wechat_cv send failed")
            return {"success": False, "error": str(exc)}

    def _invoke_external(self, command: str, contact_name: str, message: str) -> dict[str, Any]:
        payload = json.dumps({"contact_name": contact_name, "message": message}, ensure_ascii=False)
        try:
            proc = subprocess.run(
                [command, payload],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.stdout.strip():
                try:
                    return json.loads(proc.stdout)
                except json.JSONDecodeError:
                    return {"success": proc.returncode == 0, "message": proc.stdout.strip()}
            return {"success": False, "error": proc.stderr.strip() or "external mcp failed"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


def list_mcp_tools() -> list[dict[str, str]]:
    """MCP 工具描述（供 run_mcp_desktop.py 与 REST 对齐）。"""
    return [
        {"name": "desktop_bootstrap_app", "description": "VLM 切图建库"},
        {"name": "desktop_run_workflow", "description": "执行 AppProfile workflow"},
        {"name": "desktop_find_element", "description": "调试：定位 UI 元素"},
        {"name": "desktop_list_profiles", "description": "列出已注册 AppProfile"},
        {"name": "desktop_send_message", "description": "向 App 联系人/群发送消息"},
    ]
