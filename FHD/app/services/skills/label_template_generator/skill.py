"""Coordinate image analysis, OCR, code production and optional output writing."""

from __future__ import annotations

from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .label_template_ports import SkillPorts


def execute(
    ports: SkillPorts,
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
    try:
        analysis = ports.analyze(image_path, verbose=verbose)
        if not analysis["success"]:
            return analysis
        ocr_result = None
        if enable_ocr:
            ocr_result = ports.extract(image_path)
            if ocr_result.get("success"):
                ports.logger.info("OCR 识别成功，提取 %s 个字段", len(ocr_result.get("fields", [])))
        code = ports.generate(image_path, class_name, ocr_result, verbose)
        result = {"success": True, "analysis": analysis, "ocr_result": ocr_result, "code": code}
        if output_file:
            try:
                with ports.open_writer(output_file, "w", encoding="utf-8") as f:
                    f.write(code)
                result["output_file"] = output_file
            except RECOVERABLE_ERRORS as e:
                result["output_error"] = str(e)
        return result
    except RECOVERABLE_ERRORS as e:
        ports.logger.error("生成标签模板失败：%s", e)
        return {"success": False, "message": str(e)}


def get_skill_info(name: str, description: str) -> dict[str, Any]:
    """获取技能信息"""
    return {
        "name": name,
        "description": description,
        "parameters": {
            "image_path": {"type": "string", "required": True, "description": "输入图片路径"},
            "class_name": {"type": "string", "required": False, "description": "生成的类名"},
            "output_file": {
                "type": "string",
                "required": False,
                "description": "输出 Python 文件路径",
            },
            "enable_ocr": {
                "type": "boolean",
                "required": False,
                "description": "是否启用 OCR 识别",
            },
            "verbose": {"type": "boolean", "required": False, "description": "是否生成详细代码"},
        },
    }
