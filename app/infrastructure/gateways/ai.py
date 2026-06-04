"""AI 对话与 schema 索引网关。"""

from __future__ import annotations

from typing import Any


def get_ai_conversation_service() -> Any:
    from app.services.ai_conversation_service import get_ai_conversation_service as _g

    return _g()


def match_excel_import_roles_from_field_index(*args: Any, **kwargs: Any) -> Any:
    from app.services.ai_db_schema_index import match_excel_import_roles_from_field_index as _f

    return _f(*args, **kwargs)


def price_column_buckets_for_keys(*args: Any, **kwargs: Any) -> Any:
    from app.services.ai_db_schema_index import price_column_buckets_for_keys as _f

    return _f(*args, **kwargs)


__all__ = [
    "get_ai_conversation_service",
    "match_excel_import_roles_from_field_index",
    "price_column_buckets_for_keys",
]
