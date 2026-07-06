"""
AI 聊天确认/审批应用服务

从 ``ai_chat_app_service.py`` 拆分而来（P0：拆分 5 个独立 app service）。

职责：
- 处理「上传文件后追问确认导入」这类轻量确认流程（``_handle_confirmation_flow``）
- 为工作流确认卡片附加结构化 ``approval_card`` 载荷（``_enrich_confirmation_inner``），
  供 Chat 内联确认 UI（Wave 2）与动态工作流（Workflow）复用

以 Mixin 形式提供给 ``AIChatApplicationService`` 组合继承，方法内的 ``self`` 在实际运行时
指向组合后的 ``AIChatApplicationService`` 实例（依赖其 ``__init__`` 提供的 ``ai_service`` 属性），
因此这里的方法签名与实现与拆分前保持一致，不改变任何行为。

注意：本模块中的「Approval」特指聊天确认流程（confirmation flow），与
``app.application.workflow.get_approval_service()`` 返回的审批域服务（approval_service，
用于动态工作流的高风险节点审批请求）是两个不同的概念，后者仍由 Workflow 子服务持有。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _enrich_confirmation_inner(inner: dict[str, Any], *, action: str) -> dict[str, Any]:
    """Attach structured approval_card for Chat inline confirm UI (Wave 2)."""
    from app.application.workflow.approval_card import build_approval_card_payload

    enriched = dict(inner)
    enriched["approval_card"] = build_approval_card_payload(action=action, inner=inner)
    return enriched


class AIChatApprovalService:
    """
    AI 聊天确认流程子服务（Mixin）

    处理文件导入等场景下的用户确认应答，供 ``AIChatApplicationService`` 组合使用。
    """

    def _handle_confirmation_flow(
        self, user_id: str, message: str, file_context: dict[str, Any] | None
    ) -> None:
        """处理确认流程"""
        if not file_context:
            return

        if message not in ("是", "好的", "确认", "yes", "ok", "好"):
            return

        saved_name = file_context.get("saved_name")
        unit_name = file_context.get("unit_name_guess") or file_context.get("unit_name", "")
        suggested_use = file_context.get("suggested_use", "")

        if saved_name and suggested_use == "unit_products_db" and unit_name:
            self.ai_service.set_pending_confirmation(
                user_id,
                {
                    "type": "import_unit_products",
                    "tool_key": "sqlite_import_unit_products",
                    "params": {
                        "saved_name": saved_name,
                        "unit_name": unit_name,
                    },
                    "description": f"导入 {unit_name} 的产品",
                },
            )
            logger.info("用户 %s 确认导入文件：%s -> %s", user_id, saved_name, unit_name)
