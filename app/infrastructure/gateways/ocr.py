"""OCR 网关。"""

from __future__ import annotations

from typing import Any


def get_ocr_service() -> Any:
    from app.services.ocr_service import get_ocr_service as _g

    return _g()


__all__ = ["get_ocr_service", "OCRService"]

from app.services.ocr_service import OCRService  # noqa: E402
