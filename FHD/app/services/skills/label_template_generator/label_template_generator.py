"""Public label generation API; the image, OCR and source-emission capabilities are explicit."""

from __future__ import annotations

import builtins
import logging
import re as re
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS

from . import adapters, analysis, codegen, ocr
from . import fields as field_recognition
from . import skill as skill_workflow
from .analysis import _analyze_colors as _analyze_colors
from .analysis import _estimate_font_sizes as _estimate_font_sizes
from .analysis import _estimate_sections as _estimate_sections
from .fields import _classify_field as _classify_field
from .fields import _extract_fields_by_pattern as _extract_fields_by_pattern
from .fields import _identify_fields as _identify_fields
from .ports import CodePorts, ImageAnalysisPorts, OCRPorts, SkillPorts, TemplateDescription

logger = logging.getLogger(__name__)


def open(*args: Any, **kwargs: Any) -> Any:
    return builtins.open(*args, **kwargs)


def analyze_image(image_path: str, verbose: bool = False) -> dict[str, Any]:
    """
    分析图片并提取基本信息

    Args:
        image_path: 图片文件路径
        verbose: 是否输出详细信息

    Returns:
        包含图片分析结果的字典
    """
    ports = ImageAnalysisPorts(
        Image.open, _analyze_colors, _estimate_sections, _estimate_font_sizes, logger
    )
    return analysis.analyze_image(ports, image_path, verbose=verbose)


def extract_text_with_ocr(image_path: str, use_regions: bool = True) -> dict[str, Any]:
    """
    使用 PaddleOCR 提取图片中的文本，并识别固定标签和可变数据

    Args:
        image_path: 图片文件路径
        use_regions: 是否使用分区域识别（提高准确率）
    """
    ports = OCRPorts(
        Image.open,
        adapters.load_grid_detector,
        adapters.get_ocr_service,
        _pair_fields_by_grid,
        _extract_fields_by_pattern,
        logger,
    )
    return ocr.extract_text_with_ocr(ports, image_path, use_regions=use_regions)


def _pair_fields_by_grid(
    text_blocks: list[dict],
    horizontal_lines: list[int],
    vertical_lines: list[int],
    merged_horizontal: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """
    基于网格布局智能配对字段（标签 + 值）

    Args:
        text_blocks: OCR 识别的文本块列表
        horizontal_lines: 水平线 Y 坐标列表
        vertical_lines: 垂直线 X 坐标列表
        merged_horizontal: 水平合并单元格列表

    Returns:
        字段列表
    """
    return field_recognition.pair_fields_by_grid(
        text_blocks, horizontal_lines, vertical_lines, merged_horizontal, classify=_classify_field
    )


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
    ports = CodePorts(analyze_image, _generate_code_with_fields, _generate_basic_code)
    return codegen.generate_template_code(ports, image_path, class_name, ocr_result, verbose)


def _generate_code_with_fields(
    image_path: str, class_name: str, width: int, height: int, colors: dict, fields: list[dict]
) -> str:
    """基于 OCR 识别的字段生成代码"""
    description = TemplateDescription(
        Path(image_path).name, class_name, width, height, colors, fields, datetime.now()
    )
    return codegen.render_template(description)


def _generate_basic_code(
    image_path: str, class_name: str, width: int, height: int, colors: dict
) -> str:
    """生成基础代码（无 OCR 时使用）"""
    description = TemplateDescription(
        Path(image_path).name, class_name, width, height, colors, None, datetime.now()
    )
    return codegen.render_template(description)


class LabelTemplateGeneratorSkill:
    """标签模板生成技能类"""

    def __init__(self):
        self.name = "label_template_generator"
        self.description = "从图片生成标签模板代码，支持基于参考图片创建 Python 标签生成器，自动识别固定标签和可变数据"

    def execute(
        self,
        image_path: str,
        class_name: str = "LabelTemplateGenerator",
        output_file: str | None = None,
        enable_ocr: bool = True,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """
        执行标签模板生成

        Args:
            image_path: 输入图片路径
            class_name: 生成的类名
            output_file: 输出 Python 文件路径（可选）
            enable_ocr: 是否启用 OCR 识别
            verbose: 是否生成详细代码

        Returns:
            生成结果
        """
        ports = SkillPorts(
            analyze_image, extract_text_with_ocr, generate_template_code, open, logger
        )
        return skill_workflow.execute(
            ports, image_path, class_name, output_file, enable_ocr, verbose
        )

    def get_skill_info(self) -> dict[str, Any]:
        """获取技能信息"""
        return skill_workflow.get_skill_info(self.name, self.description)


_skill_instance: LabelTemplateGeneratorSkill | None = None


def get_label_template_generator_skill() -> LabelTemplateGeneratorSkill:
    """获取标签模板生成技能单例"""
    global _skill_instance
    if _skill_instance is None:
        _skill_instance = LabelTemplateGeneratorSkill()
    return _skill_instance


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="标签模板生成器 - 从图片生成 Python 标签模板代码")
    parser.add_argument("-i", "--image", required=True, help="输入图片路径")
    parser.add_argument("-o", "--output", help="输出 Python 文件路径")
    parser.add_argument("-n", "--name", default="LabelTemplateGenerator", help="生成的类名")
    parser.add_argument("--no-ocr", action="store_true", help="禁用 OCR 识别")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出模式")

    args = parser.parse_args()

    skill = LabelTemplateGeneratorSkill()
    result = skill.execute(args.image, args.name, args.output, not args.no_ocr, args.verbose)

    if result["success"]:
        print("✓ 分析成功!")
        print(f"  图片：{result['analysis']['file']}")
        print(
            f"  尺寸：{result['analysis']['size']['width']} x {result['analysis']['size']['height']}"
        )

        if result.get("ocr_result") and result["ocr_result"].get("success"):
            fields = result["ocr_result"].get("fields", [])
            print(f"  OCR 识别字段数：{len(fields)}")
            for field in fields[:10]:  # 显示前 10 个
                print(f"    - {field['label']}: {field['value']} (类型：{field['type']})")

        if "output_file" in result:
            print(f"  代码已保存到：{result['output_file']}")
        else:
            print("\n" + "=" * 60)
            print(result["code"][:2000] + "...")  # 只显示前 2000 字符
    else:
        print(f"✗ 失败：{result.get('error', '未知错误')}")
        sys.exit(1)
