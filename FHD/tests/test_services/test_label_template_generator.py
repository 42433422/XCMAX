"""Tests for app.services.skills.label_template_generator.label_template_generator."""
from __future__ import annotations

import os
import tempfile
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
    _identify_fields,
    _pair_fields_by_grid,
    analyze_image,
    extract_text_with_ocr,
    generate_template_code,
    get_label_template_generator_skill,
)


# ---------------------------------------------------------------------------
# analyze_image
# ---------------------------------------------------------------------------


class TestAnalyzeImage:
    """Tests for analyze_image function."""

    def test_success_returns_analysis_dict(self, tmp_path):
        """analyze_image returns success dict for a valid image."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert result["file"] == "test.png"
        assert result["format"] == "PNG"
        assert result["mode"] == "RGB"
        assert result["size"]["width"] == 800
        assert result["size"]["height"] == 600
        assert "colors" in result
        assert "sections" in result

    def test_file_not_found_returns_failure(self):
        """analyze_image returns failure for missing file."""
        result = analyze_image("/nonexistent/path/image.png")
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_verbose_mode_adds_additional_info(self, tmp_path):
        """analyze_image with verbose=True adds additional_info."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_verbose.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=True)
        assert result["success"] is True
        assert "additional_info" in result
        assert "dpi" in result["additional_info"]
        assert "has_transparency" in result["additional_info"]
        assert "estimated_font_sizes" in result["additional_info"]

    def test_non_verbose_no_additional_info(self, tmp_path):
        """analyze_image without verbose does not add additional_info."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_noverbose.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=False)
        assert result["success"] is True
        assert "additional_info" not in result

    def test_rgba_image_has_transparency(self, tmp_path):
        """analyze_image detects RGBA transparency."""
        from PIL import Image

        img = Image.new("RGBA", (200, 200), (255, 255, 255, 128))
        img_path = str(tmp_path / "test_rgba.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=True)
        assert result["success"] is True
        assert result["additional_info"]["has_transparency"] is True

    def test_corrupted_image_returns_failure(self, tmp_path):
        """analyze_image returns failure for corrupted image."""
        bad_path = str(tmp_path / "bad.png")
        with open(bad_path, "wb") as f:
            f.write(b"not a real image")

        result = analyze_image(bad_path)
        assert result["success"] is False

    def test_small_image_has_main_section(self, tmp_path):
        """Small image gets a single 'main' section."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img_path = str(tmp_path / "small.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert len(result["sections"]) == 1
        assert result["sections"][0]["name"] == "main"


# ---------------------------------------------------------------------------
# _analyze_colors
# ---------------------------------------------------------------------------


class TestAnalyzeColors:
    """Tests for _analyze_colors helper."""

    def test_white_background(self):
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        result = _analyze_colors(img)
        assert result["background"] == "#ffffff"
        assert result["is_consistent_background"] is True

    def test_black_background(self):
        from PIL import Image

        img = Image.new("RGB", (100, 100), (0, 0, 0))
        result = _analyze_colors(img)
        assert result["background"] == "#000000"
        assert result["is_consistent_background"] is True

    def test_inconsistent_background(self):
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        # Draw different color in bottom-right corner
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        draw.rectangle([80, 80, 99, 99], fill=(255, 0, 0))
        result = _analyze_colors(img)
        assert result["is_consistent_background"] is False

    def test_returns_expected_keys(self):
        from PIL import Image

        img = Image.new("RGB", (100, 100), (128, 128, 128))
        result = _analyze_colors(img)
        assert "background" in result
        assert "is_consistent_background" in result
        assert "border" in result
        assert "text" in result


# ---------------------------------------------------------------------------
# _estimate_sections
# ---------------------------------------------------------------------------


class TestEstimateSections:
    """Tests for _estimate_sections helper."""

    def test_large_label_returns_5_sections(self):
        sections = _estimate_sections(800, 500)
        assert len(sections) == 5
        names = [s["name"] for s in sections]
        assert "product_number" in names
        assert "footer" in names

    def test_medium_label_returns_3_sections(self):
        sections = _estimate_sections(400, 300)
        assert len(sections) == 3
        names = [s["name"] for s in sections]
        assert "header" in names
        assert "content" in names
        assert "footer" in names

    def test_small_label_returns_1_section(self):
        sections = _estimate_sections(100, 100)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"

    def test_boundary_large(self):
        """Exactly 800x500 should be large."""
        sections = _estimate_sections(800, 500)
        assert len(sections) == 5

    def test_boundary_medium(self):
        """Exactly 400x300 should be medium."""
        sections = _estimate_sections(400, 300)
        assert len(sections) == 3

    def test_sections_have_required_keys(self):
        sections = _estimate_sections(800, 500)
        for s in sections:
            assert "name" in s
            assert "y_start" in s
            assert "y_end" in s
            assert "description" in s


# ---------------------------------------------------------------------------
# _estimate_font_sizes
# ---------------------------------------------------------------------------


class TestEstimateFontSizes:
    """Tests for _estimate_font_sizes helper."""

    def test_large_width(self):
        sizes = _estimate_font_sizes(800, 600)
        assert sizes["title"] == 70
        assert sizes["label"] == 40
        assert sizes["content"] == 58
        assert sizes["small"] == 38

    def test_medium_width(self):
        sizes = _estimate_font_sizes(400, 300)
        assert sizes["title"] == 40
        assert sizes["label"] == 24
        assert sizes["content"] == 32
        assert sizes["small"] == 20

    def test_small_width(self):
        sizes = _estimate_font_sizes(100, 100)
        assert sizes["title"] == 24
        assert sizes["label"] == 14
        assert sizes["content"] == 18
        assert sizes["small"] == 12

    def test_boundary_at_800(self):
        sizes = _estimate_font_sizes(800, 600)
        assert sizes["title"] == 70

    def test_boundary_at_400(self):
        sizes = _estimate_font_sizes(400, 300)
        assert sizes["title"] == 40


# ---------------------------------------------------------------------------
# _classify_field
# ---------------------------------------------------------------------------


class TestClassifyField:
    """Tests for _classify_field helper."""

    def test_known_label_product_name(self):
        field_type, field_key = _classify_field("品名")
        assert field_type == "fixed_label"
        assert field_key == "product_name"

    def test_known_label_color(self):
        field_type, field_key = _classify_field("颜色")
        assert field_type == "fixed_label"
        assert field_key == "color"

    def test_known_label_price(self):
        field_type, field_key = _classify_field("统一零售价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_price_suffix(self):
        field_type, field_key = _classify_field("零售价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_custom_price_suffix(self):
        """Labels ending with '价' should be classified as price."""
        field_type, field_key = _classify_field("批发价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_dynamic_label(self):
        field_type, field_key = _classify_field("自定义字段")
        assert field_type == "dynamic"
        assert field_key == "自定义字段"

    def test_all_known_labels(self):
        known = {
            "品名": "product_name",
            "颜色": "color",
            "货号": "item_number",
            "码段": "code_segment",
            "等级": "grade",
            "执行标准": "standard",
            "统一零售价": "price",
            "产品名称": "product_name",
            "产品编号": "product_number",
            "规格": "specification",
            "型号": "model",
            "价格": "price",
            "零售价": "price",
            "生产日期": "production_date",
            "保质期": "shelf_life",
            "产品规格": "product_spec",
            "检验员": "inspector",
        }
        for label, expected_key in known.items():
            field_type, field_key = _classify_field(label)
            assert field_type == "fixed_label", f"Expected fixed_label for {label}"
            assert field_key == expected_key, f"Expected {expected_key} for {label}"


# ---------------------------------------------------------------------------
# _identify_fields
# ---------------------------------------------------------------------------


class TestIdentifyFields:
    """Tests for _identify_fields helper."""

    def test_colon_separated_label_value(self):
        blocks = [
            {"text": "品名：运动鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.95}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "品名"
        assert fields[0]["value"] == "运动鞋"
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_name"

    def test_chinese_colon_separated(self):
        blocks = [
            {"text": "颜色:白色", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "颜色"
        assert fields[0]["value"] == "白色"

    def test_no_colon_with_known_label(self):
        blocks = [
            {"text": "产品编号 6808AA", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "产品编号"
        assert fields[0]["value"] == "6808AA"

    def test_no_colon_no_known_label_skipped(self):
        blocks = [
            {"text": "随机文本内容", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 0

    def test_no_colon_known_label_no_value_skipped(self):
        blocks = [
            {"text": "品名", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 0

    def test_empty_blocks(self):
        fields = _identify_fields([])
        assert fields == []

    def test_price_suffix_label_with_colon(self):
        blocks = [
            {"text": "批发价：100", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["field_key"] == "price"
        assert fields[0]["type"] == "fixed_label"

    def test_dynamic_label_with_colon(self):
        blocks = [
            {"text": "自定义：值", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "dynamic"
        assert fields[0]["field_key"] == "自定义"

    def test_field_position_preserved(self):
        blocks = [
            {"text": "品名：鞋", "left": 42, "top": 99, "width": 88, "height": 22, "conf": 0.88}
        ]
        fields = _identify_fields(blocks)
        assert fields[0]["position"]["left"] == 42
        assert fields[0]["position"]["top"] == 99
        assert fields[0]["confidence"] == 0.88


# ---------------------------------------------------------------------------
# _extract_fields_by_pattern
# ---------------------------------------------------------------------------


class TestExtractFieldsByPattern:
    """Tests for _extract_fields_by_pattern fallback."""

    def test_returns_list_of_dicts(self):
        result = _extract_fields_by_pattern("/any/path.png")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_each_field_has_required_keys(self):
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert "label" in field
            assert "value" in field
            assert "field_key" in field
            assert "type" in field
            assert field["type"] == "fixed_label"

    def test_contains_common_labels(self):
        result = _extract_fields_by_pattern("/any/path.png")
        labels = {f["label"] for f in result}
        assert "品名" in labels
        assert "颜色" in labels
        assert "货号" in labels


# ---------------------------------------------------------------------------
# _pair_fields_by_grid
# ---------------------------------------------------------------------------


class TestPairFieldsByGrid:
    """Tests for _pair_fields_by_grid helper."""

    def test_empty_text_blocks(self):
        result = _pair_fields_by_grid([], [0, 100], [0, 100])
        assert result == []

    def test_none_merged_horizontal(self):
        """merged_horizontal=None should default to empty list."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "运动鞋", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.85},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100])
        assert len(result) >= 1

    def test_pair_adjacent_blocks(self):
        """Two adjacent blocks in same row should be paired as label+value."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9, "cell_row": 0, "cell_col": 0},
            {"text": "运动鞋", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.85, "cell_row": 0, "cell_col": 1},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100])
        # Should have at least one field
        assert len(result) >= 1
        # Find the paired field
        paired = [f for f in result if f.get("value")]
        assert len(paired) >= 1

    def test_single_block_no_pair(self):
        """Single block with no adjacent should have empty value."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100])
        assert len(result) == 1
        assert result[0]["value"] == ""

    def test_merged_cell_field(self):
        """Block in a merged cell should have is_merged=True."""
        blocks = [
            {"text": "品名运动鞋", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 140, "height": 20, "conf": 0.9},
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100], merged)
        merged_fields = [f for f in result if f.get("is_merged")]
        assert len(merged_fields) >= 1


# ---------------------------------------------------------------------------
# extract_text_with_ocr
# ---------------------------------------------------------------------------


class TestExtractTextWithOcr:
    """Tests for extract_text_with_ocr function."""

    def test_import_error_returns_fallback(self, tmp_path):
        """When cv2/numpy not available, returns fallback fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_ocr.png")
        img.save(img_path)

        with patch.dict("sys.modules", {"cv2": None, "numpy": None}):
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False
            assert "fallback_fields" in result

    def test_file_not_found_returns_failure(self):
        result = extract_text_with_ocr("/nonexistent/image.png")
        assert result["success"] is False

    def test_recoverable_error_returns_fallback(self, tmp_path):
        """RECOVERABLE_ERRORS during OCR should return fallback."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_ocr_err.png")
        img.save(img_path)

        with patch("app.services.skills.label_template_generator.label_template_generator.Image") as mock_img:
            mock_img.open.side_effect = OSError("broken")
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False


# ---------------------------------------------------------------------------
# generate_template_code
# ---------------------------------------------------------------------------


class TestGenerateTemplateCode:
    """Tests for generate_template_code function."""

    def test_generates_code_for_valid_image(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "test_gen.png")
        img.save(img_path)

        code = generate_template_code(img_path)
        assert isinstance(code, str)
        assert "class LabelTemplateGenerator" in code
        assert "def generate_label" in code

    def test_custom_class_name(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_custom.png")
        img.save(img_path)

        code = generate_template_code(img_path, class_name="MyLabel")
        assert "class MyLabel" in code

    def test_failed_analysis_returns_error(self):
        code = generate_template_code("/nonexistent/image.png")
        assert "Error" in code or "error" in code.lower() or "分析失败" in code

    def test_with_ocr_result_generates_field_code(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "test_ocr_gen.png")
        img.save(img_path)

        ocr_result = {
            "success": True,
            "fields": [
                {"label": "品名", "value": "运动鞋", "field_key": "product_name",
                 "type": "fixed_label"},
            ],
        }
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "product_name" in code
        assert "运动鞋" in code

    def test_without_ocr_generates_basic_code(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_basic.png")
        img.save(img_path)

        code = generate_template_code(img_path, ocr_result=None)
        assert "class LabelTemplateGenerator" in code
        assert "generate_labels_for_order" in code


# ---------------------------------------------------------------------------
# LabelTemplateGeneratorSkill
# ---------------------------------------------------------------------------


class TestLabelTemplateGeneratorSkill:
    """Tests for LabelTemplateGeneratorSkill class."""

    def test_init(self):
        skill = LabelTemplateGeneratorSkill()
        assert skill.name == "label_template_generator"
        assert "标签模板" in skill.description

    def test_get_skill_info(self):
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["name"] == "label_template_generator"
        assert "parameters" in info
        assert "image_path" in info["parameters"]
        assert info["parameters"]["image_path"]["required"] is True

    def test_execute_success(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_exec.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch.object(skill, "execute", wraps=skill.execute):
            result = skill.execute(img_path, enable_ocr=False)
            assert result["success"] is True
            assert "analysis" in result
            assert "code" in result

    def test_execute_with_output_file(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_out.png")
        img.save(img_path)
        output_file = str(tmp_path / "output.py")

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(img_path, output_file=output_file, enable_ocr=False)
        assert result["success"] is True
        assert os.path.exists(output_file)
        with open(output_file) as f:
            content = f.read()
        assert "class LabelTemplateGenerator" in content

    def test_execute_invalid_image(self):
        skill = LabelTemplateGeneratorSkill()
        result = skill.execute("/nonexistent/image.png")
        assert result["success"] is False

    def test_execute_with_ocr_enabled(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_ocr_exec.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
            return_value={"success": False, "message": "OCR unavailable"},
        ):
            result = skill.execute(img_path, enable_ocr=True)
            assert result["success"] is True
            assert result["ocr_result"]["success"] is False

    def test_execute_output_file_write_error(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test_write_err.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        mock_analysis = {"success": True, "colors": [], "sections": [], "font_sizes": []}
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            return_value=mock_analysis,
        ), patch(
            "app.services.skills.label_template_generator.label_template_generator.generate_template_code",
            return_value="# generated code",
        ), patch("builtins.open", side_effect=PermissionError("no write")):
            result = skill.execute(img_path, output_file="/forbidden/output.py", enable_ocr=False)
            assert result["success"] is True
            assert "output_error" in result


# ---------------------------------------------------------------------------
# get_label_template_generator_skill (singleton)
# ---------------------------------------------------------------------------


class TestGetLabelTemplateGeneratorSkill:
    """Tests for singleton getter."""

    def test_returns_instance(self):
        import app.services.skills.label_template_generator.label_template_generator as mod

        # Reset singleton
        mod._skill_instance = None
        skill = get_label_template_generator_skill()
        assert isinstance(skill, LabelTemplateGeneratorSkill)

    def test_singleton_same_instance(self):
        import app.services.skills.label_template_generator.label_template_generator as mod

        mod._skill_instance = None
        skill1 = get_label_template_generator_skill()
        skill2 = get_label_template_generator_skill()
        assert skill1 is skill2
        # Cleanup
        mod._skill_instance = None
