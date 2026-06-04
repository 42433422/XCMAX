"""Kitten 报表 / 文档生成网关。"""

from __future__ import annotations

from app.services.kitten_ai_document.generate import generate_office_file  # noqa: F401
from app.services.kitten_ai_document.pickup import pop_document_pickup, store_document_pickup  # noqa: F401
from app.services.kitten_business_snapshot import build_kitten_business_snapshot  # noqa: F401
from app.services.kitten_report import KittenReportExportService  # noqa: F401
from app.services.kitten_report.chart_data_service import chart_service  # noqa: F401
from app.services.kitten_report.docx_export import build_kitten_docx  # noqa: F401
from app.services.kitten_report.financial_plugins import (  # noqa: F401
    FinancialReportPlugin,
    InventoryValuationPlugin,
)
from app.services.kitten_report.save_service import analysis_save_service  # noqa: F401

__all__ = [
    "generate_office_file",
    "store_document_pickup",
    "pop_document_pickup",
    "build_kitten_business_snapshot",
    "KittenReportExportService",
    "chart_service",
    "build_kitten_docx",
    "FinancialReportPlugin",
    "InventoryValuationPlugin",
    "analysis_save_service",
]
