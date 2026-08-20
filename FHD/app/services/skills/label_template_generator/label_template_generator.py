"""
Label Template Generator - 从图片生成标签模板代码

基于参考图片，使用 PIL (Pillow) 库分析并生成对应的 Python 标签模板代码。
支持 OCR 识别固定标签和可变数据。
"""

import builtins
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


# Public indirection retained for callers/tests that replace either this
# module's writer or ``builtins.open`` without affecting PIL.Image.open.
# Resolve ``builtins.open`` at call time so both established patch contracts
# continue to work after the implementation was extracted.
def open(*args: Any, **kwargs: Any) -> Any:
    return builtins.open(*args, **kwargs)


from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _analyze_colors as _analyze_colors,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _classify_field as _classify_field,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _estimate_font_sizes as _estimate_font_sizes,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _estimate_sections as _estimate_sections,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _extract_fields_by_pattern as _extract_fields_by_pattern,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _identify_fields as _identify_fields,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    _pair_fields_by_grid as _pair_fields_by_grid,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    analyze_image as analyze_image,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    extract_text_with_ocr as extract_text_with_ocr,
)
from app.services.skills.label_template_generator.label_template_generator_part01 import (
    generate_template_code as generate_template_code,
)
from app.services.skills.label_template_generator.label_template_generator_part02 import (
    LabelTemplateGeneratorSkill as LabelTemplateGeneratorSkill,
)
from app.services.skills.label_template_generator.label_template_generator_part02 import (
    _generate_basic_code as _generate_basic_code,
)
from app.services.skills.label_template_generator.label_template_generator_part02 import (
    _generate_code_with_fields as _generate_code_with_fields,
)
from app.services.skills.label_template_generator.label_template_generator_part02 import (
    get_label_template_generator_skill as get_label_template_generator_skill,
)

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
# ruff: noqa: F401

_skill_instance: LabelTemplateGeneratorSkill | None = None
