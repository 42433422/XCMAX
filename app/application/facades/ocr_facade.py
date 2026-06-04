"""OCR Facade（已废弃）：请使用 ``get_ocr_application_service()``。"""

from __future__ import annotations

import warnings

from app.application.ocr_app_service import get_ocr_application_service

warnings.warn(
    "app.application.facades.ocr_facade 已废弃，请使用 get_ocr_application_service()",
    DeprecationWarning,
    stacklevel=2,
)


def get_ocr_service():
    """兼容旧调用：返回底层 OCR 服务实例。"""
    return get_ocr_application_service()._ocr_service


__all__ = ["get_ocr_service"]
