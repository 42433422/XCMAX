"""微信桌面自动化 RPA 桥 Mod（从 app/desktop_automation 迁移）。

历史：原 ``app/desktop_automation/`` 是主代码里的安全占位，9 个 API 路由前端零调用，
且 service/drivers 永远返回 unavailable。本 Mod 接管这 9 个路由与驱动实现，
主代码侧通过 ``app.services.wechat_sender`` 提供 CV 回退，不再依赖本 Mod。

真实驱动实现可覆盖 ``backend/service.py`` 的 ``DesktopAutomationService``。
"""

from __future__ import annotations
