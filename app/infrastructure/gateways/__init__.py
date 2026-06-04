"""
基础设施网关：应用层访问遗留业务实现的唯一入口。

实现仍位于 ``app.services``（迁移中），但 **application / facades 禁止** 直接 ``import app.services``。
"""

from __future__ import annotations
