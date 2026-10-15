"""桌面自动化（RPA）子系统。

macOS 上提供按应用档案执行的最小白名单工作流（打开应用、查询运行状态）并报告辅助功能
授权；需要界面操控的动作（元素查找、微信代发等）与 Windows/MCP 驱动在本构建不可用，
一律返回 ``success=False``，绝不假装已发送/已执行。
"""

from __future__ import annotations
