"""Excel / AI 产品解析 V1 应用服务。"""

from __future__ import annotations

from typing import Any

_excel_import_app_service: "ExcelImportApplicationService | None" = None


class ExcelImportApplicationService:
    """Excel 导入与 AI 解析用例入口。"""

    def get_ai_product_parser(self) -> Any:
        from app.infrastructure.gateways.product import get_ai_product_parser

        return get_ai_product_parser()

    def get_product_import_service(self) -> Any:
        from app.application.product_import_app_service import (
            get_product_import_application_service,
        )

        return get_product_import_application_service()


def get_excel_import_app_service() -> ExcelImportApplicationService:
    global _excel_import_app_service
    if _excel_import_app_service is None:
        _excel_import_app_service = ExcelImportApplicationService()
    return _excel_import_app_service
