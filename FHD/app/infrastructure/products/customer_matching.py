"""客户名抽取与库内对齐。

Phase 3B 从 ``app.legacy.shared_utils`` 吸收。
"""

from __future__ import annotations

from app.infrastructure.products.db_read import find_matching_customer_unified


def extract_customer_name(text: str | None) -> str | None:
    if text is None:
        return None
    s = str(text).strip()
    return s or None


def find_matching_customer(name: str | None) -> str | None:
    return find_matching_customer_unified(name or "")


__all__ = [
    "extract_customer_name",
    "find_matching_customer",
]
