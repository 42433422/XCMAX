"""桌面自动化驱动占位（从 app/desktop_automation/drivers.py 迁移）。

真实桌面构建以同名模块覆盖：实现 ``is_available`` 返回 True 并补全动作方法。
"""

from __future__ import annotations


class _BaseDriver:
    name = "base"

    def is_available(self) -> bool:
        return False


class WindowsDriver(_BaseDriver):
    name = "windows"


class MacDriver(_BaseDriver):
    name = "mac"


class MCPDriver(_BaseDriver):
    name = "mcp"

    def __init__(self, target: str = "") -> None:
        self.target = target
