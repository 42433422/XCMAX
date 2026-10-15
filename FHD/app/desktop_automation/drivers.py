"""桌面自动化驱动。

macOS 驱动只做无需辅助功能授权的动作（按 bundle id 打开 / 查询运行状态），并如实报告
辅助功能授权；Windows 与 MCP 驱动未在本构建提供，:meth:`is_available` 恒为 ``False``。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform
import re
import shutil
import subprocess

BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{1,127}$")


class _BaseDriver:
    name = "base"

    def is_available(self) -> bool:
        return False


class WindowsDriver(_BaseDriver):
    name = "windows"


class MacDriver(_BaseDriver):
    name = "mac"

    def is_available(self) -> bool:
        return platform.system() == "Darwin" and bool(
            shutil.which("open") and shutil.which("osascript")
        )

    def accessibility_trusted(self) -> bool:
        """当前进程是否已获「辅助功能」授权（只查询，不弹系统授权框）。"""
        path = ctypes.util.find_library("ApplicationServices")
        if not path:
            return False
        try:
            return bool(ctypes.cdll.LoadLibrary(path).AXIsProcessTrusted())
        except (OSError, AttributeError):
            return False

    def _run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)

    def open_app(self, bundle_id: str) -> dict:
        done = self._run("open", "-b", bundle_id)
        return {"success": done.returncode == 0, "error": done.stderr.strip()[:300] or None}

    def is_running(self, bundle_id: str) -> bool:
        done = self._run("osascript", "-e", f'application id "{bundle_id}" is running')
        return done.returncode == 0 and done.stdout.strip() == "true"


class MCPDriver(_BaseDriver):
    name = "mcp"

    def __init__(self, target: str = "") -> None:
        self.target = target
