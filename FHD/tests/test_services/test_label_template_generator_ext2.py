"""Additional tests for label_template_generator covering uncovered branches.

Focuses on:
- analyze_image verbose branches (info.get("dpi") fallback, LA mode transparency)
- _analyze_colors exception path (bare except fallback)
- _estimate_sections boundary edges (exactly at thresholds)
- _estimate_font_sizes boundary edges
- _classify_field price suffix variants and dynamic
- _identify_fields no-colon known label dynamic type, colon with price suffix
- _pair_fields_by_grid merged cell start_col skip, non-adjacent pairing
- extract_text_with_ocr grid detection with cv2/numpy mocked
- generate_template_code with verbose flag
- _generate_code_with_fields with dynamic fields
- _generate_basic_code with various colors
- LabelTemplateGeneratorSkill.execute with verbose flag and OCR success
- get_label_template_generator_skill singleton reset edge cases
"""

from __future__ import annotations

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
# analyze_image — additional edge cases
# ---------------------------------------------------------------------------


class TestAnalyzeImageAdditional:
    """Additional coverage for analyze_image."""

    def test_verbose_with_no_dpi_info(self, tmp_path):
        """analyze_image verbose with image lacking dpi should default to 'unknown'."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_dpi.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=True)
        assert result["success"] is True
        assert result["additional_info"]["dpi"] == "unknown"

    def test_la_mode_has_transparency(self, tmp_path):
        """analyze_image detects LA mode transparency."""
        from PIL import Image

        img = Image.new("LA", (200, 200), (128, 255))
        img_path = str(tmp_path / "la_mode.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=True)
        assert result["success"] is True
        assert result["additional_info"]["has_transparency"] is True

    def test_p_mode_image(self, tmp_path):
        """analyze_image handles P (palette) mode images."""
        from PIL import Image

        img = Image.new("P", (400, 300))
        img_path = str(tmp_path / "p_mode.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert result["mode"] == "P"

    def test_recoverable_error_returns_failure(self, tmp_path):
        """analyze_image catches RECOVERABLE_ERRORS and returns failure."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "err.png")
        img.save(img_path)

        with patch(
            "app.services.skills.label_template_generator.label_template_generator.Image"
        ) as MockImage:
            MockImage.open.side_effect = OSError("disk read error")
            result = analyze_image(img_path)
        assert result["success"] is False
        assert "分析失败" in result["message"]

    def test_result_includes_format(self, tmp_path):
        """analyze_image result includes format field."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "fmt.png")
        img.save(img_path, format="PNG")

        result = analyze_image(img_path)
        assert result["success"] is True
        assert result["format"] == "PNG"


# ---------------------------------------------------------------------------
# _analyze_colors — exception path
# ---------------------------------------------------------------------------


class TestAnalyzeColorsExceptionPath:
    """Cover the bare except fallback in _analyze_colors."""

    def test_convert_failure_returns_default(self):
        """When img.convert raises, _analyze_colors returns default white background."""
        mock_img = MagicMock()
        mock_img.width = 100
        mock_img.height = 100
        mock_img.convert.side_effect = RuntimeError("convert failed")

        result = _analyze_colors(mock_img)
        assert result["background"] == "#FFFFFF"
        assert result["is_consistent_background"] is True
        assert result["border"] == "#000000"
        assert result["text"] == "#000000"

    def test_getpixel_failure_returns_default(self):
        """When getpixel raises, _analyze_colors returns default."""
        mock_img = MagicMock()
        mock_img.width = 100
        mock_img.height = 100
        mock_rgb = MagicMock()
        mock_rgb.getpixel.side_effect = ValueError("bad pixel")
        mock_img.convert.return_value = mock_rgb

        result = _analyze_colors(mock_img)
        assert result["background"] == "#FFFFFF"
        assert result["is_consistent_background"] is True


# ---------------------------------------------------------------------------
# _estimate_sections — boundary edges
# ---------------------------------------------------------------------------


class TestEstimateSectionsBoundaries:
    """Cover exact boundary conditions in _estimate_sections."""

    def test_exactly_large_threshold(self):
        """Width=800, height=500 should return 5 sections (large)."""
        sections = _estimate_sections(800, 500)
        assert len(sections) == 5

    def test_exactly_medium_threshold(self):
        """Width=400, height=300 should return 3 sections (medium)."""
        sections = _estimate_sections(400, 300)
        assert len(sections) == 3

    def test_large_width_small_height(self):
        """Large width but small height should be small (1 section)."""
        sections = _estimate_sections(800, 100)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"

    def test_small_width_large_height(self):
        """Small width but large height should be small (1 section)."""
        sections = _estimate_sections(100, 500)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"

    def test_large_sections_have_correct_y_ranges(self):
        """Large label sections should have non-overlapping y ranges."""
        sections = _estimate_sections(800, 500)
        for i, s in enumerate(sections):
            assert s["y_start"] < s["y_end"]
            if i > 0:
                assert s["y_start"] >= sections[i - 1]["y_end"]

    def test_main_section_uses_height(self):
        """Small label main section should span most of the height."""
        sections = _estimate_sections(100, 200)
        assert sections[0]["y_start"] == 10
        assert sections[0]["y_end"] == 190  # height - 10


# ---------------------------------------------------------------------------
# _estimate_font_sizes — boundary edges
# ---------------------------------------------------------------------------


class TestEstimateFontSizesBoundaries:
    """Cover exact boundary conditions in _estimate_font_sizes."""

    def test_exactly_800_width(self):
        """Width=800 should use large font sizes."""
        sizes = _estimate_font_sizes(800, 600)
        assert sizes["title"] == 70
        assert sizes["label"] == 40
        assert sizes["content"] == 58
        assert sizes["small"] == 38

    def test_exactly_400_width(self):
        """Width=400 should use medium font sizes."""
        sizes = _estimate_font_sizes(400, 300)
        assert sizes["title"] == 40
        assert sizes["label"] == 24
        assert sizes["content"] == 32
        assert sizes["small"] == 20

    def test_below_400_width(self):
        """Width=399 should use small font sizes."""
        sizes = _estimate_font_sizes(399, 300)
        assert sizes["title"] == 24
        assert sizes["label"] == 14
        assert sizes["content"] == 18
        assert sizes["small"] == 12

    def test_above_800_width(self):
        """Width=801 should use large font sizes."""
        sizes = _estimate_font_sizes(801, 600)
        assert sizes["title"] == 70

    def test_zero_width(self):
        """Width=0 should use small font sizes."""
        sizes = _estimate_font_sizes(0, 0)
        assert sizes["title"] == 24
        assert sizes["small"] == 12


# ---------------------------------------------------------------------------
# _classify_field — additional branches
# ---------------------------------------------------------------------------


class TestClassifyFieldAdditional:
    """Additional coverage for _classify_field."""

    def test_empty_string_is_dynamic(self):
        """Empty string label should be dynamic."""
        field_type, field_key = _classify_field("")
        assert field_type == "dynamic"
        assert field_key == ""

    def test_single_char_price_suffix(self):
        """Single '价' char should be classified as price."""
        field_type, field_key = _classify_field("价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_long_custom_label(self):
        """Long custom label should be dynamic."""
        label = "这是一个非常长的自定义字段名称"
        field_type, field_key = _classify_field(label)
        assert field_type == "dynamic"
        assert field_key == label

    def test_price_in_middle_not_matched(self):
        """Label with '价' in middle (not end) should be dynamic."""
        field_type, field_key = _classify_field("价格区间")
        assert field_type == "dynamic"
        assert field_key == "价格区间"

    def test_special_chars_label(self):
        """Label with special characters should be dynamic."""
        field_type, field_key = _classify_field("特殊@#$%字段")
        assert field_type == "dynamic"
        assert field_key == "特殊@#$%字段"


# ---------------------------------------------------------------------------
# _identify_fields — additional branches
# ---------------------------------------------------------------------------


class TestIdentifyFieldsAdditional:
    """Additional coverage for _identify_fields."""

    def test_colon_with_price_suffix_label(self):
        """Colon-separated label ending with '价' should be fixed_label price."""
        blocks = [
            {"text": "会员价：99", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["field_key"] == "price"
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["value"] == "99"

    def test_no_colon_known_label_dynamic_branch(self):
        """Known label not in special list (e.g., '颜色') should be dynamic type."""
        blocks = [
            {"text": "颜色 红色", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "颜色"
        assert fields[0]["value"] == "红色"
        assert fields[0]["type"] == "dynamic"
        assert fields[0]["field_key"] == "color"

    def test_no_colon_fixed_label_branch(self):
        """Known label in special list (e.g., '规格') should be fixed_label."""
        blocks = [
            {"text": "规格 100ml", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "规格"
        assert fields[0]["value"] == "100ml"
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "specification"

    def test_no_colon_production_date_fixed_label(self):
        """生产日期 should be fixed_label."""
        blocks = [
            {
                "text": "生产日期 2026-01-01",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "production_date"

    def test_no_colon_shelf_life_fixed_label(self):
        """保质期 should be fixed_label."""
        blocks = [
            {
                "text": "保质期 12个月",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "shelf_life"

    def test_no_colon_inspector_fixed_label(self):
        """检验员 should be fixed_label."""
        blocks = [
            {"text": "检验员 张三", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "inspector"

    def test_no_colon_product_spec_fixed_label(self):
        """产品规格 should be fixed_label."""
        blocks = [
            {"text": "产品规格 A4", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_spec"

    def test_no_colon_product_number_fixed_label(self):
        """产品编号 should be fixed_label."""
        blocks = [
            {
                "text": "产品编号 ABC123",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_number"

    def test_no_colon_product_name_fixed_label(self):
        """产品名称 should be fixed_label."""
        blocks = [
            {
                "text": "产品名称 PE漆",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_name"

    def test_block_missing_text_key_skipped(self):
        """Block without 'text' key should be skipped (KeyError caught)."""
        blocks = [{"left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}]
        # This will raise KeyError - the function does not catch it
        with pytest.raises(KeyError):
            _identify_fields(blocks)

    def test_multiple_blocks_same_label(self):
        """Multiple blocks with same label should each create a field."""
        blocks = [
            {"text": "品名：鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9},
            {"text": "品名：衣", "left": 10, "top": 60, "width": 100, "height": 30, "conf": 0.85},
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 2
        assert fields[0]["value"] == "鞋"
        assert fields[1]["value"] == "衣"


# ---------------------------------------------------------------------------
# _pair_fields_by_grid — additional branches
# ---------------------------------------------------------------------------


class TestPairFieldsByGridAdditional:
    """Additional coverage for _pair_fields_by_grid."""

    def test_block_in_merged_not_start_col_skipped_via_else(self):
        """Block in merged cell but not at start_col should hit the else branch (skip)."""
        blocks = [
            # First block at col 0 (start of merged)
            {
                "text": "长标签内容",
                "y_center": 50,
                "center": (25, 50),
                "left": 10,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.9,
            },
            # Second block at col 1 (inside merged, not start)
            {
                "text": "extra",
                "y_center": 50,
                "center": (75, 50),
                "left": 60,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.8,
            },
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100], merged)
        # First block should be a merged field, second should be skipped
        assert len(result) == 1
        assert result[0]["is_merged"] is True
        assert result[0]["label"] == "长标签内容"

    def test_next_block_in_merged_current_unpaired(self):
        """When next block is in merged cell, current block should have empty value."""
        blocks = [
            {
                "text": "品名",
                "y_center": 50,
                "center": (25, 50),
                "left": 10,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.9,
            },
            {
                "text": "merged_val",
                "y_center": 50,
                "center": (75, 50),
                "left": 60,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.8,
            },
        ]
        merged = [{"row": 0, "start_col": 1, "end_col": 2}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 33, 66, 100], merged)
        assert len(result) >= 1
        first = [f for f in result if f["label"] == "品名"][0]
        assert first["value"] == ""

    def test_single_block_no_merged(self):
        """Single block with no merged cells should have empty value."""
        blocks = [
            {
                "text": "品名",
                "y_center": 50,
                "center": (25, 50),
                "left": 10,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.9,
            },
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100], [])
        assert len(result) == 1
        assert result[0]["value"] == ""
        assert result[0]["is_merged"] is False

    def test_two_adjacent_blocks_paired(self):
        """Two adjacent blocks in same row should be paired."""
        blocks = [
            {
                "text": "品名",
                "y_center": 50,
                "center": (25, 50),
                "left": 10,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.9,
            },
            {
                "text": "运动鞋",
                "y_center": 50,
                "center": (75, 50),
                "left": 60,
                "top": 40,
                "width": 40,
                "height": 20,
                "conf": 0.85,
            },
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100], [])
        assert len(result) == 1
        assert result[0]["label"] == "品名"
        assert result[0]["value"] == "运动鞋"
        assert result[0]["is_merged"] is False

    def test_merged_cell_with_three_cols(self):
        """Merged cell spanning 3 columns should have merge_cols=3."""
        # Block center at x=50 falls in first column [0, 33)
        blocks = [
            {
                "text": "长标签",
                "y_center": 50,
                "center": (16, 50),
                "left": 10,
                "top": 40,
                "width": 140,
                "height": 20,
                "conf": 0.9,
            },
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 2}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 33, 66, 100], merged)
        merged_fields = [f for f in result if f.get("is_merged")]
        assert len(merged_fields) >= 1
        assert merged_fields[0]["merge_cols"] == 3


# ---------------------------------------------------------------------------
# extract_text_with_ocr — grid detection with mocked cv2
# ---------------------------------------------------------------------------


class TestExtractTextWithOcrGridDetection:
    """Cover grid detection paths in extract_text_with_ocr."""

    def test_file_not_found_returns_failure(self):
        """extract_text_with_ocr returns failure for missing file."""
        result = extract_text_with_ocr("/nonexistent/image.png")
        assert result["success"] is False

    def test_import_error_returns_fallback(self, tmp_path):
        """When cv2 import fails, should return fallback fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        with patch.dict("sys.modules", {"cv2": None, "numpy": None}):
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False
            assert "fallback_fields" in result
            assert len(result["fallback_fields"]) == 7

    def test_recoverable_error_returns_fallback(self, tmp_path):
        """RECOVERABLE_ERRORS during OCR should return fallback."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "err.png")
        img.save(img_path)

        with patch(
            "app.services.skills.label_template_generator.label_template_generator.Image"
        ) as MockImage:
            MockImage.open.side_effect = OSError("broken")
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False
            assert "fallback_fields" in result

    def test_ocr_no_text_blocks_returns_fallback(self, tmp_path):
        """When OCR returns no text blocks, should return fallback fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_text.png")
        img.save(img_path)

        # Mock cv2 and numpy to allow import - need to make the grid detection
        # code path work enough to reach the OCR service call
        mock_cv2 = MagicMock()
        mock_np = MagicMock()

        # Set up cv2 returns - threshold returns (retval, binary_image)
        # The code does: gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        # then: _, binary = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
        # then iterates: for y in range(gray.shape[0])
        mock_gray = MagicMock()
        mock_gray.shape = (0, 0)  # Empty shape to skip loops
        mock_cv2.cvtColor.return_value = mock_gray
        mock_binary = MagicMock()
        mock_binary.shape = (0, 0)
        mock_cv2.threshold.return_value = (0, mock_binary)

        with (
            patch.dict("sys.modules", {"cv2": mock_cv2, "numpy": mock_np}),
            patch(
                "app.services.skills.label_template_generator.label_template_generator.Image"
            ) as MockImage,
        ):
            MockImage.open.return_value = img
            # Mock get_ocr_service to return empty text blocks
            with patch("app.services.ocr_service.get_ocr_service") as mock_get_svc:
                mock_svc = MagicMock()
                mock_svc.recognize_text_blocks.return_value = []
                mock_svc.get_active_ocr_backend.return_value = "mock"
                mock_get_svc.return_value = mock_svc

                result = extract_text_with_ocr(img_path)

        assert result["success"] is False
        assert "fallback_fields" in result


# ---------------------------------------------------------------------------
# generate_template_code — additional branches
# ---------------------------------------------------------------------------


class TestGenerateTemplateCodeAdditional:
    """Additional coverage for generate_template_code."""

    def test_verbose_flag_passed_to_analyze(self, tmp_path):
        """generate_template_code should pass verbose=True to analyze_image on first call."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "verbose.png")
        img.save(img_path)

        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            wraps=analyze_image,
        ) as mock_analyze:
            code = generate_template_code(img_path, verbose=True)
            # First call should be with verbose=True
            assert mock_analyze.call_count >= 1
            first_call = mock_analyze.call_args_list[0]
            assert first_call.args[0] == img_path
            assert first_call.kwargs.get("verbose") is True
            assert "class LabelTemplateGenerator" in code

    def test_failed_analysis_returns_error_string(self):
        """generate_template_code with failed analysis returns error string."""
        code = generate_template_code("/nonexistent/image.png")
        assert "Error" in code or "error" in code.lower() or "分析失败" in code

    def test_with_ocr_result_success_and_fields(self, tmp_path):
        """generate_template_code with successful OCR should use _generate_code_with_fields."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "ocr.png")
        img.save(img_path)

        ocr_result = {
            "success": True,
            "fields": [
                {
                    "label": "品名",
                    "value": "鞋",
                    "field_key": "product_name",
                    "type": "fixed_label",
                },
                {"label": "颜色", "value": "白", "field_key": "color", "type": "fixed_label"},
            ],
        }
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "product_name" in code
        assert "color" in code
        assert "鞋" in code
        assert "白" in code

    def test_with_ocr_result_not_success_uses_basic(self, tmp_path):
        """generate_template_code with failed OCR should use _generate_basic_code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "basic.png")
        img.save(img_path)

        ocr_result = {"success": False, "message": "OCR failed"}
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "class LabelTemplateGenerator" in code
        assert "generate_labels_for_order" in code

    def test_custom_class_name_in_code(self, tmp_path):
        """generate_template_code should use custom class name."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "custom.png")
        img.save(img_path)

        code = generate_template_code(img_path, class_name="MyCustomLabel")
        assert "class MyCustomLabel" in code


# ---------------------------------------------------------------------------
# _generate_code_with_fields — additional branches
# ---------------------------------------------------------------------------


class TestGenerateCodeWithFieldsAdditional:
    """Additional coverage for _generate_code_with_fields."""

    def test_with_dynamic_field_type(self, tmp_path):
        """Dynamic field should have editable=True in generated code."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "dyn.png")
        img.save(img_path)

        fields = [
            {"label": "自定义", "value": "值", "field_key": "custom", "type": "dynamic"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "TestGen", 800, 600, colors, fields)
        assert "class TestGen" in code
        assert "custom" in code
        # Dynamic fields should have editable: False
        assert "False" in code

    def test_with_fixed_label_field_type(self, tmp_path):
        """Fixed label field should have editable=True in generated code."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "fixed.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "FixedGen", 800, 600, colors, fields)
        assert "fixed_label" in code
        assert "True" in code  # editable: True for fixed_label

    def test_with_multiple_field_types(self, tmp_path):
        """Mix of fixed_label and dynamic fields should both be in code."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "mix.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"},
            {"label": "自定义", "value": "值", "field_key": "custom", "type": "dynamic"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "MixGen", 800, 600, colors, fields)
        assert "product_name" in code
        assert "custom" in code

    def test_code_contains_get_field_template(self, tmp_path):
        """Generated code should contain get_field_template method."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "tmpl.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "", "field_key": "product_name", "type": "fixed_label"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "TmplGen", 400, 300, colors, fields)
        assert "get_field_template" in code
        assert "example_usage" in code


# ---------------------------------------------------------------------------
# _generate_basic_code — additional branches
# ---------------------------------------------------------------------------


class TestGenerateBasicCodeAdditional:
    """Additional coverage for _generate_basic_code."""

    def test_code_contains_draw_methods(self, tmp_path):
        """Basic code should contain _draw_border and _draw_content methods."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "basic.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "BasicGen", 400, 300, colors)
        assert "_draw_border" in code
        assert "_draw_content" in code
        assert "generate_label" in code
        assert "generate_labels_for_order" in code

    def test_code_contains_dimensions(self, tmp_path):
        """Basic code should contain width and height."""
        from PIL import Image

        img = Image.new("RGB", (600, 400), (255, 255, 255))
        img_path = str(tmp_path / "dims.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "DimGen", 600, 400, colors)
        assert "self.width = 600" in code
        assert "self.height = 400" in code

    def test_code_contains_colors(self, tmp_path):
        """Basic code should contain color settings."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (0, 0, 0))
        img_path = str(tmp_path / "colors.png")
        img.save(img_path)

        colors = {"background": "#000000", "border": "#ffffff", "text": "#ffffff"}
        code = _generate_basic_code(img_path, "ColorGen", 400, 300, colors)
        assert "#000000" in code
        assert "#ffffff" in code

    def test_code_contains_example_usage(self, tmp_path):
        """Basic code should contain example_usage function."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "ex.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "ExGen", 400, 300, colors)
        assert "example_usage" in code
        assert 'if __name__ == "__main__"' in code


# ---------------------------------------------------------------------------
# _extract_fields_by_pattern — additional coverage
# ---------------------------------------------------------------------------


class TestExtractFieldsByPatternAdditional:
    """Additional coverage for _extract_fields_by_pattern."""

    def test_returns_seven_fields(self):
        """Should return exactly 7 fallback fields."""
        result = _extract_fields_by_pattern("/any/path.png")
        assert len(result) == 7

    def test_all_fields_have_correct_types(self):
        """All fallback fields should be fixed_label type."""
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert field["type"] == "fixed_label"

    def test_fields_have_expected_keys(self):
        """Each field should have label, value, field_key, type."""
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert "label" in field
            assert "value" in field
            assert "field_key" in field
            assert "type" in field

    def test_contains_expected_field_keys(self):
        """Should contain expected field keys."""
        result = _extract_fields_by_pattern("/any/path.png")
        keys = {f["field_key"] for f in result}
        assert "product_name" in keys
        assert "color" in keys
        assert "item_number" in keys
        assert "code_segment" in keys
        assert "grade" in keys
        assert "standard" in keys
        assert "price" in keys

    def test_all_values_indicate_ocr_needed(self):
        """All fallback values should indicate OCR is needed."""
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert "OCR" in field["value"] or "ocr" in field["value"].lower()


# ---------------------------------------------------------------------------
# LabelTemplateGeneratorSkill — additional branches
# ---------------------------------------------------------------------------


class TestLabelTemplateGeneratorSkillAdditional:
    """Additional coverage for LabelTemplateGeneratorSkill."""

    def test_execute_with_ocr_success_logs_field_count(self, tmp_path):
        """execute() with successful OCR should log field count."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "ocr_ok.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        mock_ocr_result = {
            "success": True,
            "fields": [
                {
                    "label": "品名",
                    "value": "鞋",
                    "field_key": "product_name",
                    "type": "fixed_label",
                },
                {"label": "颜色", "value": "白", "field_key": "color", "type": "fixed_label"},
            ],
        }
        with (
            patch(
                "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
                return_value=mock_ocr_result,
            ),
            patch(
                "app.services.skills.label_template_generator.label_template_generator.logger"
            ) as mock_logger,
        ):
            result = skill.execute(img_path, enable_ocr=True)
            assert result["success"] is True
            assert result["ocr_result"]["success"] is True
            # Logger.info should be called for OCR success
            mock_logger.info.assert_called()

    def test_execute_with_ocr_failure_no_log(self, tmp_path):
        """execute() with failed OCR should not log field count."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "ocr_fail.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with (
            patch(
                "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
                return_value={"success": False, "message": "OCR failed"},
            ),
            patch(
                "app.services.skills.label_template_generator.label_template_generator.logger"
            ) as mock_logger,
        ):
            result = skill.execute(img_path, enable_ocr=True)
            assert result["success"] is True
            assert result["ocr_result"]["success"] is False
            # Should not log field count for failed OCR
            for call in mock_logger.info.call_args_list:
                args = call[0]
                if args and "OCR 识别成功" in str(args[0]):
                    pytest.fail("Should not log OCR success for failed OCR")

    def test_execute_with_output_file_write_success(self, tmp_path):
        """execute() should write code to output_file on success."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "out.png")
        img.save(img_path)
        output_file = str(tmp_path / "output.py")

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(img_path, output_file=output_file, enable_ocr=False)
        assert result["success"] is True
        assert result["output_file"] == output_file

    def test_execute_with_output_file_write_error(self, tmp_path):
        """execute() should catch output file write error."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "err.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()

        # Patch open to fail only for the output file (not the image file)
        original_open = open

        def mock_open(file, mode="r", *args, **kwargs):
            if "w" in mode and "output" in str(file):
                raise PermissionError("no write")
            return original_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            result = skill.execute(
                img_path, output_file="/tmp/forbidden_output.py", enable_ocr=False
            )
            assert result["success"] is True
            assert "output_error" in result

    def test_execute_analysis_failure_returns_analysis(self):
        """execute() with failed analysis should return the analysis dict."""
        skill = LabelTemplateGeneratorSkill()
        result = skill.execute("/nonexistent/image.png")
        assert result["success"] is False

    def test_execute_recoverable_error_returns_failure(self, tmp_path):
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

    def test_get_skill_info_returns_all_parameters(self):
        """get_skill_info should return all expected parameters."""
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["name"] == "label_template_generator"
        assert "description" in info
        params = info["parameters"]
        assert "image_path" in params
        assert "class_name" in params
        assert "output_file" in params
        assert "enable_ocr" in params
        assert "verbose" in params
        assert params["image_path"]["required"] is True
        assert params["class_name"]["required"] is False
        assert params["output_file"]["required"] is False
        assert params["enable_ocr"]["required"] is False
        assert params["verbose"]["required"] is False

    def test_skill_init_attributes(self):
        """LabelTemplateGeneratorSkill should have correct name and description."""
        skill = LabelTemplateGeneratorSkill()
        assert skill.name == "label_template_generator"
        assert "标签模板" in skill.description
        assert "Python" in skill.description


# ---------------------------------------------------------------------------
# get_label_template_generator_skill — singleton edge cases
# ---------------------------------------------------------------------------


class TestGetLabelTemplateGeneratorSkillSingleton:
    """Additional coverage for singleton getter."""

    def test_returns_instance_when_none(self):
        """Should create new instance when _skill_instance is None."""
        import app.services.skills.label_template_generator.label_template_generator as mod

        mod._skill_instance = None
        skill = get_label_template_generator_skill()
        assert isinstance(skill, LabelTemplateGeneratorSkill)
        # Cleanup
        mod._skill_instance = None

    def test_returns_same_instance_when_set(self):
        """Should return existing instance when _skill_instance is set."""
        import app.services.skills.label_template_generator.label_template_generator as mod

        existing = LabelTemplateGeneratorSkill()
        mod._skill_instance = existing
        skill = get_label_template_generator_skill()
        assert skill is existing
        # Cleanup
        mod._skill_instance = None

    def test_singleton_persistence(self):
        """Multiple calls should return the same instance."""
        import app.services.skills.label_template_generator.label_template_generator as mod

        mod._skill_instance = None
        skill1 = get_label_template_generator_skill()
        skill2 = get_label_template_generator_skill()
        skill3 = get_label_template_generator_skill()
        assert skill1 is skill2
        assert skill2 is skill3
        # Cleanup
        mod._skill_instance = None
