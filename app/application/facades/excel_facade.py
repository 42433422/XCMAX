"""Excel Facade（已废弃）：请使用 ``get_excel_import_app_service()``。"""

from __future__ import annotations

import warnings

from app.application.excel_import_app_service import get_excel_import_app_service

warnings.warn(
    "excel_facade 已废弃，请使用 get_excel_import_app_service()",
    DeprecationWarning,
    stacklevel=2,
)


def get_ai_product_parser():
    return get_excel_import_app_service().get_ai_product_parser()


def get_product_import_service():
    return get_excel_import_app_service().get_product_import_service()


__all__ = ["get_ai_product_parser", "get_product_import_service"]
