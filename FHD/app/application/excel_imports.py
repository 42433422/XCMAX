"""Excel 导入应用层辅助。

Phase 3B 从 ``legacy-layer.customers_excel_import`` 与
``legacy-layer.products_bulk_import`` 吸收。
"""

from __future__ import annotations

import re as re
from collections.abc import Iterable as Iterable
from decimal import Decimal as Decimal
from decimal import InvalidOperation as InvalidOperation
from typing import Any as Any

from app.domain.app_pure.excel_imports import _LOST_LEGACY_SYMBOLS as _LOST_LEGACY_SYMBOLS
from app.domain.app_pure.excel_imports import _norm_header as _norm_header
from app.domain.app_pure.excel_imports import _norm_model as _norm_model
from app.domain.app_pure.excel_imports import _parse_price as _parse_price
from app.domain.app_pure.excel_imports import _pick_first as _pick_first
from app.domain.app_pure.excel_imports import (
    resolve_customer_excel_columns as resolve_customer_excel_columns,
)

__all__ = [
    "_norm_header",
    "_norm_model",
    "_parse_price",
    "resolve_customer_excel_columns",
]


def __getattr__(name: str):
    """Latent API fallback.

    历史上 ``legacy-layer.products_bulk_import`` 暴露过 ``_parse_price``、
    ``_norm_model``,``customers_excel_import`` 暴露过 ``run_customers_excel_import_bytes``,
    但这些实现在 2026-04 清理时已不存在; xcagi_compat 中仍有少数路由引用它们。
    此处抛出明确的 ImportError,让异常信息指向真实原因。
    """
    if name in _LOST_LEGACY_SYMBOLS:
        raise ImportError(
            f"{name!r} is not implemented in app.application.excel_imports; "
            "this function was lost in the backend → legacy-layer cleanup."
        )
    raise AttributeError(f"module 'app.application.excel_imports' has no attribute {name!r}")
