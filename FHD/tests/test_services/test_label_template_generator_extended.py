"""Comprehensive tests for label_template_generator — covering _generate_code_with_fields,
_generate_basic_code, _pair_fields_by_grid edge cases, extract_text_with_ocr grid detection,
and LabelTemplateGeneratorSkill edge cases.

Extends the existing test file with additional coverage for uncovered lines.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.skills.label_template_generator.label_template_generator import (
    LabelTemplateGeneratorSkill,
    _analyze_colors,
    _classify_field,
    _estimate_font_sizes,
    _estimate_sections,
    _extract_fields_by_pattern,
    _generate_basic_code,
    _generate_code_with_fields,
    _identify_fields,
    _pair_fields_by_grid,
    analyze_image,
    extract_text_with_ocr,
    generate_template_code,
    get_label_template_generator_skill,
)


# ---------------------------------------------------------------------------
# _pair_fields_by_grid — additional edge cases
# ---------------------------------------------------------------------------


class TestPairFieldsByGridEdgeCases:
    """Additional edge cases for _pair_fields_by_grid."""

    def test_multiple_rows(self):
        """Blocks in different rows should be grouped separately."""
        blocks = [
            {"text": "品名", "y_center": 25, "center": (25, 25), "left": 10, "top": 15,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "运动鞋", "y_center": 25, "center": (75, 25), "left": 60, "top": 15,
             "width": 40, "height": 20, "conf": 0.85},
            {"text": "颜色", "y_center": 75, "center": (25, 75), "left": 10, "top": 65,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "白色", "y_center": 75, "center": (75, 75), "left": 60, "top": 65,
             "width": 40, "height": 20, "conf": 0.85},
        ]
        result = _pair_fields_by_grid(blocks, [0, 50, 100], [0, 50, 100])
        assert len(result) >= 2

    def test_block_in_merged_not_start_col_skipped(self):
        """Block in merged cell but not at start_col should be skipped."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "extra", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.8},
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100], merged)
        labels = [f["label"] for f in result]
        assert "extra" not in labels

    def test_next_block_in_merged_not_paired(self):
        """When next block is in merged cell, current block should not be paired with it."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "merged_val", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.8},
        ]
        merged = [{"row": 0, "start_col": 1, "end_col": 2}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 33, 66, 100], merged)
        first_field = result[0]
        assert first_field["label"] == "品名"
        assert first_field["value"] == ""

    def test_non_adjacent_columns_not_paired(self):
        """Blocks in non-adjacent columns should not be paired."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (15, 50), "left": 5, "top": 40,
             "width": 20, "height": 20, "conf": 0.9},
            {"text": "运动鞋", "y_center": 50, "center": (85, 50), "left": 75, "top": 40,
             "width": 20, "height": 20, "conf": 0.85},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 25, 50, 75, 100])
        assert len(result) >= 1
        first_field = [f for f in result if f["label"] == "品名"][0]
        assert first_field["value"] == ""

    def test_empty_merged_horizontal(self):
        """Empty merged_horizontal list should work the same as None."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100], [])
        assert len(result) == 1

    def test_merged_cell_with_two_cols(self):
        """Merged cell spanning 2 columns should have merge_cols=2."""
        blocks = [
            {"text": "长标签", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 140, "height": 20, "conf": 0.9},
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100], merged)
        merged_fields = [f for f in result if f.get("is_merged")]
        assert len(merged_fields) >= 1
        assert merged_fields[0]["merge_cols"] == 2


# ---------------------------------------------------------------------------
# _identify_fields — additional edge cases
# ---------------------------------------------------------------------------


class TestIdentifyFieldsEdgeCases:
    """Additional edge cases for _identify_fields."""

    def test_multiple_blocks_mixed(self):
        """Mix of colon-separated and no-colon fields."""
        blocks = [
            {"text": "品名：运动鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.95},
            {"text": "产品编号 6808AA", "left": 10, "top": 60, "width": 100, "height": 30, "conf": 0.9},
            {"text": "随机文本", "left": 10, "top": 100, "width": 100, "height": 30, "conf": 0.8},
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 2
        assert fields[0]["label"] == "品名"
        assert fields[1]["label"] == "产品编号"

    def test_colon_with_empty_value(self):
        """Colon-separated label with empty value should still create field."""
        blocks = [
            {"text": "品名：", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "品名"
        assert fields[0]["value"] == ""

    def test_no_colon_known_label_with_spaces(self):
        """Known label followed by value with spaces."""
        blocks = [
            {"text": "型号 ABC123", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "型号"
        assert fields[0]["value"] == "ABC123"
        assert fields[0]["field_key"] == "model"

    def test_full_text_preserved(self):
        """full_text should contain the original text."""
        blocks = [
            {"text": "品名：运动鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert fields[0]["full_text"] == "品名：运动鞋"

    def test_no_colon_known_label_type_field(self):
        """No-colon known label should have correct type classification."""
        blocks = [
            {"text": "产品名称 PE漆", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_name"

    def test_no_colon_known_label_dynamic_type(self):
        """No-colon known label not in special list should be dynamic."""
        blocks = [
            {"text": "颜色 红色", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "dynamic"


# ---------------------------------------------------------------------------
# _generate_code_with_fields
# ---------------------------------------------------------------------------


class TestGenerateCodeWithFields:
    """Tests for _generate_code_with_fields helper."""

    def test_generates_class_with_fields(self, tmp_path):
        """Generated code should contain field definitions."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "运动鞋", "field_key": "product_name", "type": "fixed_label"},
            {"label": "颜色", "value": "白色", "field_key": "color", "type": "fixed_label"},
            {"label": "自定义", "value": "值", "field_key": "custom", "type": "dynamic"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}

        code = _generate_code_with_fields(img_path, "MyLabel", 800, 600, colors, fields)
        assert "class MyLabel" in code
        assert "product_name" in code
        assert "color" in code
        assert "custom" in code
        assert "运动鞋" in code
        assert "白色" in code
        assert "generate_label" in code
        assert "get_field_template" in code

    def test_generated_code_has_field_type_info(self, tmp_path):
        """Generated code should include type and editable info per field."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test2.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "", "field_key": "product_name", "type": "fixed_label"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}

        code = _generate_code_with_fields(img_path, "TestGen", 400, 300, colors, fields)
        assert "fixed_label" in code
        assert "editable" in code

    def test_empty_fields(self, tmp_path):
        """Generated code with no fields should still be valid."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "empty_fields.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "EmptyGen", 400, 300, colors, [])
        assert "class EmptyGen" in code


# ---------------------------------------------------------------------------
# _generate_basic_code
# ---------------------------------------------------------------------------


class TestGenerateBasicCode:
    """Tests for _generate_basic_code helper."""

    def test_generates_basic_class(self, tmp_path):
        """Basic code should generate a simple label class."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "basic.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "BasicLabel", 400, 300, colors)
        assert "class BasicLabel" in code
        assert "generate_label" in code
        assert "generate_labels_for_order" in code
        assert "_draw_border" in code
        assert "_draw_content" in code

    def test_basic_code_contains_dimensions(self, tmp_path):
        """Basic code should contain width and height."""
        from PIL import Image

        img = Image.new("RGB", (600, 400), (255, 255, 255))
        img_path = str(tmp_path / "dims.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "DimLabel", 600, 400, colors)
        assert "self.width = 600" in code
        assert "self.height = 400" in code

    def test_basic_code_contains_colors(self, tmp_path):
        """Basic code should contain color settings."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (0, 0, 0))
        img_path = str(tmp_path / "colors.png")
        img.save(img_path)

        colors = {"background": "#000000", "border": "#ffffff", "text": "#ffffff"}
        code = _generate_basic_code(img_path, "ColorLabel", 400, 300, colors)
        assert "#000000" in code


# ---------------------------------------------------------------------------
# extract_text_with_ocr — grid detection
# ---------------------------------------------------------------------------


class TestExtractTextWithOcrGridDetection:
    """Tests for extract_text_with_ocr grid detection paths."""

    def test_ocr_import_error_returns_fallback(self, tmp_path):
        """When cv2/numpy not available, should return fallback fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_ocr.png")
        img.save(img_path)

        # Patch at the sys.modules level to prevent import
        with patch.dict("sys.modules", {"cv2": None}):
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False
            assert "fallback_fields" in result

    def test_ocr_recoverable_error_returns_fallback(self, tmp_path):
        """RECOVERABLE_ERRORS during OCR should return fallback."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "ocr_err.png")
        img.save(img_path)

        with patch(
            "app.services.skills.label_template_generator.label_template_generator.Image"
        ) as MockImage:
            MockImage.open.side_effect = OSError("broken")
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False


# ---------------------------------------------------------------------------
# generate_template_code — additional edge cases
# ---------------------------------------------------------------------------


class TestGenerateTemplateCodeEdgeCases:
    """Additional edge cases for generate_template_code."""

    def test_ocr_result_not_success(self, tmp_path):
        """When OCR result is not successful, should generate basic code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_ocr.png")
        img.save(img_path)

        ocr_result = {"success": False, "message": "OCR failed"}
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "class LabelTemplateGenerator" in code
        assert "generate_labels_for_order" in code

    def test_ocr_result_success_with_fields(self, tmp_path):
        """When OCR result is successful with fields, should generate field code."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "with_fields.png")
        img.save(img_path)

        ocr_result = {
            "success": True,
            "fields": [
                {"label": "品名", "value": "运动鞋", "field_key": "product_name", "type": "fixed_label"},
                {"label": "颜色", "value": "白色", "field_key": "color", "type": "fixed_label"},
            ],
        }
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "product_name" in code
        assert "color" in code
        assert "运动鞋" in code


# ---------------------------------------------------------------------------
# LabelTemplateGeneratorSkill — additional edge cases
# ---------------------------------------------------------------------------


class TestLabelTemplateGeneratorSkillEdgeCases:
    """Additional edge cases for LabelTemplateGeneratorSkill."""

    def test_execute_with_ocr_success(self, tmp_path):
        """execute() with OCR enabled and successful should include ocr_result."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "ocr_ok.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        mock_ocr_result = {
            "success": True,
            "fields": [
                {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"},
            ],
        }
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
            return_value=mock_ocr_result,
        ):
            result = skill.execute(img_path, enable_ocr=True)
            assert result["success"] is True
            assert result["ocr_result"]["success"] is True
            assert "code" in result

    def test_execute_with_verbose(self, tmp_path):
        """execute() with verbose=True should pass verbose to analyze_image."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "verbose.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            return_value={
                "success": True,
                "file": "verbose.png",
                "format": "PNG",
                "mode": "RGB",
                "size": {"width": 400, "height": 300},
                "colors": {"background": "#ffffff", "border": "#000000", "text": "#000000"},
                "sections": [],
            },
        ) as mock_analyze, patch(
            "app.services.skills.label_template_generator.label_template_generator.generate_template_code",
            return_value="# code",
        ), patch(
            "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
            return_value={"success": False},
        ):
            result = skill.execute(img_path, enable_ocr=False, verbose=True)
            mock_analyze.assert_called_once_with(img_path, verbose=True)

    def test_execute_recoverable_error(self, tmp_path):
        """execute() should catch RECOVERABLE_ERRORS and return failure."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "err.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            side_effect=OSError("disk error"),
        ):
            result = skill.execute(img_path)
            assert result["success"] is False
            assert "disk error" in result["message"]

    def test_execute_output_file_success(self, tmp_path):
        """execute() should write code to output_file."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "out.png")
        img.save(img_path)
        output_file = str(tmp_path / "output.py")

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(img_path, output_file=output_file, enable_ocr=False)
        assert result["success"] is True
        assert result.get("output_file") == output_file
        assert os.path.exists(output_file)

    def test_get_skill_info_parameters(self):
        """get_skill_info should return all expected parameters."""
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        params = info["parameters"]
        assert "image_path" in params
        assert "class_name" in params
        assert "output_file" in params
        assert "enable_ocr" in params
        assert "verbose" in params
        assert params["image_path"]["required"] is True
        assert params["class_name"]["required"] is False


# ---------------------------------------------------------------------------
# _analyze_colors — edge cases
# ---------------------------------------------------------------------------


class TestAnalyzeColorsEdgeCases:
    """Additional edge cases for _analyze_colors."""

    def test_rgba_image(self):
        """_analyze_colors should handle RGBA images."""
        from PIL import Image

        img = Image.new("RGBA", (100, 100), (255, 128, 64, 255))
        result = _analyze_colors(img)
        assert result["background"] == "#ff8040"
        assert result["is_consistent_background"] is True

    def test_l_mode_image(self):
        """_analyze_colors should handle L (grayscale) mode images."""
        from PIL import Image

        img = Image.new("L", (100, 100), 128)
        result = _analyze_colors(img)
        assert "background" in result

    def test_very_small_image(self):
        """_analyze_colors should handle images smaller than 10x10."""
        from PIL import Image

        img = Image.new("RGB", (5, 5), (255, 255, 255))
        result = _analyze_colors(img)
        assert "background" in result


# ---------------------------------------------------------------------------
# _estimate_sections — edge cases
# ---------------------------------------------------------------------------


class TestEstimateSectionsEdgeCases:
    """Additional edge cases for _estimate_sections."""

    def test_just_below_large_threshold(self):
        """799x499 should be medium, not large."""
        sections = _estimate_sections(799, 499)
        assert len(sections) == 3

    def test_just_below_medium_threshold(self):
        """399x299 should be small, not medium."""
        sections = _estimate_sections(399, 299)
        assert len(sections) == 1

    def test_zero_dimensions(self):
        """Zero dimensions should return small section."""
        sections = _estimate_sections(0, 0)
        assert len(sections) == 1


# ---------------------------------------------------------------------------
# _extract_fields_by_pattern — edge cases
# ---------------------------------------------------------------------------


class TestExtractFieldsByPatternEdgeCases:
    """Additional edge cases for _extract_fields_by_pattern."""

    def test_all_fields_have_ocr_placeholder(self):
        """All fallback fields should indicate OCR is needed."""
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert "OCR" in field["value"] or "ocr" in field["value"].lower() or "需要" in field["value"]

    def test_returns_seven_fields(self):
        """Should return exactly 7 fallback fields."""
        result = _extract_fields_by_pattern("/any/path.png")
        assert len(result) == 7
