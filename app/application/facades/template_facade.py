"""已废弃。"""
import warnings
from app.infrastructure.gateways import templates as _gw
warnings.warn("template_facade 已废弃", DeprecationWarning, stacklevel=2)
document_templates_service = _gw.document_templates_service
_extract_structured_excel_preview = _gw._extract_structured_excel_preview
__all__ = list(_gw.__all__)
