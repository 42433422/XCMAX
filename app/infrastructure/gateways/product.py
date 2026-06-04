"""产品与导入网关。"""

from __future__ import annotations

from typing import Any


def get_products_service() -> Any:
    from app.services.products_service import ProductsService

    from app.infrastructure.persistence.product_repository_impl import (
        SQLAlchemyProductRepository,
    )

    service = ProductsService()
    service.set_repository(SQLAlchemyProductRepository())
    return service


def get_printer_service() -> Any:
    from app.services.printer_service import PrinterService

    return PrinterService()


def get_product_import_service() -> Any:
    from app.services.product_import_service import ProductImportService

    return ProductImportService()


def get_ai_product_parser() -> Any:
    from app.services.ai_product_parser import AIProductParser

    return AIProductParser()


__all__ = [
    "get_products_service",
    "get_printer_service",
    "get_product_import_service",
    "get_ai_product_parser",
    "ProductsService",
    "PrinterService",
    "ProductImportService",
]

from app.services.ai_product_parser import AIProductParser  # noqa: E402
from app.services.product_import_service import ProductImportService  # noqa: E402
from app.services.products_service import ProductsService  # noqa: E402
from app.services.printer_service import PrinterService  # noqa: E402
