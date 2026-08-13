"""Product-list request normalization shared by dispatch and workflow execution."""

from __future__ import annotations

from typing import Any

PRODUCT_LIST_PHRASES = {
    "产品",
    "产品列表",
    "当前产品",
    "当前产品列表",
    "现有产品",
    "现有产品列表",
    "全部产品",
    "全部产品列表",
    "所有产品",
    "所有产品列表",
}


def is_full_product_list_phrase(value: str) -> bool:
    return value.strip() in PRODUCT_LIST_PHRASES


def inject_product_query_fallback(params: dict[str, Any], user_message: str) -> str:
    """Inject a real search token, while preserving an explicit full-list request."""
    from app.application.ai_chat.workflow_response_builder import normalize_product_float_query

    keyword = normalize_product_float_query(user_message)
    if keyword:
        params["keyword"] = keyword
    else:
        params.pop("keyword", None)
    return keyword
