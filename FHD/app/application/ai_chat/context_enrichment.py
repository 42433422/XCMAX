"""Optional retrieval context enrichment with explicit search and contact resolver ports."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExcelContextSearch(Protocol):
    def query(self, *, index_id: str, query_text: str, top_k: int) -> dict[str, Any]: ...


class WechatContextResolver(Protocol):
    def __call__(self, message: str, context: dict[str, Any]) -> dict[str, Any] | None: ...


def inject_excel_vector_context(
    message: str, context: dict[str, Any], *, search_service: ExcelContextSearch | None = None
) -> dict[str, Any]:
    """
    若请求携带 excel_index_id，则做一次语义检索并将结果写入 excel_vector_context。
    与 context 中已有的 excel_analysis（专用 extract-grid 等）可同时存在，二者一并进入下游提示词。

    注意：本方法在 process_chat 中会先于 _try_handle_dynamic_workflow 调用，以便规则导入捷径
    也能携带 excel_vector_context（供日志/后续扩展；当前列映射仍以 extract-grid 与字段索引为主）。
    若未传 excel_index_id / excel_vector_index_id，则不会检索（前端需在聊天 context 中带上建索引返回的 id）。
    """
    if not isinstance(context, dict):
        return {}
    excel_index_id = str(
        context.get("excel_index_id") or context.get("excel_vector_index_id") or ""
    ).strip()
    if not excel_index_id:
        return context
    top_k_raw = context.get("excel_top_k", 5)
    try:
        top_k = int(top_k_raw)
    except RECOVERABLE_ERRORS:
        top_k = 5
    try:
        if search_service is None:
            from app.application import get_excel_vector_search_app_service

            search_service = get_excel_vector_search_app_service()
        result = search_service.query(index_id=excel_index_id, query_text=message, top_k=top_k)
        if result.get("success"):
            enriched = dict(context)
            enriched["excel_vector_context"] = {
                "index_id": excel_index_id,
                "query": message,
                "hits": result.get("hits", []),
            }
            return enriched
    except RECOVERABLE_ERRORS as err:
        logger.warning("注入 Excel 向量上下文失败: %s", err, exc_info=True)
    return context


def inject_wechat_contact_context(
    message: str, context: dict[str, Any], *, resolver: WechatContextResolver | None = None
) -> dict[str, Any]:
    """
    注入微信联系人情报（服务器侧微信同步基建 → 聊天智慧）。

    解析顺序：context.wechat_contact_key 显式指定 > 消息文本自动匹配已同步联系人名。
    命中时写入 ``wechat_contact_context``（由 PromptsMixin 渲染进 system prompt）；
    未命中时显式置 None，避免上一轮残留情报污染本轮（request_context 按 user 跨轮合并）。
    任何异常静默降级，不阻断聊天主链路。
    """
    if not isinstance(context, dict):
        return {}
    try:
        if resolver is None:
            from app.application.wechat_chat_context import resolve_wechat_chat_context

            resolver = resolve_wechat_chat_context
        payload = resolver(message, context)
    except RECOVERABLE_ERRORS as err:
        logger.warning("注入微信联系人情报失败: %s", err, exc_info=True)
        return context
    enriched = dict(context)
    enriched["wechat_contact_context"] = payload
    return enriched
