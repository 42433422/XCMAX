"""Render the selected structured label template; never substitute a sample template."""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from threading import RLock
from typing import Any

from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

_FONT_PATH = Path(__file__).resolve().parents[3] / "resources" / "fonts" / "NotoSansSC-Regular.ttf"
_FONT_NAME = "XCAGILabelNotoSC"
_RENDER_LOCK = RLock()
_FONT_CACHE: dict[str, Any] = {}


def _label_font():
    if not _FONT_PATH.is_file():
        raise ValueError("标签中文字体资源缺失，请修复安装后重试")
    key = str(_FONT_PATH)
    if key not in _FONT_CACHE:
        font = TTFont(_FONT_NAME, key, validate=1)
        pdfmetrics.registerFont(font)
        _FONT_CACHE[key] = font
    return _FONT_CACHE[key]


_BINDINGS = {
    "产品ID": "id",
    "产品名称": "name",
    "品名": "name",
    "名称": "name",
    "型号": "model_number",
    "货号": "model_number",
    "规格": "specification",
    "单价": "price",
    "价格": "price",
    "单位": "unit",
    "品牌": "brand",
    "分类": "category",
    "说明": "description",
    "库存数量": "quantity",
}
_ALIASES = {
    "product_name": "name",
    "product_id": "id",
    "model": "model_number",
    "spec": "specification",
}


def _number(value: Any, *, minimum: float = 0, maximum: float = 10000) -> float:
    if isinstance(value, bool):
        raise ValueError("模板位置或尺寸无效")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("模板位置或尺寸缺失") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError("模板位置或尺寸超出可输出范围")
    return number


def _field_text(field: dict, product: dict) -> str:
    label = str(field.get("label") or "").strip()
    kind = field.get("type")
    if kind == "fixed":
        value = str(field.get("value") if field.get("value") is not None else "")
    elif kind == "dynamic":
        binding = str(
            field.get("binding")
            or field.get("field_key")
            or field.get("key")
            or _BINDINGS.get(label)
            or ""
        )
        binding = _ALIASES.get(binding, binding)
        if (
            binding not in product
            or product[binding] is None
            or str(product[binding]).strip() == ""
        ):
            raise ValueError(
                f"字段「{label or binding}」缺少可用产品数据或字段绑定，请编辑模板后重试"
            )
        value = str(product[binding])
    else:
        raise ValueError(f"字段「{label}」类型暂不支持输出，请使用固定文字或产品动态字段")
    text = f"{label}: {value}" if label else value
    if not text.strip() or len(text) > 1000 or "\n" in text:
        raise ValueError("标签字段文字为空、过长或含换行，请调整模板")
    return text


def render_template_label(
    path: Path,
    template: dict,
    product: dict,
    copies: int,
    paper_width_mm: float,
    paper_height_mm: float,
) -> dict:
    # ReportLab TTFont subsetting has document state; do not interleave two documents.
    with _RENDER_LOCK:
        return _render_template_label(
            path, template, product, copies, paper_width_mm, paper_height_mm
        )


def _render_template_label(
    path: Path,
    template: dict,
    product: dict,
    copies: int,
    paper_width_mm: float,
    paper_height_mm: float,
) -> dict:
    """Produce one PDF page per copy, preserving template coordinates and background."""
    if template.get("category") != "label":
        raise ValueError("所选模板不是标签模板")
    preview = template.get("preview_data") or {}
    if not isinstance(preview, dict):
        raise ValueError("模板预览布局无效")
    size = preview.get("image_size") or {"width": 900, "height": 600}
    if not isinstance(size, dict):
        raise ValueError("模板画布尺寸无效")
    width = _number(size.get("width"), minimum=1, maximum=5000)
    height = _number(size.get("height"), minimum=1, maximum=5000)
    paper_width_mm = _number(paper_width_mm, minimum=10, maximum=500)
    paper_height_mm = _number(paper_height_mm, minimum=10, maximum=500)
    scale_x = paper_width_mm * 72 / 25.4 / width
    scale_y = paper_height_mm * 72 / 25.4 / height
    fields = template.get("fields")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 200:
        raise ValueError("模板没有可输出字段，或字段过多")
    font = _label_font()
    rendered: list[dict[str, Any]] = []
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("position"), dict):
            raise ValueError("模板字段缺少位置，无法按原模板输出")
        pos = field["position"]
        x, y = _number(pos.get("left")), _number(pos.get("top"))
        w, h = _number(pos.get("width"), minimum=1), _number(pos.get("height"), minimum=1)
        if x + w > width or y + h > height or field.get("rotation", 0) != 0:
            raise ValueError("字段超出画布或带有暂不支持的旋转，请调整模板")
        text = _field_text(field, product)
        for character in text:
            if not character.isspace() and ord(character) not in font.face.charToGlyph:
                raise ValueError(
                    f"标签中文字体缺少字符 U+{ord(character):04X}，请调整文字或更新字体"
                )
        font_size = _number(
            field.get("font_size", field.get("fontSize", 14)), minimum=6, maximum=144
        )
        font_size = min(font_size, h - 4)
        available = w - 10
        while font_size >= 6 and pdfmetrics.stringWidth(text, _FONT_NAME, font_size) > available:
            font_size -= 0.5
        if font_size < 6:
            raise ValueError(f"字段「{field.get('label', '')}」文字无法放入原位置，请扩大字段")
        rendered.append(
            {"text": text, "left": x, "top": y, "width": w, "height": h, "font_size": font_size}
        )
    grid = preview.get("grid") or {}
    if not isinstance(grid, dict):
        raise ValueError("模板网格无效")
    lines = {}
    for key, bound in (("horizontal_lines", height), ("vertical_lines", width)):
        raw = grid.get(key, [])
        if not isinstance(raw, list) or len(raw) > 500:
            raise ValueError("模板网格无效")
        lines[key] = [_number(v, maximum=bound) for v in raw]
    background = None
    if preview.get("image"):
        raw = preview["image"]
        if (
            not isinstance(raw, str)
            or len(raw) > 8_000_000
            or not raw.startswith(("data:image/png;base64,", "data:image/jpeg;base64,"))
        ):
            raise ValueError("模板背景必须是已保存的 PNG/JPEG 图片，不能读取外部地址")
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(base64.b64decode(raw.split(",", 1)[1], validate=True)))
            if image.width * image.height > 25_000_000:
                raise ValueError("模板背景过大")
            image.load()
            background = ImageReader(image)
        except (ValueError, OSError) as exc:
            raise ValueError("模板背景图片无法读取") from exc
    pdf = canvas.Canvas(
        str(path), pagesize=(paper_width_mm * 72 / 25.4, paper_height_mm * 72 / 25.4)
    )
    pdf.setTitle(str(template.get("name") or "标签"))
    for _ in range(copies):
        pdf.saveState()
        pdf.scale(scale_x, scale_y)
        if background:
            pdf.drawImage(background, 0, 0, width, height)
        pdf.setLineWidth(1)
        for y in lines["horizontal_lines"]:
            pdf.line(0, height - y, width, height - y)
        for x in lines["vertical_lines"]:
            pdf.line(x, 0, x, height)
        for field in rendered:
            # Opaque field area replaces OCR sample text in a saved background image.
            pdf.setFillColorRGB(1, 1, 1)
            pdf.rect(
                field["left"],
                height - field["top"] - field["height"],
                field["width"],
                field["height"],
                fill=1,
                stroke=0,
            )
            pdf.setFillColorRGB(0, 0, 0)
            pdf.setFont(_FONT_NAME, field["font_size"])
            pdf.drawString(
                field["left"] + 5, height - field["top"] - field["font_size"] - 2, field["text"]
            )
        pdf.restoreState()
        pdf.showPage()
    pdf.save()
    return {
        "fields": rendered,
        "width": width,
        "height": height,
        "paper_width_mm": paper_width_mm,
        "paper_height_mm": paper_height_mm,
        "pages": copies,
    }
