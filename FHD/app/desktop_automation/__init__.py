"""桌面自动化（RPA）子系统。

完整的桌面自动化后端（驱动真实桌面发微信/操作 UI）属于**可选的桌面端组件**，不随
服务端/容器构建一并分发。本包提供安全的「后端未安装」占位实现，保证：

- ``app.fastapi_routes.desktop_automation`` 路由及 ``app.services.user_cs_*`` 的懒导入
  能正常完成（消除历史上对不存在模块的 ``ModuleNotFoundError`` 潜在崩溃）；
- 所有动作型调用一律返回 ``success=False``，绝不假装已发送/已执行；
- 单测可对 :func:`app.desktop_automation.service.get_desktop_automation_service` 打桩。

桌面构建可用同名模块覆盖本占位以接入真实 RPA。
"""

from __future__ import annotations
