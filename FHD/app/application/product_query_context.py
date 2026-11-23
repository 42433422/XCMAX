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
    keyword = normalize_product_float_query(user_message)
    if keyword:
        params["keyword"] = keyword
    else:
        params.pop("keyword", None)
    return keyword


def normalize_product_float_query(raw: str) -> str:
    """Keep specific product terms while preserving an empty full-list query."""
    text = str(raw or "").strip()
    candidate = text.rstrip("。！？…").strip()
    for prefix in ("查询", "查一下", "查下", "查看", "看看", "看下", "查"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :].strip()
            break
    for scope in ("当前", "现有", "全部", "所有"):
        if candidate.startswith(scope):
            candidate = candidate[len(scope) :].strip()
            break
    if candidate in {"产品", "产品列表", "产品库"}:
        return ""
    return text
