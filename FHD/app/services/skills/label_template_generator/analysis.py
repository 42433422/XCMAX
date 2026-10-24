"""Image ownership, palette sampling and label layout estimates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from PIL import Image

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import ImageAnalysisPorts


def analyze_image(
    ports: ImageAnalysisPorts, image_path: str, verbose: bool = False
) -> dict[str, Any]:
    """
    分析图片并提取基本信息

    Args:
        image_path: 图片文件路径
        verbose: 是否输出详细信息

    Returns:
        包含图片分析结果的字典
    """
    img: Image.Image | None = None
    try:
        img = ports.open_image(image_path)
        width, height = img.size
        result = {
            "success": True,
            "file": Path(image_path).name,
            "format": img.format,
            "mode": img.mode,
            "size": {"width": width, "height": height},
            "colors": ports.colors(img),
            "sections": ports.sections(width, height),
        }
        if verbose:
            result["additional_info"] = {
                "dpi": img.info.get("dpi", "unknown"),
                "has_transparency": img.mode in ("RGBA", "LA"),
                "estimated_font_sizes": ports.font_sizes(width, height),
            }
        return result
    except FileNotFoundError:
        return {"success": False, "message": f"文件不存在：{image_path}"}
    except RECOVERABLE_ERRORS as e:
        ports.logger.error("分析图片失败：%s", e)
        return {"success": False, "message": f"分析失败：{str(e)}"}
    finally:
        if img is not None:
            img.close()


def _analyze_colors(img: Image.Image) -> dict[str, Any]:
    """分析图片中的主要颜色"""
    img_rgb: Image.Image | None = None
    try:
        img_rgb = img.convert("RGB")
        left, right = min(10, img.width - 1), max(0, img.width - 10)
        top, bottom = min(10, img.height - 1), max(0, img.height - 10)
        corners = [
            (left, top),
            (right, top),
            (left, bottom),
            (right, bottom),
        ]
        corner_colors = [cast(tuple[int, int, int], img_rgb.getpixel(pos)) for pos in corners]
        bg_color = corner_colors[0]
        is_consistent_bg = all(c == bg_color for c in corner_colors)
        return {
            "background": f"#{bg_color[0]:02x}{bg_color[1]:02x}{bg_color[2]:02x}",
            "is_consistent_background": is_consistent_bg,
            "border": "#000000",
            "text": "#000000",
        }
    except RECOVERABLE_ERRORS:
        return {
            "background": "#FFFFFF",
            "is_consistent_background": True,
            "border": "#000000",
            "text": "#000000",
        }
    finally:
        if img_rgb is not None and img_rgb is not img:
            img_rgb.close()


def _estimate_sections(width: int, height: int) -> list[dict[str, Any]]:
    """估算标签的分区"""
    sections = []
    if width >= 800 and height >= 500:
        sections = [
            {"name": "product_number", "y_start": 20, "y_end": 100, "description": "产品编号区域"},
            {"name": "product_name", "y_start": 110, "y_end": 190, "description": "产品名称区域"},
            {"name": "ratio", "y_start": 200, "y_end": 290, "description": "参考配比区域"},
            {"name": "date_spec", "y_start": 300, "y_end": 380, "description": "日期和规格区域"},
            {"name": "footer", "y_start": 390, "y_end": 460, "description": "底部提示区域"},
        ]
    elif width >= 400 and height >= 300:
        sections = [
            {"name": "header", "y_start": 20, "y_end": 80, "description": "标题区域"},
            {"name": "content", "y_start": 90, "y_end": 220, "description": "内容区域"},
            {"name": "footer", "y_start": 230, "y_end": 280, "description": "底部区域"},
        ]
    else:
        sections = [
            {"name": "main", "y_start": 10, "y_end": height - 10, "description": "主内容区域"}
        ]
    return sections


def _estimate_font_sizes(width: int, height: int) -> dict[str, int]:
    """估算字体大小"""
    if width >= 800:
        return {"title": 70, "label": 40, "content": 58, "small": 38}
    elif width >= 400:
        return {"title": 40, "label": 24, "content": 32, "small": 20}
    else:
        return {"title": 24, "label": 14, "content": 18, "small": 12}
