"""文档模板网关。"""

from __future__ import annotations

from app.services import document_templates_service  # noqa: F401
from app.services.document_templates_service import _extract_structured_excel_preview  # noqa: F401

__all__ = ["document_templates_service", "_extract_structured_excel_preview"]
