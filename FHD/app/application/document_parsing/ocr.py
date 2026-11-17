"""扫描件 PDF 的 OCR 兜底（成熟组件复用：RapidOCR ONNX，Apache-2.0）。

只在 pdfplumber 提取不到文本的页面调用，避免对文本版 PDF 付多余算力。
未安装 rapidocr-onnxruntime 时返回空串，由调用方保持原错误提示。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_engine: Any | None = None
_load_attempted = False


def ocr_mode() -> str:
    """auto（仅空页）| off | force（所有页）。"""
    raw = (os.environ.get("XCAGI_PDF_OCR") or "auto").strip().lower()
    return raw if raw in {"auto", "off", "force"} else "auto"


def _engine_or_none() -> Any | None:
    global _engine, _load_attempted
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        if _load_attempted:
            return None
        _load_attempted = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
            logger.info("RapidOCR 引擎已加载")
        except BOUNDARY_ERRORS:
            logger.warning("rapidocr-onnxruntime 不可用，扫描件 OCR 跳过", exc_info=True)
            return None
        return _engine


def ocr_available() -> bool:
    return _engine_or_none() is not None


def ocr_page_text(page: Any, *, resolution: int = 150) -> str:
    """把 pdfplumber 页面渲染成图后 OCR，返回纯文本；失败返回空串。"""
    engine = _engine_or_none()
    if engine is None:
        return ""
    try:
        image = page.to_image(resolution=resolution).original
    except BOUNDARY_ERRORS:
        logger.debug("PDF 页面渲染失败，跳过 OCR", exc_info=True)
        return ""
    try:
        import numpy as np

        array = np.array(image.convert("RGB"))
        result, _ = engine(array)
    except BOUNDARY_ERRORS:
        logger.warning("OCR 识别失败", exc_info=True)
        return ""
    if not result:
        return ""
    lines = [str(item[1]).strip() for item in result if len(item) > 1 and str(item[1]).strip()]
    return "\n".join(lines)


def reset_engine_for_tests() -> None:
    global _engine, _load_attempted
    with _lock:
        _engine = None
        _load_attempted = False
