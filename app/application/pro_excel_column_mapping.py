"""Excel 列角色推断与价格列解析（与 ai_chat_app_service 共享实现）。

列映射逻辑仍在 ``AIChatApplicationService`` 中；本模块暴露稳定导入路径供测试与后续迁移。
"""

from __future__ import annotations

from app.application.ai_chat_app_service import AIChatApplicationService

ProExcelColumnMappingMixin = AIChatApplicationService

__all__ = ["ProExcelColumnMappingMixin", "AIChatApplicationService"]
