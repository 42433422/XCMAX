"""OCR orchestration owns each image and receives recognition and field-pairing capabilities."""

from __future__ import annotations

from PIL import Image

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import OCRPorts, Payload


def extract_text_with_ocr(ports: OCRPorts, image_path: str, use_regions: bool = True) -> Payload:
    """Use the configured detector and OCR service while retaining the existing fallback envelope."""
    image: Image.Image | None = None
    try:
        detector = ports.load_grid_detector()
        image = ports.open_image(image_path)
        grid = detector(image)
        ports.logger.info(
            "检测到网格：%s条水平线，%s条垂直线", len(grid.horizontal), len(grid.vertical)
        )
        service = ports.service()
        text_blocks = service.recognize_text_blocks(image)
        if not text_blocks:
            return {
                "success": False,
                "message": "OCR 未识别到文本。请安装 paddlepaddle+paddleocr（推荐）或 easyocr，并检查图片清晰度。",
                "fallback_fields": ports.fallback(image_path),
            }
        ports.logger.info(
            "OCR 识别到 %s 个文本块（引擎：%s）", len(text_blocks), service.get_active_ocr_backend()
        )
        fields = ports.pair(text_blocks, grid.horizontal, grid.vertical, grid.merged)
        return {
            "success": True,
            "text_blocks": text_blocks,
            "fields": fields,
            "total_blocks": len(text_blocks),
            "grid": {
                "rows": len(grid.horizontal) - 1 if len(grid.horizontal) > 1 else 0,
                "cols": len(grid.vertical) - 1 if len(grid.vertical) > 1 else 0,
                "horizontal_lines": grid.horizontal,
                "vertical_lines": grid.vertical,
                "cells": grid.cells,
            },
        }
    except ImportError as exc:
        ports.logger.warning("标签模板 OCR 依赖缺失：%s", exc)
        return {
            "success": False,
            "message": f"缺少图像处理依赖：{exc}（需 Pillow、numpy、opencv-python；OCR 需 paddleocr 或 easyocr）",
            "fallback_fields": ports.fallback(image_path),
        }
    except RECOVERABLE_ERRORS as exc:
        ports.logger.exception("OCR 提取失败：%s", exc)
        return {
            "success": False,
            "message": f"OCR 失败：{str(exc)}",
            "fallback_fields": ports.fallback(image_path),
        }
    finally:
        if image is not None:
            image.close()
