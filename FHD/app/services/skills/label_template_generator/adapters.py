"""Optional image processing and the canonical OCR service at explicit I/O boundaries."""

from __future__ import annotations

from collections.abc import Callable

from PIL import Image

from .grid import detect_grid
from .label_template_ports import Grid, OCRService


def load_grid_detector() -> Callable[[Image.Image], Grid]:
    import cv2
    import numpy as np

    def detect(image: Image.Image) -> Grid:
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        try:
            gray = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2GRAY)
            _, binary = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
            return detect_grid(binary)
        finally:
            if rgb is not image:
                rgb.close()

    return detect


def get_ocr_service() -> OCRService:
    from app.services.ocr_service import get_ocr_service as resolve_service

    return resolve_service()
