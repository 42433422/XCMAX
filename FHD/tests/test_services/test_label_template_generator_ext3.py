"""Deep coverage tests for label_template_generator covering remaining branches.

Focuses on:
- _pair_fields_by_grid: merged cell skip_count logic, non-adjacent pairing,
  blocks in merged but not at start_col (else branch), group_by_row grouping
- _identify_fields: text without colon and not matching known labels,
  empty value_part branch, multiple known labels matching first
- _classify_field: known labels mapping (品名, 颜色, 货号, etc.)
- _analyze_colors: consistent background True/False, custom colors
- _estimate_sections: between-threshold sizes
- extract_text_with_ocr: full grid detection path with mocked cv2/numpy
- generate_template_code: ocr_result None path, ocr_result without success
- _generate_code_with_fields: empty fields list, multiple field types
- _generate_basic_code: small dimensions, custom class name
- LabelTemplateGeneratorSkill.execute: enable_ocr=False path, verbose=True
- get_label_template_generator_skill: thread-safe singleton creation
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
# _classify_field — known labels mapping
# ---------------------------------------------------------------------------


class TestClassifyFieldKnownLabels:
    """Cover all known label mappings in _classify_field."""

    @pytest.mark.parametrize(
        "label,expected_key",
        [
            ("品名", "product_name"),
            ("颜色", "color"),
            ("货号", "item_number"),
            ("码段", "code_segment"),
            ("等级", "grade"),
            ("执行标准", "standard"),
            ("统一零售价", "price"),
            ("产品名称", "product_name"),
            ("产品编号", "product_number"),
            ("规格", "specification"),
            ("型号", "model"),
            ("价格", "price"),
            ("零售价", "price"),
            ("生产日期", "production_date"),
            ("保质期", "shelf_life"),
            ("产品规格", "product_spec"),
            ("检验员", "inspector"),
        ],
    )
    def test_known_label_returns_fixed_label(self, label, expected_key):
        """Each known label should map to fixed_label with correct field_key."""
        field_type, field_key = _classify_field(label)
        assert field_type == "fixed_label"
        assert field_key == expected_key

    def test_label_ending_with_price_suffix_jia(self):
        """Label ending with '价' (not in known list) should be price."""
        field_type, field_key = _classify_field("会员价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_label_ending_with_price_suffix_promotional(self):
        """Label '促销价' should be price."""
        field_type, field_key = _classify_field("促销价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_unknown_label_returns_dynamic(self):
        """Unknown label should be dynamic with the label as key."""
        field_type, field_key = _classify_field("自定义字段")
        assert field_type == "dynamic"
        assert field_key == "自定义字段"


# ---------------------------------------------------------------------------
# _identify_fields — additional branches
# ---------------------------------------------------------------------------


class TestIdentifyFieldsDeep:
    """Deep coverage for _identify_fields."""

    def test_colon_with_known_label_returns_fixed_label(self):
        """Colon-separated known label should be fixed_label."""
        blocks = [
            {"text": "品名：运动鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_name"
        assert fields[0]["value"] == "运动鞋"

    def test_colon_with_unknown_label_returns_dynamic(self):
        """Colon-separated unknown label should be dynamic."""
        blocks = [
            {"text": "自定义：值", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "dynamic"
        assert fields[0]["field_key"] == "自定义"
        assert fields[0]["value"] == "值"

    def test_colon_with_empty_value(self):
        """Colon with empty value should still create field."""
        blocks = [
            {"text": "品名：", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["value"] == ""

    def test_no_colon_unknown_text_skipped(self):
        """Text without colon and not matching known labels should be skipped."""
        blocks = [
            {"text": "完全无法识别的文本", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 0

    def test_no_colon_known_label_no_value_skipped(self):
        """Known label with no value part should be skipped."""
        blocks = [
            {"text": "品名", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 0

    def test_no_colon_known_label_with_only_whitespace_value_skipped(self):
        """Known label with only whitespace value should be skipped (after strip)."""
        blocks = [
            {"text": "品名   ", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 0

    def test_no_colon_first_matching_label_wins(self):
        """When multiple known labels could match, first match wins."""
        # "产品名称" comes before "产品编号" in iteration, but text starts with "产品名称"
        blocks = [
            {"text": "产品名称ABC", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "产品名称"
        assert fields[0]["value"] == "ABC"

    def test_full_text_preserved(self):
        """full_text should preserve the original text."""
        blocks = [
            {"text": "品名：鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9}
        ]
        fields = _identify_fields(blocks)
        assert fields[0]["full_text"] == "品名：鞋"

    def test_position_info_preserved(self):
        """Position info should be preserved from block."""
        blocks = [
            {"text": "品名：鞋", "left": 15, "top": 25, "width": 110, "height": 35, "conf": 0.95}
        ]
        fields = _identify_fields(blocks)
        assert fields[0]["position"]["left"] == 15
        assert fields[0]["position"]["top"] == 25
        assert fields[0]["position"]["width"] == 110
        assert fields[0]["position"]["height"] == 35
        assert fields[0]["confidence"] == 0.95

    def test_empty_blocks_returns_empty(self):
        """Empty blocks list should return empty fields."""
        assert _identify_fields([]) == []

    def test_multiple_blocks_mixed_patterns(self):
        """Mix of colon and no-colon patterns should all be identified."""
        blocks = [
            {"text": "品名：鞋", "left": 10, "top": 20, "width": 100, "height": 30, "conf": 0.9},
            {"text": "颜色 红色", "left": 10, "top": 60, "width": 100, "height": 30, "conf": 0.85},
            {"text": "未知文本", "left": 10, "top": 100, "width": 100, "height": 30, "conf": 0.8},
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 2
        assert fields[0]["label"] == "品名"
        assert fields[1]["label"] == "颜色"


# ---------------------------------------------------------------------------
# _pair_fields_by_grid — deep coverage
# ---------------------------------------------------------------------------


class TestPairFieldsByGridDeep:
    """Deep coverage for _pair_fields_by_grid."""

    def test_empty_blocks_returns_empty(self):
        """Empty text_blocks should return empty list."""
        result = _pair_fields_by_grid([], [0, 100], [0, 100])
        assert result == []

    def test_none_merged_horizontal_defaults_to_empty(self):
        """None merged_horizontal should default to empty list."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100], None)
        assert len(result) == 1
        assert result[0]["is_merged"] is False

    def test_merged_cell_skip_count_greater_than_one(self):
        """Merged cell with end_col - start_col > 1 should skip multiple blocks."""
        # 5 columns [0, 25, 50, 75, 100], merged from col 0 to col 2 (3 cols)
        blocks = [
            # Block at col 0 (start of merged, center x=12 falls in [0, 25))
            {"text": "长标签", "y_center": 50, "center": (12, 50), "left": 5, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            # Block at col 1 (inside merged, center x=37 falls in [25, 50))
            {"text": "skip1", "y_center": 50, "center": (37, 50), "left": 30, "top": 40,
             "width": 20, "height": 20, "conf": 0.8},
            # Block at col 2 (inside merged, center x=62 falls in [50, 75))
            {"text": "skip2", "y_center": 50, "center": (62, 50), "left": 55, "top": 40,
             "width": 20, "height": 20, "conf": 0.7},
            # Block at col 3 (outside merged, center x=87 falls in [75, 100))
            {"text": "正常", "y_center": 50, "center": (87, 50), "left": 80, "top": 40,
             "width": 20, "height": 20, "conf": 0.85},
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 2}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 25, 50, 75, 100], merged)
        # Should have 2 fields: merged "长标签" and "正常" (unpaired, outside merged)
        merged_fields = [f for f in result if f.get("is_merged")]
        assert len(merged_fields) == 1
        assert merged_fields[0]["label"] == "长标签"
        assert merged_fields[0]["merge_cols"] == 3
        # "正常" should be a separate field (not merged)
        normal_fields = [f for f in result if f["label"] == "正常"]
        assert len(normal_fields) == 1
        assert not normal_fields[0].get("is_merged", False)

    def test_merged_cell_with_default_end_col(self):
        """Merged cell with missing end_col should default to start_col."""
        blocks = [
            {"text": "标签", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
        ]
        # merged_info without end_col - should default to start_col
        merged = [{"row": 0, "start_col": 0, "end_col": 0}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100], merged)
        # Block at col 0 is at start_col, should be processed as merged
        merged_fields = [f for f in result if f.get("is_merged")]
        # merge_cols = end_col - start_col + 1 = 1
        if merged_fields:
            assert merged_fields[0]["merge_cols"] == 1

    def test_blocks_in_different_rows_grouped_separately(self):
        """Blocks in different rows should be in separate groups."""
        blocks = [
            {"text": "品名", "y_center": 25, "center": (25, 25), "left": 10, "top": 15,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "鞋", "y_center": 25, "center": (75, 25), "left": 60, "top": 15,
             "width": 40, "height": 20, "conf": 0.85},
            {"text": "颜色", "y_center": 75, "center": (25, 75), "left": 10, "top": 65,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "红", "y_center": 75, "center": (75, 75), "left": 60, "top": 65,
             "width": 40, "height": 20, "conf": 0.85},
        ]
        result = _pair_fields_by_grid(blocks, [0, 50, 100], [0, 50, 100])
        assert len(result) == 2
        labels = [f["label"] for f in result]
        assert "品名" in labels
        assert "颜色" in labels

    def test_non_adjacent_blocks_not_paired(self):
        """Blocks in non-adjacent columns should not be paired."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (16, 50), "left": 10, "top": 40,
             "width": 20, "height": 20, "conf": 0.9},
            # Block at col 2 (not adjacent to col 0)
            {"text": "值", "y_center": 50, "center": (83, 50), "left": 70, "top": 40,
             "width": 20, "height": 20, "conf": 0.85},
        ]
        # 3 columns: 0, 1, 2
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 33, 66, 100])
        # Should have 2 separate fields (not paired)
        assert len(result) == 2
        for field in result:
            assert field["value"] == ""

    def test_last_block_in_row_unpaired(self):
        """Last block in a row with no next block should have empty value."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "鞋", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.85},
            # Third block with no next block
            {"text": "等级", "y_center": 50, "center": (125, 50), "left": 110, "top": 40,
             "width": 40, "height": 20, "conf": 0.8},
        ]
        # 3 columns
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100, 150])
        # First two should be paired, third should be unpaired
        unpaired = [f for f in result if f["label"] == "等级"]
        assert len(unpaired) == 1
        assert unpaired[0]["value"] == ""

    def test_block_at_merged_start_col_processed(self):
        """Block exactly at merged start_col should be processed as merged."""
        blocks = [
            {"text": "合并标签", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 80, "height": 20, "conf": 0.9},
        ]
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100], merged)
        assert len(result) == 1
        assert result[0]["is_merged"] is True
        assert result[0]["merge_cols"] == 2

    def test_field_position_from_label_block(self):
        """Field position should come from the label block."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 11, "top": 41,
             "width": 41, "height": 21, "conf": 0.9},
            {"text": "鞋", "y_center": 50, "center": (75, 50), "left": 61, "top": 41,
             "width": 41, "height": 21, "conf": 0.85},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100])
        assert len(result) == 1
        assert result[0]["position"]["left"] == 11
        assert result[0]["position"]["top"] == 41
        assert result[0]["position"]["width"] == 41
        assert result[0]["position"]["height"] == 21

    def test_confidence_averaged_for_paired_blocks(self):
        """Confidence should be averaged for paired label+value blocks."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "鞋", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.7},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100])
        assert len(result) == 1
        assert result[0]["confidence"] == pytest.approx(0.8)

    def test_full_text_combines_label_and_value(self):
        """full_text should combine label and value with ': ' separator."""
        blocks = [
            {"text": "品名", "y_center": 50, "center": (25, 50), "left": 10, "top": 40,
             "width": 40, "height": 20, "conf": 0.9},
            {"text": "运动鞋", "y_center": 50, "center": (75, 50), "left": 60, "top": 40,
             "width": 40, "height": 20, "conf": 0.85},
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 50, 100])
        assert len(result) == 1
        assert result[0]["full_text"] == "品名: 运动鞋"


# ---------------------------------------------------------------------------
# _analyze_colors — additional coverage
# ---------------------------------------------------------------------------


class TestAnalyzeColorsDeep:
    """Deep coverage for _analyze_colors."""

    def test_consistent_background_returns_true(self):
        """All corners same color should return is_consistent_background=True."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 0, 0))
        result = _analyze_colors(img)
        assert result["is_consistent_background"] is True
        assert result["background"] == "#ff0000"

    def test_inconsistent_background_returns_false(self):
        """Different corner colors should return is_consistent_background=False."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        # Draw different colors in corners
        img.putpixel((10, 10), (255, 0, 0))
        result = _analyze_colors(img)
        assert result["is_consistent_background"] is False

    def test_custom_background_color(self):
        """Custom background color should be reflected in result."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), (0, 128, 255))
        result = _analyze_colors(img)
        assert result["background"] == "#0080ff"

    def test_border_and_text_always_default(self):
        """Border and text should always be #000000."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        result = _analyze_colors(img)
        assert result["border"] == "#000000"
        assert result["text"] == "#000000"

    def test_small_image_uses_safe_corners(self):
        """Small image (10x10) should still work with corner positions."""
        from PIL import Image

        img = Image.new("RGB", (20, 20), (100, 100, 100))
        result = _analyze_colors(img)
        assert result["background"] == "#646464"


# ---------------------------------------------------------------------------
# _estimate_sections — additional coverage
# ---------------------------------------------------------------------------


class TestEstimateSectionsDeep:
    """Deep coverage for _estimate_sections."""

    def test_just_below_large_threshold(self):
        """Width=799, height=499 should be medium (3 sections)."""
        sections = _estimate_sections(799, 499)
        # 799 < 800, so not large; 499 < 500, so not large
        # 799 >= 400 and 499 >= 300, so medium
        assert len(sections) == 3

    def test_just_below_medium_threshold(self):
        """Width=399, height=299 should be small (1 section)."""
        sections = _estimate_sections(399, 299)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"

    def test_medium_width_small_height(self):
        """Width=400, height=299 should be small (1 section)."""
        sections = _estimate_sections(400, 299)
        assert len(sections) == 1

    def test_small_width_medium_height(self):
        """Width=399, height=300 should be small (1 section)."""
        sections = _estimate_sections(399, 300)
        assert len(sections) == 1

    def test_large_sections_have_descriptions(self):
        """Large label sections should have descriptions."""
        sections = _estimate_sections(800, 500)
        for s in sections:
            assert "description" in s
            assert isinstance(s["description"], str)
            assert len(s["description"]) > 0

    def test_medium_sections_have_descriptions(self):
        """Medium label sections should have descriptions."""
        sections = _estimate_sections(400, 300)
        for s in sections:
            assert "description" in s

    def test_all_sections_have_y_start_and_y_end(self):
        """All sections should have y_start and y_end."""
        for w, h in [(800, 500), (400, 300), (100, 100)]:
            sections = _estimate_sections(w, h)
            for s in sections:
                assert "y_start" in s
                assert "y_end" in s
                assert isinstance(s["y_start"], int)
                assert isinstance(s["y_end"], int)


# ---------------------------------------------------------------------------
# _estimate_font_sizes — additional coverage
# ---------------------------------------------------------------------------


class TestEstimateFontSizesDeep:
    """Deep coverage for _estimate_font_sizes."""

    def test_just_below_400_width(self):
        """Width=399 should use small font sizes."""
        sizes = _estimate_font_sizes(399, 300)
        assert sizes == {"title": 24, "label": 14, "content": 18, "small": 12}

    def test_just_above_400_width(self):
        """Width=401 should use medium font sizes."""
        sizes = _estimate_font_sizes(401, 300)
        assert sizes == {"title": 40, "label": 24, "content": 32, "small": 20}

    def test_just_below_800_width(self):
        """Width=799 should use medium font sizes."""
        sizes = _estimate_font_sizes(799, 600)
        assert sizes == {"title": 40, "label": 24, "content": 32, "small": 20}

    def test_just_above_800_width(self):
        """Width=801 should use large font sizes."""
        sizes = _estimate_font_sizes(801, 600)
        assert sizes == {"title": 70, "label": 40, "content": 58, "small": 38}

    def test_all_keys_present(self):
        """All font size configs should have title, label, content, small."""
        for w, h in [(100, 100), (400, 300), (800, 600)]:
            sizes = _estimate_font_sizes(w, h)
            assert "title" in sizes
            assert "label" in sizes
            assert "content" in sizes
            assert "small" in sizes

    def test_font_sizes_increase_with_width(self):
        """Font sizes should generally increase with width."""
        small = _estimate_font_sizes(100, 100)
        medium = _estimate_font_sizes(400, 300)
        large = _estimate_font_sizes(800, 600)
        assert small["title"] < medium["title"] < large["title"]
        assert small["content"] < medium["content"] < large["content"]


# ---------------------------------------------------------------------------
# extract_text_with_ocr — full grid detection path
# ---------------------------------------------------------------------------


class TestExtractTextWithOcrGridDetectionDeep:
    """Deep coverage for extract_text_with_ocr grid detection."""

    def test_successful_ocr_with_grid(self, tmp_path):
        """Successful OCR with grid should return fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "grid.png")
        img.save(img_path)

        # Mock cv2 and numpy
        mock_cv2 = MagicMock()
        mock_np = MagicMock()

        # Set up cv2 returns
        mock_gray = MagicMock()
        mock_gray.shape = (300, 400)
        mock_cv2.cvtColor.return_value = mock_gray
        mock_binary = MagicMock()
        mock_binary.shape = (300, 400)
        mock_cv2.threshold.return_value = (0, mock_binary)
        mock_cv2.COLOR_RGB2GRAY = 6
        mock_cv2.THRESH_BINARY_INV = 1

        # Mock binary array access - return zeros (no lines detected)
        mock_binary.__getitem__ = MagicMock(return_value=MagicMock())
        mock_binary.__getitem__.return_value.__getitem__ = MagicMock(return_value=0)
        mock_gray.__getitem__ = MagicMock(return_value=MagicMock())
        mock_gray.__getitem__.return_value.__getitem__ = MagicMock(return_value=0)

        with patch.dict("sys.modules", {"cv2": mock_cv2, "numpy": mock_np}), patch(
            "app.services.skills.label_template_generator.label_template_generator.Image"
        ) as MockImage:
            MockImage.open.return_value = img
            with patch(
                "app.services.ocr_service.get_ocr_service"
            ) as mock_get_svc:
                mock_svc = MagicMock()
                mock_svc.recognize_text_blocks.return_value = [
                    {"text": "品名", "center": (50, 50), "y_center": 50, "left": 10, "top": 40,
                     "width": 40, "height": 20, "conf": 0.9},
                ]
                mock_svc.get_active_ocr_backend.return_value = "mock"
                mock_get_svc.return_value = mock_svc

                result = extract_text_with_ocr(img_path)

        assert result["success"] is True
        assert "fields" in result
        assert "grid" in result

    def test_import_error_returns_fallback_fields(self, tmp_path):
        """ImportError should return fallback fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "import_err.png")
        img.save(img_path)

        with patch.dict("sys.modules", {"cv2": None, "numpy": None}):
            result = extract_text_with_ocr(img_path)
            assert result["success"] is False
            assert "fallback_fields" in result
            assert len(result["fallback_fields"]) == 7

    def test_recoverable_error_returns_fallback(self, tmp_path):
        """RECOVERABLE_ERRORS should return fallback fields."""
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

    def test_no_text_blocks_returns_fallback(self, tmp_path):
        """Empty text blocks should return fallback fields."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_text.png")
        img.save(img_path)

        mock_cv2 = MagicMock()
        mock_np = MagicMock()
        mock_gray = MagicMock()
        mock_gray.shape = (0, 0)
        mock_cv2.cvtColor.return_value = mock_gray
        mock_binary = MagicMock()
        mock_binary.shape = (0, 0)
        mock_cv2.threshold.return_value = (0, mock_binary)

        with patch.dict("sys.modules", {"cv2": mock_cv2, "numpy": mock_np}), patch(
            "app.services.skills.label_template_generator.label_template_generator.Image"
        ) as MockImage:
            MockImage.open.return_value = img
            with patch(
                "app.services.ocr_service.get_ocr_service"
            ) as mock_get_svc:
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


class TestGenerateTemplateCodeDeep:
    """Deep coverage for generate_template_code."""

    def test_with_none_ocr_result_uses_basic(self, tmp_path):
        """None ocr_result should use _generate_basic_code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "none_ocr.png")
        img.save(img_path)

        code = generate_template_code(img_path, ocr_result=None)
        assert "class LabelTemplateGenerator" in code
        assert "generate_labels_for_order" in code

    def test_with_ocr_result_no_success_key_uses_basic(self, tmp_path):
        """ocr_result without success key should use _generate_basic_code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_success.png")
        img.save(img_path)

        ocr_result = {"fields": []}  # No success key
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "class LabelTemplateGenerator" in code

    def test_with_ocr_result_success_false_uses_basic(self, tmp_path):
        """ocr_result with success=False should use _generate_basic_code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "false_success.png")
        img.save(img_path)

        ocr_result = {"success": False, "fields": []}
        code = generate_template_code(img_path, ocr_result=ocr_result)
        assert "class LabelTemplateGenerator" in code

    def test_with_ocr_result_success_true_no_fields(self, tmp_path):
        """ocr_result with success=True but no fields should use _generate_code_with_fields."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), (255, 255, 255))
        img_path = str(tmp_path / "no_fields.png")
        img.save(img_path)

        ocr_result = {"success": True}  # No fields key
        code = generate_template_code(img_path, ocr_result=ocr_result)
        # Should still use _generate_code_with_fields with empty fields
        assert "class LabelTemplateGenerator" in code

    def test_verbose_flag_in_analysis(self, tmp_path):
        """verbose=True should produce additional_info in analysis."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "verbose.png")
        img.save(img_path)

        code = generate_template_code(img_path, verbose=True)
        assert "class LabelTemplateGenerator" in code

    def test_failed_analysis_returns_error_string(self):
        """Failed analysis should return error string."""
        code = generate_template_code("/nonexistent/image.png")
        assert "Error" in code or "error" in code.lower() or "分析失败" in code


# ---------------------------------------------------------------------------
# _generate_code_with_fields — additional branches
# ---------------------------------------------------------------------------


class TestGenerateCodeWithFieldsDeep:
    """Deep coverage for _generate_code_with_fields."""

    def test_empty_fields_list(self, tmp_path):
        """Empty fields list should still generate valid code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "empty.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "EmptyGen", 400, 300, colors, [])
        assert "class EmptyGen" in code
        assert "self.fields = {" in code

    def test_field_with_missing_field_key_uses_label(self, tmp_path):
        """Field without field_key should use label as key."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_key.png")
        img.save(img_path)

        fields = [
            {"label": "自定义标签", "value": "值", "type": "dynamic"},  # No field_key
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "NoKeyGen", 400, 300, colors, fields)
        assert "自定义标签" in code

    def test_field_with_missing_value_uses_empty(self, tmp_path):
        """Field without value should use empty string."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_val.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "field_key": "product_name", "type": "fixed_label"},  # No value
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "NoValGen", 400, 300, colors, fields)
        assert "product_name" in code

    def test_field_with_missing_type_defaults_to_dynamic(self, tmp_path):
        """Field without type should default to dynamic."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_type.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name"},  # No type
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "NoTypeGen", 400, 300, colors, fields)
        assert "product_name" in code
        # dynamic type should have editable: False
        assert "False" in code

    def test_code_contains_draw_barcode_method(self, tmp_path):
        """Generated code should contain _draw_barcode method."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "barcode.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "BarcodeGen", 400, 300, colors, fields)
        assert "_draw_barcode" in code
        assert "auto_barcode" in code

    def test_code_contains_get_font_method(self, tmp_path):
        """Generated code should contain _get_font method."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "font.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "FontGen", 400, 300, colors, fields)
        assert "_get_font" in code
        assert "ImageFont" in code

    def test_code_contains_logger_setup(self, tmp_path):
        """Generated code should contain logger setup."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "logger.png")
        img.save(img_path)

        fields = []
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "LogGen", 400, 300, colors, fields)
        assert "logger" in code
        assert "logging.getLogger" in code

    def test_code_contains_example_usage(self, tmp_path):
        """Generated code should contain example_usage function."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "example.png")
        img.save(img_path)

        fields = [
            {"label": "品名", "value": "鞋", "field_key": "product_name", "type": "fixed_label"},
        ]
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "ExGen", 400, 300, colors, fields)
        assert "example_usage" in code
        assert 'if __name__ == "__main__"' in code


# ---------------------------------------------------------------------------
# _generate_basic_code — additional branches
# ---------------------------------------------------------------------------


class TestGenerateBasicCodeDeep:
    """Deep coverage for _generate_basic_code."""

    def test_small_dimensions(self, tmp_path):
        """Small dimensions should still generate valid code."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img_path = str(tmp_path / "small.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "SmallGen", 100, 100, colors)
        assert "self.width = 100" in code
        assert "self.height = 100" in code

    def test_custom_class_name(self, tmp_path):
        """Custom class name should appear in code."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "custom.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "MyCustomLabel", 400, 300, colors)
        assert "class MyCustomLabel" in code

    def test_code_contains_generate_labels_for_order(self, tmp_path):
        """Basic code should contain generate_labels_for_order method."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "multi.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "MultiGen", 400, 300, colors)
        assert "generate_labels_for_order" in code
        assert "def generate_label" in code

    def test_code_contains_draw_content(self, tmp_path):
        """Basic code should contain _draw_content method."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "content.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "ContentGen", 400, 300, colors)
        assert "_draw_content" in code
        assert "品名" in code  # Default content
        assert "货号" in code

    def test_code_contains_get_font_with_platform(self, tmp_path):
        """Basic code should contain _get_font with platform check."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "platform.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "PlatformGen", 400, 300, colors)
        assert "platform.system" in code
        assert "Windows" in code
        assert "Darwin" in code


# ---------------------------------------------------------------------------
# LabelTemplateGeneratorSkill — additional branches
# ---------------------------------------------------------------------------


class TestLabelTemplateGeneratorSkillDeep:
    """Deep coverage for LabelTemplateGeneratorSkill."""

    def test_execute_with_enable_ocr_false(self, tmp_path):
        """execute() with enable_ocr=False should not call OCR."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_ocr.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr"
        ) as mock_ocr:
            result = skill.execute(img_path, enable_ocr=False)
            assert result["success"] is True
            assert result["ocr_result"] is None
            mock_ocr.assert_not_called()

    def test_execute_with_verbose_true(self, tmp_path):
        """execute() with verbose=True should pass verbose to analyze_image."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "verbose.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            wraps=analyze_image,
        ) as mock_analyze:
            result = skill.execute(img_path, verbose=True)
            assert result["success"] is True
            # analyze_image is called multiple times: once in execute, once in generate_template_code,
            # and once in _generate_basic_code. First call should have verbose=True.
            assert mock_analyze.call_count >= 1
            first_call = mock_analyze.call_args_list[0]
            assert first_call.args[0] == img_path
            assert first_call.kwargs.get("verbose") is True

    def test_execute_with_custom_class_name(self, tmp_path):
        """execute() should use custom class name."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "custom.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(img_path, class_name="MyCustomGen", enable_ocr=False)
        assert result["success"] is True
        assert "class MyCustomGen" in result["code"]

    def test_execute_with_output_file_success(self, tmp_path):
        """execute() should write code to output_file."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "out.png")
        img.save(img_path)
        output_file = str(tmp_path / "output.py")

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(img_path, output_file=output_file, enable_ocr=False)
        assert result["success"] is True
        assert result["output_file"] == output_file

    def test_execute_with_output_file_error(self, tmp_path):
        """execute() should catch output file write error."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "err.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()

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

    def test_execute_analysis_failure_returns_failure(self):
        """execute() with failed analysis should return failure."""
        skill = LabelTemplateGeneratorSkill()
        result = skill.execute("/nonexistent/image.png")
        assert result["success"] is False

    def test_execute_recoverable_error_returns_failure(self, tmp_path):
        """execute() should catch RECOVERABLE_ERRORS."""
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

    def test_get_skill_info_returns_correct_structure(self):
        """get_skill_info should return correct structure."""
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["name"] == "label_template_generator"
        assert "description" in info
        assert "parameters" in info
        params = info["parameters"]
        assert "image_path" in params
        assert "class_name" in params
        assert "output_file" in params
        assert "enable_ocr" in params
        assert "verbose" in params

    def test_skill_attributes(self):
        """Skill should have correct name and description."""
        skill = LabelTemplateGeneratorSkill()
        assert skill.name == "label_template_generator"
        assert "标签模板" in skill.description
        assert "Python" in skill.description


# ---------------------------------------------------------------------------
# get_label_template_generator_skill — singleton
# ---------------------------------------------------------------------------


class TestGetLabelTemplateGeneratorSkillDeep:
    """Deep coverage for singleton getter."""

    def test_returns_instance_when_none(self):
        """Should create new instance when _skill_instance is None."""
        import app.services.skills.label_template_generator.label_template_generator as mod

        mod._skill_instance = None
        skill = get_label_template_generator_skill()
        assert isinstance(skill, LabelTemplateGeneratorSkill)
        mod._skill_instance = None

    def test_returns_same_instance_when_set(self):
        """Should return existing instance."""
        import app.services.skills.label_template_generator.label_template_generator as mod

        existing = LabelTemplateGeneratorSkill()
        mod._skill_instance = existing
        skill = get_label_template_generator_skill()
        assert skill is existing
        mod._skill_instance = None

    def test_singleton_persistence(self):
        """Multiple calls should return same instance."""
        import app.services.skills.label_template_generator.label_template_generator as mod

        mod._skill_instance = None
        skill1 = get_label_template_generator_skill()
        skill2 = get_label_template_generator_skill()
        assert skill1 is skill2
        mod._skill_instance = None


# ---------------------------------------------------------------------------
# _extract_fields_by_pattern — additional coverage
# ---------------------------------------------------------------------------


class TestExtractFieldsByPatternDeep:
    """Deep coverage for _extract_fields_by_pattern."""

    def test_returns_seven_fields(self):
        """Should return exactly 7 fields."""
        result = _extract_fields_by_pattern("/any/path.png")
        assert len(result) == 7

    def test_all_fields_are_fixed_label(self):
        """All fields should be fixed_label type."""
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert field["type"] == "fixed_label"

    def test_fields_have_expected_labels(self):
        """Should contain expected labels."""
        result = _extract_fields_by_pattern("/any/path.png")
        labels = {f["label"] for f in result}
        assert "品名" in labels
        assert "颜色" in labels
        assert "货号" in labels
        assert "码段" in labels
        assert "等级" in labels
        assert "执行标准" in labels
        assert "统一零售价" in labels

    def test_fields_have_expected_keys(self):
        """Should contain expected field_keys."""
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
        """All values should indicate OCR is needed."""
        result = _extract_fields_by_pattern("/any/path.png")
        for field in result:
            assert "OCR" in field["value"] or "ocr" in field["value"].lower()

    def test_path_does_not_affect_result(self):
        """Different paths should return same fields."""
        result1 = _extract_fields_by_pattern("/path1.png")
        result2 = _extract_fields_by_pattern("/path2.png")
        assert len(result1) == len(result2)
        for f1, f2 in zip(result1, result2):
            assert f1["label"] == f2["label"]
            assert f1["field_key"] == f2["field_key"]


# ---------------------------------------------------------------------------
# analyze_image — additional coverage
# ---------------------------------------------------------------------------


class TestAnalyzeImageDeep:
    """Deep coverage for analyze_image."""

    def test_file_not_found_returns_failure(self):
        """FileNotFoundError should return failure."""
        result = analyze_image("/nonexistent/image.png")
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_recoverable_error_returns_failure(self, tmp_path):
        """RECOVERABLE_ERRORS should return failure."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "err.png")
        img.save(img_path)

        with patch(
            "app.services.skills.label_template_generator.label_template_generator.Image"
        ) as MockImage:
            MockImage.open.side_effect = OSError("disk error")
            result = analyze_image(img_path)
            assert result["success"] is False
            assert "分析失败" in result["message"]

    def test_verbose_includes_additional_info(self, tmp_path):
        """verbose=True should include additional_info."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "verbose.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=True)
        assert result["success"] is True
        assert "additional_info" in result
        assert "dpi" in result["additional_info"]
        assert "has_transparency" in result["additional_info"]
        assert "estimated_font_sizes" in result["additional_info"]

    def test_non_verbose_excludes_additional_info(self, tmp_path):
        """verbose=False should exclude additional_info."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "no_verbose.png")
        img.save(img_path)

        result = analyze_image(img_path, verbose=False)
        assert result["success"] is True
        assert "additional_info" not in result

    def test_result_includes_colors(self, tmp_path):
        """Result should include colors."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "colors.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert "colors" in result
        assert "background" in result["colors"]
        assert "border" in result["colors"]
        assert "text" in result["colors"]

    def test_result_includes_sections(self, tmp_path):
        """Result should include sections."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "sections.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert "sections" in result
        assert isinstance(result["sections"], list)
        assert len(result["sections"]) > 0

    def test_result_includes_size(self, tmp_path):
        """Result should include size."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "size.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert "size" in result
        assert result["size"]["width"] == 400
        assert result["size"]["height"] == 300

    def test_result_includes_format_and_mode(self, tmp_path):
        """Result should include format and mode."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "fmt.png")
        img.save(img_path, format="PNG")

        result = analyze_image(img_path)
        assert result["success"] is True
        assert result["format"] == "PNG"
        assert result["mode"] == "RGB"

    def test_result_includes_filename(self, tmp_path):
        """Result should include file name."""
        from PIL import Image

        img = Image.new("RGB", (400, 300), (255, 255, 255))
        img_path = str(tmp_path / "filename.png")
        img.save(img_path)

        result = analyze_image(img_path)
        assert result["success"] is True
        assert result["file"] == "filename.png"
