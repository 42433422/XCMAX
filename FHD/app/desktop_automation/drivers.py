"""桌面自动化驱动占位。

后端未安装时所有驱动 :meth:`is_available` 恒为 ``False``；真实桌面构建以同名模块覆盖。
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
