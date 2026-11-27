"""扫描件 PDF 的 OCR 兜底（成熟组件复用：RapidOCR ONNX，Apache-2.0）。

只在 pdfplumber 提取不到文本的页面调用，避免对文本版 PDF 付多余算力。
未安装 rapidocr-onnxruntime 时返回空串，由调用方保持原错误提示。
"""

from __future__ import annotations

import logging
import math
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


def _recognize_blocks(engine: Any, array: Any) -> list[dict[str, Any]]:
    result, _ = engine(array)
    blocks: list[dict[str, Any]] = []
    for item in result or []:
        if len(item) < 2 or not str(item[1]).strip():
            continue
        score = item[2] if len(item) > 2 else None
        block: dict[str, Any] = {
            "text": str(item[1]).strip(),
            "confidence": float(score)
            if isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 1
            else None,
            "coordinate_space": "engine_input_pixels",
        }
        points = item[0]
        if hasattr(points, "tolist"):
            points = points.tolist()
        if (
            isinstance(points, (list, tuple))
            and points
            and all(
                isinstance(point, (list, tuple))
                and len(point) == 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)
                for point in points
            )
        ):
            xs, ys = zip(*points)
            block.update(
                polygon=[list(point) for point in points],
                left=min(xs),
                top=min(ys),
                width=max(xs) - min(xs),
                height=max(ys) - min(ys),
            )
        blocks.append(block)
    return blocks


def ocr_array_blocks(array: Any) -> list[dict[str, Any]]:
    """RapidOCR text evidence, never a table-structure result."""
    engine = _engine_or_none()
    if engine is None:
        return []
    try:
        return _recognize_blocks(engine, array)
    except BOUNDARY_ERRORS:
        logger.warning("OCR 识别失败", exc_info=True)
        return []


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
        return "\n".join(block["text"] for block in _recognize_blocks(engine, array))
    except BOUNDARY_ERRORS:
        logger.warning("OCR 识别失败", exc_info=True)
        return ""


def ocr_image_text(path: Any, *, max_side: int = 2400) -> str:
    """识别单张图片（png/jpg/webp 等）；失败返回空串。"""
    engine = _engine_or_none()
    if engine is None:
        return ""
    try:
        from PIL import Image

        image = Image.open(str(path)).convert("RGB")
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side))
        import numpy as np

        return "\n".join(block["text"] for block in _recognize_blocks(engine, np.array(image)))
    except BOUNDARY_ERRORS:
        logger.warning("图片 OCR 失败", exc_info=True)
        return ""


def reset_engine_for_tests() -> None:
    global _engine, _load_attempted
    with _lock:
        _engine = None
        _load_attempted = False
