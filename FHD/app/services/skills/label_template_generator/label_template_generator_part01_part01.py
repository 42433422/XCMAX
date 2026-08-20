# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module(
        "app.services.skills.label_template_generator.label_template_generator"
    )


def analyze_image(image_path: str, verbose: bool = False) -> dict[str, _facade().Any]:
    """
    分析图片并提取基本信息

    Args:
        image_path: 图片文件路径
        verbose: 是否输出详细信息

    Returns:
        包含图片分析结果的字典
    """
    img: _facade().Image.Image | None = None
    try:
        img = _facade().Image.open(image_path)
        width, height = img.size
        result = {
            "success": True,
            "file": _facade().Path(image_path).name,
            "format": img.format,
            "mode": img.mode,
            "size": {"width": width, "height": height},
            "colors": _facade()._analyze_colors(img),
            "sections": _facade()._estimate_sections(width, height),
        }
        if verbose:
            result["additional_info"] = {
                "dpi": img.info.get("dpi", "unknown"),
                "has_transparency": img.mode in ("RGBA", "LA"),
                "estimated_font_sizes": _facade()._estimate_font_sizes(width, height),
            }
        return result
    except FileNotFoundError:
        return {"success": False, "message": f"文件不存在：{image_path}"}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error("分析图片失败：%s", e)
        return {"success": False, "message": f"分析失败：{str(e)}"}
    finally:
        if img is not None:
            img.close()


def extract_text_with_ocr(image_path: str, use_regions: bool = True) -> dict[str, _facade().Any]:
    """
    使用 PaddleOCR 提取图片中的文本，并识别固定标签和可变数据

    Args:
        image_path: 图片文件路径
        use_regions: 是否使用分区域识别（提高准确率）
    """
    img: _facade().Image.Image | None = None
    try:
        import cv2
        import numpy as np

        img = _facade().Image.open(image_path)
        width, height = img.size
        img_array = np.array(img)
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
        horizontal_lines = []
        for y in range(gray.shape[0]):
            row = binary[y, :]
            continuous_start = None
            max_continuous_length = 0
            current_length = 0
            for x in range(len(row)):
                if row[x] > 0:
                    if continuous_start is None:
                        continuous_start = x
                    current_length += 1
                else:
                    if current_length > max_continuous_length:
                        max_continuous_length = current_length
                    continuous_start = None
                    current_length = 0
            if current_length > max_continuous_length:
                max_continuous_length = current_length
            if max_continuous_length > gray.shape[1] * 0.5:
                horizontal_lines.append(y)
        vertical_lines = []
        for x in range(gray.shape[1]):
            col = binary[:, x]
            continuous_start = None
            max_continuous_length = 0
            current_length = 0
            for y in range(len(col)):
                if col[y] > 0:
                    if continuous_start is None:
                        continuous_start = y
                    current_length += 1
                else:
                    if current_length > max_continuous_length:
                        max_continuous_length = current_length
                    continuous_start = None
                    current_length = 0
            if current_length > max_continuous_length:
                max_continuous_length = current_length
            if max_continuous_length > gray.shape[0] * 0.5:
                vertical_lines.append(x)
        horizontal_lines = sorted({int(y) for y in horizontal_lines})
        vertical_lines = sorted({int(x) for x in vertical_lines})

        def merge_close_lines(lines, threshold=50):
            if not lines:
                return []
            merged = [lines[0]]
            for line in lines[1:]:
                if line - merged[-1] > threshold:
                    merged.append(line)
            return merged

        def merge_very_close_lines(lines, threshold=5):
            if not lines:
                return []
            merged = [lines[0]]
            for line in lines[1:]:
                if line - merged[-1] > threshold:
                    merged.append(line)
                else:
                    merged[-1] = (merged[-1] + line) // 2
            return merged

        horizontal_lines = merge_very_close_lines(horizontal_lines, threshold=5)
        vertical_lines = merge_very_close_lines(vertical_lines, threshold=5)
        horizontal_lines = merge_close_lines(horizontal_lines, threshold=50)
        vertical_lines = merge_close_lines(vertical_lines, threshold=50)
        _facade().logger.info(
            "检测到网格：%s条水平线，%s条垂直线", len(horizontal_lines), len(vertical_lines)
        )
        from app.services.ocr_service import get_ocr_service

        ocr_svc = get_ocr_service()
        text_blocks = ocr_svc.recognize_text_blocks(img)
        if not text_blocks:
            return {
                "success": False,
                "message": "OCR 未识别到文本。请安装 paddlepaddle+paddleocr（推荐）或 easyocr，并检查图片清晰度。",
                "fallback_fields": _facade()._extract_fields_by_pattern(image_path),
            }
        _facade().logger.info(
            "OCR 识别到 %s 个文本块（引擎：%s）", len(text_blocks), ocr_svc.get_active_ocr_backend()
        )
        cells: list[dict[str, _facade().Any]] = []
        merged_cells: list[dict[str, _facade().Any]] = []
        if len(horizontal_lines) > 1 and len(vertical_lines) > 1:
            rows = len(horizontal_lines) - 1
            cols = len(vertical_lines) - 1
            for i in range(rows):
                for j in range(cols):
                    x = vertical_lines[j]
                    y = horizontal_lines[i]
                    w = vertical_lines[j + 1] - vertical_lines[j]
                    h = horizontal_lines[i + 1] - horizontal_lines[i]
                    cell = {
                        "row": i,
                        "col": j,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                        "should_merge_right": False,
                    }
                    if j < cols - 1:
                        right_border_x = x + w
                        border_black_count = 0
                        border_total = 0
                        for check_y in range(y, y + h):
                            if check_y < gray.shape[0] and right_border_x < gray.shape[1]:
                                border_total += 1
                                if binary[check_y, right_border_x] > 0:
                                    border_black_count += 1
                        if border_total > 0 and 0 < border_black_count < h * 0.5:
                            cell["should_merge_right"] = True
                    cells.append(cell)
            merged_cells = []
            visited = set()
            for i in range(rows):
                for j in range(cols):
                    cell_id = f"{i},{j}"
                    if cell_id in visited:
                        continue
                    cell = next((c for c in cells if c["row"] == i and c["col"] == j), {})
                    if not cell:
                        continue
                    merge_count = 1
                    while cell["should_merge_right"] and j + merge_count < cols:
                        visited.add(f"{i},{j + merge_count}")
                        merge_count += 1
                        if j + merge_count < cols:
                            next_cell = next(
                                (c for c in cells if c["row"] == i and c["col"] == j + merge_count),
                                None,
                            )
                            if next_cell:
                                cell = next_cell
                            else:
                                break
                    merged_cells.append(
                        {
                            "row": i,
                            "start_col": j,
                            "end_col": j + merge_count - 1,
                            "merge_cols": merge_count,
                            "x": vertical_lines[j],
                            "y": horizontal_lines[i],
                            "width": vertical_lines[j + merge_count] - vertical_lines[j],
                            "height": horizontal_lines[i + 1] - horizontal_lines[i],
                            "original_cols": list(range(j, j + merge_count)),
                        }
                    )
                    visited.add(cell_id)
        merged_cells_info = []
        for mc in merged_cells:
            if mc.get("start_col", 0) != mc.get("end_col", 0):
                merged_cells_info.append(
                    {"row": mc["row"], "start_col": mc["start_col"], "end_col": mc["end_col"]}
                )
        fields = _facade()._pair_fields_by_grid(
            text_blocks, horizontal_lines, vertical_lines, merged_cells_info
        )
        return {
            "success": True,
            "text_blocks": text_blocks,
            "fields": fields,
            "total_blocks": len(text_blocks),
            "grid": {
                "rows": len(horizontal_lines) - 1 if len(horizontal_lines) > 1 else 0,
                "cols": len(vertical_lines) - 1 if len(vertical_lines) > 1 else 0,
                "horizontal_lines": horizontal_lines,
                "vertical_lines": vertical_lines,
                "cells": merged_cells if merged_cells else cells,
            },
        }
    except ImportError as e:
        _facade().logger.warning("标签模板 OCR 依赖缺失：%s", e)
        return {
            "success": False,
            "message": f"缺少图像处理依赖：{e}（需 Pillow、numpy、opencv-python；OCR 需 paddleocr 或 easyocr）",
            "fallback_fields": _facade()._extract_fields_by_pattern(image_path),
        }
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error("OCR 提取失败：%s", e)
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "message": f"OCR 失败：{str(e)}",
            "fallback_fields": _facade()._extract_fields_by_pattern(image_path),
        }
    finally:
        if img is not None:
            img.close()
