# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module(
        "app.services.skills.label_template_generator.label_template_generator"
    )


def _extract_fields_by_pattern(image_path: str) -> list[dict[str, _facade().Any]]:
    """
    基于常见标签模式提取字段（OCR 不可用时的回退方案）
    """
    return [
        {
            "label": "品名",
            "value": "（需要 OCR 识别）",
            "field_key": "product_name",
            "type": "fixed_label",
        },
        {
            "label": "颜色",
            "value": "（需要 OCR 识别）",
            "field_key": "color",
            "type": "fixed_label",
        },
        {
            "label": "货号",
            "value": "（需要 OCR 识别）",
            "field_key": "item_number",
            "type": "fixed_label",
        },
        {
            "label": "码段",
            "value": "（需要 OCR 识别）",
            "field_key": "code_segment",
            "type": "fixed_label",
        },
        {
            "label": "等级",
            "value": "（需要 OCR 识别）",
            "field_key": "grade",
            "type": "fixed_label",
        },
        {
            "label": "执行标准",
            "value": "（需要 OCR 识别）",
            "field_key": "standard",
            "type": "fixed_label",
        },
        {
            "label": "统一零售价",
            "value": "（需要 OCR 识别）",
            "field_key": "price",
            "type": "fixed_label",
        },
    ]


def _analyze_colors(img: _facade().Image.Image) -> dict[str, _facade().Any]:
    """分析图片中的主要颜色"""
    try:
        img_rgb = img.convert("RGB")
        corners = [
            (10, 10),
            (img.width - 10, 10),
            (10, img.height - 10),
            (img.width - 10, img.height - 10),
        ]
        corner_colors = [img_rgb.getpixel(pos) for pos in corners]
        bg_color = corner_colors[0]
        is_consistent_bg = all(c == bg_color for c in corner_colors)
        return {
            "background": f"#{bg_color[0]:02x}{bg_color[1]:02x}{bg_color[2]:02x}",
            "is_consistent_background": is_consistent_bg,
            "border": "#000000",
            "text": "#000000",
        }
    except _facade().RECOVERABLE_ERRORS:
        return {
            "background": "#FFFFFF",
            "is_consistent_background": True,
            "border": "#000000",
            "text": "#000000",
        }


def _estimate_sections(width: int, height: int) -> list[dict[str, _facade().Any]]:
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


def generate_template_code(
    image_path: str,
    class_name: str = "LabelTemplateGenerator",
    ocr_result: dict | None = None,
    verbose: bool = False,
) -> str:
    """
    从图片生成 Python 模板代码

    Args:
        image_path: 图片文件路径
        class_name: 生成的类名
        ocr_result: OCR 识别结果（可选）
        verbose: 是否生成详细代码

    Returns:
        生成的 Python 代码字符串
    """
    analysis = _facade().analyze_image(image_path, verbose=True)
    if not analysis["success"]:
        return f"# Error: {analysis.get('error', '分析失败')}"
    width = analysis["size"]["width"]
    height = analysis["size"]["height"]
    colors = analysis["colors"]
    if ocr_result and ocr_result.get("success"):
        fields = ocr_result.get("fields", [])
        code = _facade()._generate_code_with_fields(
            image_path, class_name, width, height, colors, fields
        )
    else:
        code = _facade()._generate_basic_code(image_path, class_name, width, height, colors)
    return code
