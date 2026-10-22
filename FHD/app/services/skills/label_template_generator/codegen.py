"""Emit one standalone label runtime using validated identifiers and Python data literals."""

from __future__ import annotations

import keyword
from pprint import pformat
from string import Template

from .ports import CodePorts, Payload, TemplateDescription


def generate_template_code(
    ports: CodePorts,
    image_path: str,
    class_name: str = "LabelTemplateGenerator",
    ocr_result: Payload | None = None,
    verbose: bool = False,
) -> str:
    analysis = ports.analyze(image_path, verbose=True)
    if not analysis["success"]:
        return f"# Error: {analysis.get('error', '分析失败')}"
    width, height = analysis["size"]["width"], analysis["size"]["height"]
    colors = analysis["colors"]
    if ocr_result and ocr_result.get("success"):
        return ports.with_fields(
            image_path, class_name, width, height, colors, ocr_result.get("fields", [])
        )
    return ports.basic(image_path, class_name, width, height, colors)


def render_template(description: TemplateDescription) -> str:
    if not description.class_name.isidentifier() or keyword.iskeyword(description.class_name):
        raise ValueError("class_name 必须为有效的 Python 类名")
    fields = {
        str(field.get("field_key", field["label"])): {
            "label": str(field["label"]),
            "default_value": str(field.get("value", "")),
            "type": str(field.get("type", "dynamic")),
            "editable": field.get("type", "dynamic") == "fixed_label",
        }
        for field in description.fields or []
    }
    note = (
        f"{description.class_name} - 标签模板生成器\n"
        f"此代码由 label-template-generator 自动生成，基于图片：{description.source}\n"
        f"生成时间：{description.created_at:%Y-%m-%d %H:%M:%S}"
    )
    uses_fields = description.fields is not None
    code = _PROGRAM.substitute(
        DOC=repr(note),
        CLASS=description.class_name,
        WIDTH=int(description.width),
        HEIGHT=int(description.height),
        BACKGROUND=repr(str(description.colors["background"])),
        BORDER=repr(str(description.colors["border"])),
        TEXT=repr(str(description.colors["text"])),
        FIELDS=pformat(fields, sort_dicts=False, indent=4).replace("\n", "\n        "),
        USE_FIELDS=uses_fields,
        DATA_PARAMETER="data" if uses_fields else "product_data",
        ORDER_PARAMETER='order_number: str = ""' if uses_fields else "order_number: str",
    )
    compile(code, "<generated-label>", "exec")
    return code


# Keep the exported runtime readable and self-contained: frozen applications do
# not have to locate a separate template resource, and generated files need no app imports.
_PROGRAM = Template(
    r'''# -*- coding: utf-8 -*-
$DOC

import logging
import os
import platform
import re
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)
RECOVERABLE_ERRORS = (OSError, ValueError, TypeError, RuntimeError, KeyError, IndexError, AttributeError)


class $CLASS:
    """标签模板生成器，支持固定标签和动态数据。"""

    def __init__(self, output_dir: Optional[str] = None):
        self.width = $WIDTH
        self.height = $HEIGHT
        self.bg_color = $BACKGROUND
        self.border_color = $BORDER
        self.text_color = $TEXT
        self.output_dir = output_dir or os.getcwd()
        self.fields = $FIELDS
        self._use_fields = $USE_FIELDS

    def _get_font(self, size: int):
        if platform.system() == "Windows":
            paths = ["C:\\Windows\\Fonts\\simhei.ttf", "C:\\Windows\\Fonts\\msyh.ttc", "C:\\Windows\\Fonts\\simsun.ttc"]
        elif platform.system() == "Darwin":
            paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"]
        else:
            paths = ["/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, ValueError):
                continue
        return ImageFont.load_default()

    @staticmethod
    def _filename_component(value: Any, default: str = "label") -> str:
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).replace(" ", "_")
        return value.strip(". ") or default

    def generate_label(self, $DATA_PARAMETER: Dict[str, Any], $ORDER_PARAMETER, label_index: int = 1) -> Optional[str]:
        """生成标签图片；返回输出目录内的文件名，操作失败时返回 None。"""
        payload = $DATA_PARAMETER
        try:
            with Image.new("RGB", (self.width, self.height), self.bg_color) as image:
                draw = ImageDraw.Draw(image)
                self._draw_border(draw)
                if self._use_fields:
                    self._draw_fields(image, draw, payload)
                else:
                    self._draw_content(draw, payload, order_number)
                os.makedirs(self.output_dir, exist_ok=True)
                if self._use_fields:
                    product_name = payload.get("product_name", payload.get("item_number", "label"))
                else:
                    product_name = payload.get("name", "") or payload.get("product_name", "")
                safe_name = self._filename_component(product_name, "")[:20]
                if order_number or not self._use_fields:
                    order = self._filename_component(order_number, "")
                    index = self._filename_component(label_index, "1")
                    filename = f"{order}_第{index}项_{safe_name}.png"
                else:
                    filename = f"label_{safe_name}_{datetime.now():%Y%m%d%H%M%S}.png"
                output_path = os.path.join(self.output_dir, filename)
                image.save(output_path)
            logger.info("标签已生成：%s", output_path)
            return filename
        except RECOVERABLE_ERRORS as exc:
            logger.error("生成标签失败：%s", exc)
            return None

    def _draw_border(self, draw: ImageDraw.ImageDraw):
        draw.rectangle([0, 0, self.width - 1, self.height - 1], outline=self.border_color, width=3)

    def _draw_content(self, draw: ImageDraw.ImageDraw, product_data: Dict[str, Any], order_number: str):
        label_font, value_font = self._get_font(36), self._get_font(40)
        rows = [("品名", "product_name", ""), ("货号", "item_number", ""), ("等级", "grade", "合格品")]
        for index, (label, key, default) in enumerate(rows):
            y = 40 + index * 50
            draw.text((40, y), f"{label}：", font=label_font, fill=self.text_color)
            draw.text((180, y), str(product_data.get(key, default)), font=value_font, fill=self.text_color)

    def _draw_fields(self, image: Image.Image, draw: ImageDraw.ImageDraw, data: Dict[str, Any]):
        y_offset = 40
        label_font, value_font, bold_font = self._get_font(36), self._get_font(40), self._get_font(48)
        for field_key, field_info in self.fields.items():
            value = data.get(field_key, field_info.get("default_value", ""))
            if field_key == "price":
                draw.text((40, y_offset), "统一零售价：¥ ", font=label_font, fill=self.text_color)
                draw.text((220, y_offset), str(value), font=bold_font, fill=self.text_color)
            else:
                draw.text((40, y_offset), f"{field_info['label']}: ", font=label_font, fill=self.text_color)
                draw.text((180, y_offset), str(value), font=value_font, fill=self.text_color)
            y_offset += 50
        self._draw_barcode(image, draw, data, y_offset + 20)

    def _barcode_placeholder(self, draw: ImageDraw.ImageDraw, y_offset: int, message: str):
        draw.rectangle([40, y_offset, self.width - 40, y_offset + 80], outline=self.border_color, width=1)
        draw.text((self.width // 2 - 60, y_offset + 90), message, font=self._get_font(20), fill=self.text_color)

    def _draw_barcode(self, image: Image.Image, draw: ImageDraw.ImageDraw, data: Dict[str, Any], y_offset: int):
        value = str(data.get("barcode_data") or "")
        if not value and data.get("auto_barcode", False):
            item = str(data.get("item_number", ""))
            value = item + str(data.get("code_segment", "")) if item else ""
        if not value:
            self._barcode_placeholder(draw, y_offset, "无条码数据")
            return
        try:
            from barcode import Code128, EAN13
            from barcode.writer import ImageWriter

            barcode_class = EAN13 if value.isdigit() and len(value) >= 12 else Code128
            value = value[:12] if barcode_class is EAN13 else value
            barcode = barcode_class(value, writer=ImageWriter())
            with BytesIO() as buffer:
                barcode.write(buffer, options={"module_width": 2, "module_height": 40, "font_size": 10, "text_distance": 5, "show_text": True})
                buffer.seek(0)
                with Image.open(buffer) as barcode_image:
                    image.paste(barcode_image, ((self.width - 360) // 2, y_offset))
        except ImportError:
            self._barcode_placeholder(draw, y_offset, "1txm.com")
        except RECOVERABLE_ERRORS as exc:
            logger.error("绘制条码失败：%s", exc)
            self._barcode_placeholder(draw, y_offset, "无条码数据")

    def get_field_template(self) -> Dict[str, Any]:
        return {
            key: {"label": info["label"], "type": info["type"], "editable": info["editable"], "example_value": info.get("default_value", "")}
            for key, info in self.fields.items()
        }

    def generate_labels_for_order(self, order_number: str, products: list) -> list:
        labels = []
        for index, product in enumerate(products, 1):
            filename = self.generate_label(product, order_number, index)
            if filename:
                labels.append({"filename": filename, "order_number": order_number, "label_index": index})
        return labels


def example_usage():
    generator = $CLASS(output_dir="./labels")
    data = {"product_name": "示例产品", "item_number": "12345", "grade": "合格品"}
    filename = generator.generate_label(data, "ORDER-001", 1)
    print(f"生成的标签：{filename}")


if __name__ == "__main__":
    example_usage()
'''
)
