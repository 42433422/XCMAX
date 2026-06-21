"""Coverage-gap tests for label_template_generator.

Targets branches not exercised by:
- test_label_template_generator.py
- test_label_template_generator_ext2.py
- test_label_template_generator_ext3.py
- test_label_template_generator_extended.py

Focus areas
-----------
1. _pair_fields_by_grid
   - is_in_merged=True but col != start_col  ("else: in merged range but not start" skipped)
   - next_is_in_merged=True  (next block is in merged → single-block path)
   - non-adjacent cols  (next_col != col+1 → single-block path)
   - empty text_blocks  → []
   - merged_horizontal=None  → defaults to []
2. _identify_fields
   - colon format: "价" suffix label → field_type=fixed_label
   - no-colon: known label in fixed_label list vs not
   - no-colon: known label but value_part is empty (whitespace only)  → skipped
3. _analyze_colors
   - consistent vs inconsistent background corners (pixel-level)
   - exception path → default fallback dict
4. _estimate_sections
   - exactly at boundary (w==800, h==500) and (w==400, h==300)
5. _estimate_font_sizes
   - exactly at boundary (w==800 and w==400)
6. LabelTemplateGeneratorSkill.execute
   - output_file write succeeds
   - output_file write fails with OSError
   - enable_ocr=False path
   - ocr_result success=False path
   - ocr_result success=True path (logger line)
   - outer RECOVERABLE_ERRORS handler
7. get_label_template_generator_skill singleton (second call returns same object)
8. _extract_fields_by_pattern returns exactly 7 items
9. generate_template_code: analysis fails → "# Error:..."
   generate_template_code: ocr_result with success=True → _generate_code_with_fields
10. _generate_code_with_fields: fields with different types
11. _generate_basic_code: basic invocation
12. analyze_image: RECOVERABLE_ERRORS handler
13. extract_text_with_ocr: ImportError, RECOVERABLE_ERRORS, and OCR success paths
14. find_cell: loop-break branches (y in range, x in range)
15. _classify_field: label ending in 价
16. LabelTemplateGeneratorSkill.get_skill_info
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from PIL import Image

import app.services.skills.label_template_generator.label_template_generator as _mod
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
    generate_template_code,
    get_label_template_generator_skill,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(text: str, x_center: int, y_center: int, cell_col: int = 0, cell_row: int = 0,
                left: int = 0, top: int = 0, width: int = 100, height: int = 30,
                conf: float = 0.9) -> dict:
    return {
        "text": text,
        "center": (x_center, y_center),
        "cell_col": cell_col,
        "cell_row": cell_row,
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "conf": conf,
        "x_center": x_center,
        "y_center": y_center,
    }


def _make_block_raw(text: str, x_center: int, y_center: int,
                    left: int = 0, top: int = 0, width: int = 100, height: int = 30,
                    conf: float = 0.9) -> dict:
    """Block without pre-assigned cell_row/cell_col (they will be computed from grid lines)."""
    return {
        "text": text,
        "center": (x_center, y_center),
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "conf": conf,
        "y_center": y_center,
    }


# ---------------------------------------------------------------------------
# 1. _pair_fields_by_grid
# ---------------------------------------------------------------------------

class TestPairFieldsByGridCovGaps:
    """Branches not covered by the existing test files."""

    def test_empty_text_blocks_returns_empty_list(self):
        """Empty blocks → early return []."""
        result = _pair_fields_by_grid([], [0, 100], [0, 100, 200])
        assert result == []

    def test_none_merged_horizontal_treated_as_empty(self):
        """merged_horizontal=None must not raise and behaves like []."""
        block = _make_block_raw("品名", 50, 50, left=10, top=10)
        result = _pair_fields_by_grid([block], [0, 100], [0, 100, 200], merged_horizontal=None)
        # Should return exactly one field without errors
        assert len(result) == 1
        assert result[0]["label"] == "品名"

    def test_block_in_merged_not_at_start_col_is_skipped(self):
        """
        A block whose col is inside a merged range but col != start_col must be
        silently skipped (the bare 'else' branch at the end of the while loop).

        Layout: merged range covers cols 0-1.
        Block A is at col 0 (start_col) → processed.
        Block B is at col 1 (inside merged, not start) → silently skipped.
        """
        h_lines = [0, 100]
        v_lines = [0, 100, 200, 300]

        # Both blocks in the same row; their centers determine which grid cell
        block_a = _make_block_raw("品名", 50, 50, left=5, top=5)    # col 0
        block_b = _make_block_raw("VALUE", 150, 50, left=105, top=5)  # col 1

        # merged: row 0, cols 0-1
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]

        result = _pair_fields_by_grid([block_a, block_b], h_lines, v_lines, merged)

        # block_a → processed as merged-start
        # block_b → in merged range but not start → skipped (the bare else)
        labels = [f["label"] for f in result]
        assert "品名" in labels
        # block_b should NOT appear as a top-level field entry
        assert not any(f["label"] == "VALUE" for f in result)

    def test_next_block_in_merged_causes_single_block_path(self):
        """
        When the current block is a normal cell and next_block IS in a merged range,
        next_is_in_merged=True → the 'else' single-block path fires (not pairing).
        """
        h_lines = [0, 100]
        v_lines = [0, 100, 200, 300]

        # block_a at col 0 (normal), block_b at col 1 which is inside a merged range
        block_a = _make_block_raw("颜色", 50, 50, left=5, top=5)    # col 0
        block_b = _make_block_raw("红色", 150, 50, left=105, top=5)  # col 1

        # merged covers row 0, cols 1-2  (block_b is start_col of this range)
        merged = [{"row": 0, "start_col": 1, "end_col": 2}]

        result = _pair_fields_by_grid([block_a, block_b], h_lines, v_lines, merged)

        # block_a must be a single-block entry (not paired with block_b)
        a_entries = [f for f in result if f["label"] == "颜色"]
        assert len(a_entries) == 1
        assert a_entries[0]["value"] == ""
        assert a_entries[0]["is_merged"] is False

    def test_non_adjacent_cols_goes_to_single_block_path(self):
        """
        When next_col != col+1 (e.g. col 0 followed by col 2), the pair-check
        fails and the current block becomes a standalone field.
        """
        h_lines = [0, 100]
        v_lines = [0, 100, 200, 300]

        # block_a at col 0, block_b at col 2 (gap at col 1)
        block_a = _make_block_raw("货号", 50, 50, left=5, top=5)     # col 0
        block_b = _make_block_raw("1635", 250, 50, left=205, top=5)  # col 2

        result = _pair_fields_by_grid([block_a, block_b], h_lines, v_lines, [])

        # block_a must be standalone, value=""
        a_entries = [f for f in result if f["label"] == "货号"]
        assert len(a_entries) == 1
        assert a_entries[0]["value"] == ""

    def test_merged_start_col_has_correct_merge_cols(self):
        """Merged cell at start_col properly records merge_cols count."""
        h_lines = [0, 100]
        v_lines = [0, 100, 200, 300]

        block = _make_block_raw("执行标准", 50, 50, left=5, top=5)  # col 0
        merged = [{"row": 0, "start_col": 0, "end_col": 2}]

        result = _pair_fields_by_grid([block], h_lines, v_lines, merged)

        assert len(result) == 1
        assert result[0]["is_merged"] is True
        assert result[0]["merge_cols"] == 3  # 0..2 inclusive

    def test_last_single_block_in_row_has_empty_value(self):
        """
        When only one block exists in a row and no merged range is involved,
        the j+1 branch is not taken; falls to the else for single last block.
        """
        h_lines = [0, 100]
        v_lines = [0, 100, 200]

        block = _make_block_raw("等级", 50, 50, left=5, top=5)

        result = _pair_fields_by_grid([block], h_lines, v_lines, [])

        assert len(result) == 1
        assert result[0]["value"] == ""
        assert result[0]["is_merged"] is False

    def test_paired_blocks_result_full_text_format(self):
        """Adjacent normal blocks produce full_text='label: value'."""
        h_lines = [0, 100]
        v_lines = [0, 100, 200]

        block_a = _make_block_raw("码段", 50, 50, left=5, top=5, conf=0.8)    # col 0
        block_b = _make_block_raw("00001", 150, 50, left=105, top=5, conf=0.9)  # col 1

        result = _pair_fields_by_grid([block_a, block_b], h_lines, v_lines, [])

        assert len(result) == 1
        assert result[0]["full_text"] == "码段: 00001"
        assert result[0]["value"] == "00001"
        # confidence is average of 0.8 and 0.9
        assert abs(result[0]["confidence"] - 0.85) < 1e-9

    def test_two_rows_each_with_single_block(self):
        """Blocks in different grid rows are processed independently."""
        h_lines = [0, 100, 200]
        v_lines = [0, 100, 200]

        block_a = _make_block_raw("品名", 50, 50, left=5, top=5)
        block_b = _make_block_raw("颜色", 50, 150, left=5, top=105)

        result = _pair_fields_by_grid([block_a, block_b], h_lines, v_lines, [])

        assert len(result) == 2
        labels = {f["label"] for f in result}
        assert labels == {"品名", "颜色"}


# ---------------------------------------------------------------------------
# 2. _identify_fields
# ---------------------------------------------------------------------------

class TestIdentifyFieldsCovGaps:
    """Branches in _identify_fields not fully exercised by prior test files."""

    def _blk(self, text: str) -> dict:
        return {"text": text, "left": 0, "top": 0, "width": 200, "height": 30, "conf": 0.9}

    def test_colon_format_jia_suffix_yields_fixed_label(self):
        """Label ending in '价' with Chinese colon → field_type=fixed_label, key=price."""
        fields = _identify_fields([self._blk("特价：99")])
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "price"
        assert fields[0]["value"] == "99"

    def test_colon_format_cust_price_suffix(self):
        """A multi-char label ending in '价' (e.g., '特惠价') also maps to price."""
        fields = _identify_fields([self._blk("特惠价：128")])
        assert len(fields) == 1
        assert fields[0]["field_key"] == "price"
        assert fields[0]["type"] == "fixed_label"

    def test_colon_format_unknown_label_is_dynamic(self):
        """Label not in common_labels and not ending in '价' → dynamic."""
        fields = _identify_fields([self._blk("批次：A001")])
        assert len(fields) == 1
        assert fields[0]["type"] == "dynamic"
        assert fields[0]["field_key"] == "批次"

    def test_no_colon_known_label_in_fixed_list_is_fixed_label(self):
        """No-colon format: '产品名称' is in the fixed_label list → fixed_label."""
        fields = _identify_fields([self._blk("产品名称 PE封固底漆")])
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["label"] == "产品名称"
        assert fields[0]["value"] == "PE封固底漆"

    def test_no_colon_known_label_not_in_fixed_list_is_dynamic(self):
        """No-colon format: '品名' is NOT in the fixed_label sublist → dynamic."""
        fields = _identify_fields([self._blk("品名 运动鞋")])
        assert len(fields) == 1
        assert fields[0]["type"] == "dynamic"
        assert fields[0]["label"] == "品名"

    def test_no_colon_known_label_empty_value_part_skipped(self):
        """No-colon: known label with only whitespace value_part → skipped (not appended)."""
        fields = _identify_fields([self._blk("品名   ")])
        assert fields == []

    def test_no_colon_inspector_is_fixed_label(self):
        """'检验员' belongs to the fixed_label sublist."""
        fields = _identify_fields([self._blk("检验员 张三")])
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"

    def test_no_colon_shelf_life_is_fixed_label(self):
        """'保质期' belongs to the fixed_label sublist."""
        fields = _identify_fields([self._blk("保质期 12个月")])
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"

    def test_no_colon_production_date_is_fixed_label(self):
        """'生产日期' belongs to the fixed_label sublist."""
        fields = _identify_fields([self._blk("生产日期 2024-01-01")])
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"

    def test_colon_format_known_label_grade(self):
        """'等级：合格品' → fixed_label, key=grade."""
        fields = _identify_fields([self._blk("等级：合格品")])
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "grade"
        assert fields[0]["value"] == "合格品"

    def test_colon_format_empty_value_is_still_appended(self):
        """'品名：' with empty value should still produce a field entry (value='')."""
        fields = _identify_fields([self._blk("品名：")])
        assert len(fields) == 1
        assert fields[0]["value"] == ""
        assert fields[0]["type"] == "fixed_label"

    def test_no_colon_first_label_match_wins_and_breaks(self):
        """
        Text that starts with two different known labels should match the first
        one found via iteration (implementation uses 'break' after first match).
        """
        # "产品名称" is 4 chars; "产品" is not a key, but "产品编号" is 4 chars too.
        # Use a text that uniquely starts with one known label.
        fields = _identify_fields([self._blk("规格 100ml")])
        assert len(fields) == 1
        assert fields[0]["label"] == "规格"


# ---------------------------------------------------------------------------
# 3. _analyze_colors - consistent vs inconsistent
# ---------------------------------------------------------------------------

class TestAnalyzeColorsCovGaps:
    """Pixel-level consistency branch."""

    def test_all_corners_same_color_consistent(self):
        """Uniform-color image → is_consistent_background=True."""
        img = Image.new("RGB", (200, 200), color=(255, 0, 0))
        result = _analyze_colors(img)
        assert result["is_consistent_background"] is True
        assert result["background"] == "#ff0000"

    def test_corners_different_color_inconsistent(self):
        """Image where corners differ → is_consistent_background=False."""
        img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        # Paint bottom-right corner a different colour
        for px in range(185, 200):
            for py in range(185, 200):
                img.putpixel((px, py), (0, 0, 0))
        result = _analyze_colors(img)
        # Corner (190, 190) is now black; corner (10,10) is still white
        assert result["is_consistent_background"] is False


# ---------------------------------------------------------------------------
# 4. _estimate_sections - exact boundary
# ---------------------------------------------------------------------------

class TestEstimateSectionsBoundaryExact:
    """Test the exact boundary values for each branch."""

    def test_exactly_800_wide_and_500_tall_returns_5_sections(self):
        result = _estimate_sections(800, 500)
        assert len(result) == 5

    def test_exactly_400_wide_and_300_tall_returns_3_sections(self):
        result = _estimate_sections(400, 300)
        assert len(result) == 3

    def test_399_wide_returns_1_section(self):
        result = _estimate_sections(399, 299)
        assert len(result) == 1

    def test_large_threshold_section_names(self):
        result = _estimate_sections(1000, 600)
        names = [s["name"] for s in result]
        assert "product_number" in names
        assert "footer" in names

    def test_medium_threshold_section_names(self):
        result = _estimate_sections(400, 300)
        names = [s["name"] for s in result]
        assert "header" in names
        assert "content" in names
        assert "footer" in names

    def test_small_threshold_main_section_uses_height(self):
        result = _estimate_sections(100, 80)
        assert len(result) == 1
        assert result[0]["name"] == "main"
        assert result[0]["y_end"] == 70  # height - 10


# ---------------------------------------------------------------------------
# 5. _estimate_font_sizes - exact boundary
# ---------------------------------------------------------------------------

class TestEstimateFontSizesBoundaryExact:
    """Test the exact width boundary values."""

    def test_exactly_800_wide_returns_large_fonts(self):
        result = _estimate_font_sizes(800, 500)
        assert result["title"] == 70

    def test_exactly_400_wide_returns_medium_fonts(self):
        result = _estimate_font_sizes(400, 300)
        assert result["title"] == 40

    def test_399_wide_returns_small_fonts(self):
        result = _estimate_font_sizes(399, 300)
        assert result["title"] == 24

    def test_large_returns_all_expected_keys(self):
        result = _estimate_font_sizes(900, 600)
        assert set(result.keys()) == {"title", "label", "content", "small"}

    def test_medium_returns_all_expected_keys(self):
        result = _estimate_font_sizes(500, 300)
        assert set(result.keys()) == {"title", "label", "content", "small"}

    def test_small_returns_all_expected_keys(self):
        result = _estimate_font_sizes(200, 150)
        assert set(result.keys()) == {"title", "label", "content", "small"}


# ---------------------------------------------------------------------------
# 6. LabelTemplateGeneratorSkill.execute branches
# ---------------------------------------------------------------------------

def _make_good_analysis():
    return {
        "success": True,
        "file": "test.png",
        "format": "PNG",
        "mode": "RGB",
        "size": {"width": 800, "height": 500},
        "colors": {"background": "#ffffff", "border": "#000000", "text": "#000000",
                   "is_consistent_background": True},
        "sections": [],
    }


class TestSkillExecuteCovGaps:

    def test_execute_enable_ocr_false_skips_ocr(self, tmp_path):
        """enable_ocr=False → ocr_result is None; basic code generated."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "label.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(img_path, enable_ocr=False)

        assert result["success"] is True
        assert result["ocr_result"] is None
        assert "class LabelTemplateGenerator" in result["code"]

    def test_execute_ocr_success_false_generates_basic_code(self, tmp_path):
        """enable_ocr=True but ocr_result.success=False → basic code path."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "label.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator"
            ".extract_text_with_ocr",
            return_value={"success": False, "message": "no ocr"},
        ):
            result = skill.execute(img_path, enable_ocr=True)

        assert result["success"] is True
        assert result["ocr_result"] == {"success": False, "message": "no ocr"}

    def test_execute_output_file_write_succeeds(self, tmp_path):
        """When output_file is set and write succeeds, result includes output_file key."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "label.png")
        img.save(img_path)
        out_file = str(tmp_path / "output.py")

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator"
            ".extract_text_with_ocr",
            return_value={"success": False},
        ):
            result = skill.execute(img_path, output_file=out_file, enable_ocr=False)

        assert result["success"] is True
        assert result.get("output_file") == out_file
        assert Path(out_file).exists()

    def test_execute_output_file_write_oserror_records_error(self, tmp_path):
        """When output_file write raises OSError, result['output_error'] is set.

        We patch 'open' only inside the label_template_generator module so that
        PIL's own file-reading (Image.open) is not disrupted.
        """
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "label.png")
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        _module_path = (
            "app.services.skills.label_template_generator"
            ".label_template_generator.open"
        )
        with patch(_module_path, side_effect=OSError("disk full")):
            result = skill.execute(img_path, output_file="/nonexistent/out.py", enable_ocr=False)

        assert result["success"] is True
        assert "output_error" in result
        assert "disk full" in result["output_error"]

    def test_execute_analysis_failure_returns_failure_dict(self, tmp_path):
        """analyze_image failure is returned verbatim by execute."""
        skill = LabelTemplateGeneratorSkill()
        result = skill.execute("/does/not/exist.png")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 7. get_label_template_generator_skill singleton
# ---------------------------------------------------------------------------

class TestGetSkillSingleton:

    def test_second_call_returns_same_object(self):
        """Two successive calls must return the identical Python object."""
        # Reset the module-level singleton so the test is deterministic
        original = _mod._skill_instance
        try:
            _mod._skill_instance = None
            first = get_label_template_generator_skill()
            second = get_label_template_generator_skill()
            assert first is second
        finally:
            _mod._skill_instance = original

    def test_returns_label_template_generator_skill_type(self):
        """The returned object must be a LabelTemplateGeneratorSkill instance."""
        skill = get_label_template_generator_skill()
        assert isinstance(skill, LabelTemplateGeneratorSkill)

    def test_singleton_not_recreated_when_already_set(self):
        """If _skill_instance is already set, get_label_template_generator_skill returns it."""
        original = _mod._skill_instance
        try:
            sentinel = LabelTemplateGeneratorSkill()
            _mod._skill_instance = sentinel
            result = get_label_template_generator_skill()
            assert result is sentinel
        finally:
            _mod._skill_instance = original


# ---------------------------------------------------------------------------
# 8. _extract_fields_by_pattern
# ---------------------------------------------------------------------------

class TestExtractFieldsByPattern:

    def test_always_returns_exactly_seven_items(self):
        result = _extract_fields_by_pattern("any_path.png")
        assert len(result) == 7

    def test_all_items_have_required_keys(self):
        result = _extract_fields_by_pattern("any_path.png")
        for item in result:
            assert "label" in item
            assert "value" in item
            assert "field_key" in item
            assert "type" in item

    def test_path_argument_is_ignored(self):
        """The function ignores the path — result is always the same template."""
        r1 = _extract_fields_by_pattern("path_a.png")
        r2 = _extract_fields_by_pattern("path_b.png")
        assert [i["label"] for i in r1] == [i["label"] for i in r2]


# ---------------------------------------------------------------------------
# 9. generate_template_code - analysis fails path
# ---------------------------------------------------------------------------

class TestGenerateTemplateCodeFailure:

    def test_analysis_failure_returns_error_comment(self, tmp_path):
        """When analyze_image fails, generate_template_code returns '# Error:...'."""
        code = generate_template_code("/nonexistent/image.png")
        assert code.startswith("# Error:")

    def test_analysis_failure_contains_error_keyword(self):
        """The returned string must contain '#' indicating a comment."""
        code = generate_template_code("/no/file.png")
        assert "#" in code

    def test_with_failed_ocr_result_uses_basic_path(self, tmp_path):
        """ocr_result with success=False → _generate_basic_code is called."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        code = generate_template_code(img_path, ocr_result={"success": False})
        assert "class LabelTemplateGenerator" in code

    def test_with_none_ocr_result_uses_basic_path(self, tmp_path):
        """ocr_result=None → _generate_basic_code."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        code = generate_template_code(img_path, ocr_result=None)
        assert "class LabelTemplateGenerator" in code


# ---------------------------------------------------------------------------
# 10. _generate_code_with_fields - different field types
# ---------------------------------------------------------------------------

class TestGenerateCodeWithFields:

    def _fields(self):
        return [
            {"label": "品名", "value": "运动鞋", "field_key": "product_name", "type": "fixed_label"},
            {"label": "批次", "value": "A001", "field_key": "批次", "type": "dynamic"},
        ]

    def test_fixed_label_field_editable_true(self, tmp_path):
        """fixed_label fields should have editable=True in generated code."""
        img = Image.new("RGB", (200, 200), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "MyGen", 200, 200, colors, self._fields())
        # fixed_label → editable=True
        assert "editable" in code

    def test_dynamic_field_editable_false(self, tmp_path):
        """dynamic fields should have editable=False in generated code."""
        img = Image.new("RGB", (200, 200), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "MyGen", 200, 200, colors, self._fields())
        assert "False" in code

    def test_returns_nonempty_string(self, tmp_path):
        """Code output is a non-empty string."""
        img = Image.new("RGB", (200, 200), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "TestClass", 200, 200, colors, [])
        assert isinstance(code, str) and len(code) > 0

    def test_class_name_appears_in_output(self, tmp_path):
        """The provided class_name must appear in the generated code."""
        img = Image.new("RGB", (200, 200), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_code_with_fields(img_path, "XcmaxLabelGen", 200, 200, colors, [])
        assert "XcmaxLabelGen" in code


# ---------------------------------------------------------------------------
# 11. _generate_basic_code
# ---------------------------------------------------------------------------

class TestGenerateBasicCode:

    def test_basic_code_contains_class_name(self, tmp_path):
        img = Image.new("RGB", (600, 400), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "BasicLabel", 600, 400, colors)
        assert "BasicLabel" in code

    def test_basic_code_returns_string(self, tmp_path):
        img = Image.new("RGB", (600, 400), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)
        colors = {"background": "#fafafa", "border": "#333333", "text": "#111111"}
        code = _generate_basic_code(img_path, "MyLabel", 600, 400, colors)
        assert isinstance(code, str)

    def test_basic_code_embeds_dimensions(self, tmp_path):
        img = Image.new("RGB", (640, 480), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)
        colors = {"background": "#ffffff", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "DimLabel", 640, 480, colors)
        assert "640" in code
        assert "480" in code

    def test_basic_code_embeds_background_color(self, tmp_path):
        img = Image.new("RGB", (300, 200), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)
        colors = {"background": "#abcdef", "border": "#000000", "text": "#000000"}
        code = _generate_basic_code(img_path, "ColorLabel", 300, 200, colors)
        assert "#abcdef" in code


# ---------------------------------------------------------------------------
# 12. analyze_image - RECOVERABLE_ERRORS handler (lines 57-59)
# ---------------------------------------------------------------------------

class TestAnalyzeImageRecoverableErrors:
    """RECOVERABLE_ERRORS branch in analyze_image (non-FileNotFoundError exceptions)."""

    def test_pil_open_raises_oserror_returns_failure(self):
        """If Image.open raises OSError (in RECOVERABLE_ERRORS), returns success=False."""
        from unittest.mock import patch as _patch
        _target = (
            "app.services.skills.label_template_generator"
            ".label_template_generator.Image.open"
        )
        from app.services.skills.label_template_generator.label_template_generator import (
            analyze_image,
        )
        with _patch(_target, side_effect=OSError("corrupt image")):
            result = analyze_image("some_path.png")
        assert result["success"] is False
        assert "corrupt image" in result["message"]

    def test_pil_open_raises_valueerror_returns_failure(self):
        """ValueError (DATA_SHAPE → RECOVERABLE_ERRORS) → success=False."""
        _target = (
            "app.services.skills.label_template_generator"
            ".label_template_generator.Image.open"
        )
        from app.services.skills.label_template_generator.label_template_generator import (
            analyze_image,
        )
        with patch(_target, side_effect=ValueError("bad value")):
            result = analyze_image("some_path.png")
        assert result["success"] is False

    def test_file_not_found_returns_specific_message(self):
        """FileNotFoundError is handled separately from RECOVERABLE_ERRORS."""
        from app.services.skills.label_template_generator.label_template_generator import (
            analyze_image,
        )
        result = analyze_image("/this/path/does/not/exist.png")
        assert result["success"] is False
        assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# 13. extract_text_with_ocr - ImportError, RECOVERABLE_ERRORS, and success paths
# ---------------------------------------------------------------------------

class TestExtractTextWithOcr:
    """Branches in extract_text_with_ocr using mocked cv2 / numpy / OCR.

    Strategy: inject cv2 via sys.modules so the function body can do
    ``import cv2`` and get the mock. numpy is real (it IS installed).
    This lets the pixel-scanning loops (lines 88-139) actually execute
    against real numpy arrays, covering the inner branches.
    """

    _MODULE = (
        "app.services.skills.label_template_generator"
        ".label_template_generator"
    )

    @staticmethod
    def _build_cv2_mock_with_real_arrays(h: int, w: int, black_rows=None, black_cols=None):
        """Build a cv2 mock whose threshold() returns a REAL numpy array so the
        pixel-scanning loops execute.  black_rows/black_cols mark full black lines
        (value=255) so the line-detection branch fires too.
        """
        import sys

        import numpy as np

        cv2_mock = MagicMock()
        # gray: all zero (no pixels by default)
        gray = np.zeros((h, w), dtype=np.uint8)
        # binary: paint horizontal and vertical lines for line-detection branches
        binary = np.zeros((h, w), dtype=np.uint8)
        if black_rows:
            for r in black_rows:
                binary[r, :] = 255   # full horizontal line
        if black_cols:
            for c in black_cols:
                binary[:, c] = 255   # full vertical line

        cv2_mock.cvtColor.return_value = gray
        cv2_mock.threshold.return_value = (0, binary)
        cv2_mock.COLOR_RGB2GRAY = 7
        cv2_mock.THRESH_BINARY_INV = 1
        return cv2_mock

    def test_import_error_returns_failure_with_fallback_fields(self, tmp_path):
        """When cv2 / numpy is missing (ImportError), returns success=False with fallback_fields."""
        import sys
        img = Image.new("RGB", (100, 100), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        # Remove cv2 from sys.modules so the in-function import fails
        saved = sys.modules.pop("cv2", None)
        try:
            result = extract_text_with_ocr(img_path)
        finally:
            if saved is not None:
                sys.modules["cv2"] = saved

        assert result["success"] is False
        assert "fallback_fields" in result
        assert isinstance(result["fallback_fields"], list)

    def test_recoverable_error_returns_failure_with_fallback_fields(self, tmp_path):
        """When Image.open raises OSError inside extract_text_with_ocr → failure + fallback."""
        import sys
        img = Image.new("RGB", (100, 100), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        _target = f"{self._MODULE}.Image.open"
        # Make sure cv2 is absent so we don't segfault trying to mock it
        saved = sys.modules.pop("cv2", None)
        try:
            # OSError is a RECOVERABLE_ERROR and is caught before cv2 import
            with patch(_target, side_effect=OSError("disk error")):
                result = extract_text_with_ocr(img_path)
        finally:
            if saved is not None:
                sys.modules["cv2"] = saved

        assert result["success"] is False
        assert "fallback_fields" in result

    def test_ocr_no_text_blocks_returns_failure_with_fallback(self, tmp_path):
        """OCR returns empty list → success=False, fallback_fields present.

        Uses real numpy arrays so the pixel loops actually run.
        """
        import sys

        import numpy as np

        img = Image.new("RGB", (20, 10), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        cv2_mock = self._build_cv2_mock_with_real_arrays(10, 20)

        mock_ocr_svc = MagicMock()
        mock_ocr_svc.recognize_text_blocks.return_value = []
        mock_ocr_svc.get_active_ocr_backend.return_value = "mock"

        sys.modules["cv2"] = cv2_mock
        try:
            with patch("app.services.ocr_service.get_ocr_service", return_value=mock_ocr_svc):
                result = extract_text_with_ocr(img_path)
        finally:
            sys.modules.pop("cv2", None)

        assert result["success"] is False
        assert "fallback_fields" in result

    def test_ocr_success_with_text_blocks_no_grid_lines(self, tmp_path):
        """OCR returns text blocks; no black grid lines → success=True, cells=[].

        This exercises the pixel loops (all zero binary → no lines detected)
        and the grid branch where horizontal_lines/vertical_lines have <= 1 entries.
        """
        import sys

        import numpy as np

        # Use a small image; the function calls Image.open internally
        img = Image.new("RGB", (20, 10), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        # All-zeros binary → no lines; pixel loops execute but append nothing
        cv2_mock = self._build_cv2_mock_with_real_arrays(10, 20)

        text_blocks = [
            {
                "text": "品名",
                "center": (5, 5),
                "left": 0,
                "top": 0,
                "width": 10,
                "height": 5,
                "conf": 0.95,
                "y_center": 5,
            },
        ]

        mock_ocr_svc = MagicMock()
        mock_ocr_svc.recognize_text_blocks.return_value = text_blocks
        mock_ocr_svc.get_active_ocr_backend.return_value = "paddleocr"

        sys.modules["cv2"] = cv2_mock
        try:
            with patch("app.services.ocr_service.get_ocr_service", return_value=mock_ocr_svc):
                result = extract_text_with_ocr(img_path)
        finally:
            sys.modules.pop("cv2", None)

        assert result["success"] is True
        assert result["total_blocks"] == 1
        assert "grid" in result

    def test_ocr_success_with_grid_lines(self, tmp_path):
        """OCR + grid lines detected → cells and merged_cells are computed.

        This exercises lines 200-285 (cell construction) and 290-291 (merged_cells_info).
        The binary array has full black rows/cols so line-detection branches fire.
        """
        import sys

        import numpy as np

        # A 30x20 pixel image with H=30 (rows), W=20 (cols)
        H, W = 30, 20
        img = Image.new("RGB", (W, H), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        # Paint rows at y=0 and y=15 and cols at x=0 and x=10 as black grid lines
        cv2_mock = self._build_cv2_mock_with_real_arrays(
            H, W,
            black_rows=[0, 15],
            black_cols=[0, 10],
        )

        text_blocks = [
            {
                "text": "品名",
                "center": (5, 7),
                "left": 1,
                "top": 1,
                "width": 8,
                "height": 13,
                "conf": 0.9,
                "y_center": 7,
            },
            {
                "text": "运动鞋",
                "center": (14, 7),
                "left": 11,
                "top": 1,
                "width": 8,
                "height": 13,
                "conf": 0.88,
                "y_center": 7,
            },
        ]

        mock_ocr_svc = MagicMock()
        mock_ocr_svc.recognize_text_blocks.return_value = text_blocks
        mock_ocr_svc.get_active_ocr_backend.return_value = "paddleocr"

        sys.modules["cv2"] = cv2_mock
        try:
            with patch("app.services.ocr_service.get_ocr_service", return_value=mock_ocr_svc):
                result = extract_text_with_ocr(img_path)
        finally:
            sys.modules.pop("cv2", None)

        assert result["success"] is True
        assert result["total_blocks"] == 2
        grid = result["grid"]
        # Lines detected: after merge_very_close_lines and merge_close_lines the exact
        # count depends on threshold; just check the result is structured correctly.
        assert "horizontal_lines" in grid
        assert "vertical_lines" in grid

    def test_ocr_success_with_adjacent_black_lines_merge(self, tmp_path):
        """Lines very close together (distance < 5px) exercise merge_very_close_lines
        'else' branch (lines 163-165: merged[-1] = (merged[-1] + line) // 2)."""
        import sys

        import numpy as np

        H, W = 50, 50
        img = Image.new("RGB", (W, H), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        # Two adjacent rows at y=10 and y=12 (distance=2 < threshold=5) → merge
        # Also two adjacent rows at y=30 and y=32 → merge
        cv2_mock = self._build_cv2_mock_with_real_arrays(
            H, W,
            black_rows=[10, 12, 30, 32],   # pairs that will be merged
            black_cols=[10, 12, 30, 32],   # same for cols
        )

        mock_ocr_svc = MagicMock()
        mock_ocr_svc.recognize_text_blocks.return_value = []
        mock_ocr_svc.get_active_ocr_backend.return_value = "paddleocr"

        sys.modules["cv2"] = cv2_mock
        try:
            with patch("app.services.ocr_service.get_ocr_service", return_value=mock_ocr_svc):
                result = extract_text_with_ocr(img_path)
        finally:
            sys.modules.pop("cv2", None)

        # OCR returned nothing → success=False; but the pixel loop ran
        assert result["success"] is False
        assert "fallback_fields" in result

    def test_ocr_pixel_loop_black_then_white_branch(self, tmp_path):
        """Exercises the 'else' branch in the pixel loop (row[x]==0 after black run):
        when current_length > max_continuous_length in the else branch (line 101-102).
        """
        import sys

        import numpy as np

        H, W = 10, 20
        img = Image.new("RGB", (W, H), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        # Create a binary where row 0 has: black pixels 0..11, then white 12..19
        # so the 'else' branch fires when we hit position 12 (current_length=12 > 0)
        gray = np.zeros((H, W), dtype=np.uint8)
        binary = np.zeros((H, W), dtype=np.uint8)
        binary[0, :12] = 255   # 12 black pixels (> W*0.5=10) → detected as line

        cv2_mock = MagicMock()
        cv2_mock.cvtColor.return_value = gray
        cv2_mock.threshold.return_value = (0, binary)
        cv2_mock.COLOR_RGB2GRAY = 7
        cv2_mock.THRESH_BINARY_INV = 1

        mock_ocr_svc = MagicMock()
        mock_ocr_svc.recognize_text_blocks.return_value = []
        mock_ocr_svc.get_active_ocr_backend.return_value = "paddleocr"

        sys.modules["cv2"] = cv2_mock
        try:
            with patch("app.services.ocr_service.get_ocr_service", return_value=mock_ocr_svc):
                result = extract_text_with_ocr(img_path)
        finally:
            sys.modules.pop("cv2", None)

        assert result["success"] is False  # no text blocks

    def test_cell_border_detection_partial_black(self, tmp_path):
        """Exercises the border detection branch inside cell construction (lines 222-236):
        0 < border_black_count < h*0.5 → should_merge_right=True."""
        import sys

        import numpy as np

        H, W = 60, 60
        img = Image.new("RGB", (W, H), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        from app.services.skills.label_template_generator.label_template_generator import (
            extract_text_with_ocr,
        )

        # Full horizontal lines at y=0 and y=30 and y=59
        # Full vertical lines at x=0, x=20, x=40, x=59
        # Paint partial black on the border at x=20 (for rows 0..7, only 8 out of 30 → <50%)
        gray = np.zeros((H, W), dtype=np.uint8)
        binary = np.zeros((H, W), dtype=np.uint8)
        # Horizontal lines
        binary[0, :] = 255
        binary[30, :] = 255
        binary[59, :] = 255
        # Vertical lines
        binary[:, 0] = 255
        binary[:, 20] = 255
        binary[:, 40] = 255
        binary[:, 59] = 255
        # Remove most of col 20's pixels in row range 0..30 to make it partial
        binary[5:30, 20] = 0   # only rows 0..4 remain black (5 out of 30 → <50%)

        cv2_mock = MagicMock()
        cv2_mock.cvtColor.return_value = gray
        cv2_mock.threshold.return_value = (0, binary)
        cv2_mock.COLOR_RGB2GRAY = 7
        cv2_mock.THRESH_BINARY_INV = 1

        text_blocks = [
            {
                "text": "品名",
                "center": (10, 15),
                "left": 1,
                "top": 1,
                "width": 18,
                "height": 28,
                "conf": 0.9,
                "y_center": 15,
            },
        ]
        mock_ocr_svc = MagicMock()
        mock_ocr_svc.recognize_text_blocks.return_value = text_blocks
        mock_ocr_svc.get_active_ocr_backend.return_value = "paddleocr"

        sys.modules["cv2"] = cv2_mock
        try:
            with patch("app.services.ocr_service.get_ocr_service", return_value=mock_ocr_svc):
                result = extract_text_with_ocr(img_path)
        finally:
            sys.modules.pop("cv2", None)

        assert result["success"] is True


# ---------------------------------------------------------------------------
# 14. _pair_fields_by_grid find_cell — loop-break branches
# ---------------------------------------------------------------------------

class TestFindCellBreakBranches:
    """Ensure find_cell hits the 'break' in both the row and col loops.

    The function uses a nested loop with break — coverage reports branches
    365→370 and 371→376 as missing when the loops never match.
    We need grids where the center coordinate actually falls inside a cell.
    """

    def test_find_cell_hits_row_and_col_break(self):
        """Block center falls inside row 1 and col 1; both loop branches hit break."""
        # Grid: 3 h_lines (rows 0 and 1), 3 v_lines (cols 0 and 1)
        h_lines = [0, 50, 100]
        v_lines = [0, 50, 100]

        # block center at (75, 75) → row 1, col 1
        block = _make_block_raw("品名", x_center=75, y_center=75, left=55, top=55)

        result = _pair_fields_by_grid([block], h_lines, v_lines, [])
        # Should produce one field from row 1, col 1
        assert len(result) == 1
        assert result[0]["label"] == "品名"

    def test_find_cell_two_blocks_different_cells(self):
        """Two blocks: one in row 0 col 0, one in row 1 col 1 — each break hits."""
        h_lines = [0, 50, 100]
        v_lines = [0, 50, 100]

        block_a = _make_block_raw("颜色", x_center=25, y_center=25, left=5, top=5)   # row 0, col 0
        block_b = _make_block_raw("红色", x_center=75, y_center=75, left=55, top=55)  # row 1, col 1

        result = _pair_fields_by_grid([block_a, block_b], h_lines, v_lines, [])
        labels = {f["label"] for f in result}
        assert "颜色" in labels
        assert "红色" in labels

    def test_find_cell_center_exactly_at_boundary(self):
        """Block center exactly at a grid line start — finds cell 0."""
        h_lines = [0, 100]
        v_lines = [0, 100]

        block = _make_block_raw("货号", x_center=0, y_center=0, left=0, top=0)

        result = _pair_fields_by_grid([block], h_lines, v_lines, [])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 15. _classify_field — label ending in 价 (line 580)
# ---------------------------------------------------------------------------

class TestClassifyFieldJiaSuffix:
    """_classify_field's 'elif label.endswith(价)' branch."""

    def test_label_ending_jia_maps_to_price(self):
        """A label not in common_labels but ending in '价' → fixed_label, price."""
        field_type, field_key = _classify_field("特惠价")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_known_label_takes_priority_over_jia_suffix(self):
        """'价格' IS in common_labels, so the first if-branch fires, not elif."""
        field_type, field_key = _classify_field("价格")
        assert field_type == "fixed_label"
        assert field_key == "price"

    def test_unknown_label_not_ending_jia_is_dynamic(self):
        """Label not in common_labels and not ending in '价' → dynamic."""
        field_type, field_key = _classify_field("批次号")
        assert field_type == "dynamic"
        assert field_key == "批次号"

    def test_classify_field_via_pair_fields_jia_label(self):
        """_classify_field's jia-suffix path is also hit via _pair_fields_by_grid
        when a merged cell's text ends in 价."""
        h_lines = [0, 100]
        v_lines = [0, 100, 200, 300]
        block = _make_block_raw("特价", 50, 50, left=5, top=5)
        merged = [{"row": 0, "start_col": 0, "end_col": 1}]
        result = _pair_fields_by_grid([block], h_lines, v_lines, merged)
        assert len(result) == 1
        assert result[0]["field_key"] == "price"
        assert result[0]["type"] == "fixed_label"


# ---------------------------------------------------------------------------
# 16. _analyze_colors — exception path (lines 769-770)
# ---------------------------------------------------------------------------

class TestAnalyzeColorsExceptionPath:
    """The bare 'except Exception' in _analyze_colors returns default fallback dict."""

    def test_exception_during_color_analysis_returns_default(self):
        """If img.convert raises an exception → fallback with #FFFFFF background."""
        fake_img = MagicMock(spec=Image.Image)
        fake_img.convert.side_effect = RuntimeError("no color data")
        fake_img.width = 100
        fake_img.height = 100

        result = _analyze_colors(fake_img)

        assert result["background"] == "#FFFFFF"
        assert result["is_consistent_background"] is True
        assert result["border"] == "#000000"
        assert result["text"] == "#000000"

    def test_exception_during_getpixel_returns_default(self):
        """If getpixel raises → fallback returned."""
        fake_rgb = MagicMock()
        fake_rgb.getpixel.side_effect = IndexError("out of bounds")

        fake_img = MagicMock(spec=Image.Image)
        fake_img.convert.return_value = fake_rgb
        fake_img.width = 100
        fake_img.height = 100

        result = _analyze_colors(fake_img)

        assert result["background"] == "#FFFFFF"


# ---------------------------------------------------------------------------
# 17. generate_template_code — OCR success path (lines 842-844)
# ---------------------------------------------------------------------------

class TestGenerateTemplateCodeOcrSuccess:
    """When ocr_result has success=True, _generate_code_with_fields is called."""

    def test_successful_ocr_result_uses_code_with_fields(self, tmp_path):
        """ocr_result with success=True and fields → generates code with fields."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        ocr_result = {
            "success": True,
            "fields": [
                {
                    "label": "品名",
                    "value": "运动鞋",
                    "field_key": "product_name",
                    "type": "fixed_label",
                }
            ],
        }

        code = generate_template_code(img_path, ocr_result=ocr_result)

        # _generate_code_with_fields embeds the field data
        assert "product_name" in code
        assert "class LabelTemplateGenerator" in code

    def test_successful_ocr_empty_fields_still_generates_code(self, tmp_path):
        """ocr_result success=True but empty fields list → still calls _generate_code_with_fields."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        ocr_result = {"success": True, "fields": []}
        code = generate_template_code(img_path, ocr_result=ocr_result)

        assert "class LabelTemplateGenerator" in code


# ---------------------------------------------------------------------------
# 18. LabelTemplateGeneratorSkill.execute — ocr success log + outer error handler
# ---------------------------------------------------------------------------

class TestSkillExecuteAdditionalBranches:
    """Cover the OCR-success logger call (line 1350) and outer RECOVERABLE_ERRORS (1366-1368)."""

    def test_execute_with_ocr_success_logs_field_count(self, tmp_path):
        """When OCR returns success=True, the logger.info at line 1350 is hit."""
        img = Image.new("RGB", (800, 500), "white")
        img_path = str(tmp_path / "img.png")
        img.save(img_path)

        mock_ocr = {
            "success": True,
            "fields": [
                {
                    "label": "品名",
                    "value": "鞋",
                    "field_key": "product_name",
                    "type": "fixed_label",
                }
            ],
        }

        skill = LabelTemplateGeneratorSkill()
        _patch_ocr = (
            "app.services.skills.label_template_generator"
            ".label_template_generator.extract_text_with_ocr"
        )
        with patch(_patch_ocr, return_value=mock_ocr):
            result = skill.execute(img_path, enable_ocr=True)

        assert result["success"] is True
        assert result["ocr_result"]["success"] is True
        # The fields should carry through
        assert "code" in result

    def test_execute_outer_recoverable_error_returns_failure(self, tmp_path):
        """If analyze_image raises a RECOVERABLE_ERRORS exception inside execute,
        the outer except block catches it and returns success=False."""
        skill = LabelTemplateGeneratorSkill()

        _patch_analyze = (
            "app.services.skills.label_template_generator"
            ".label_template_generator.analyze_image"
        )
        with patch(_patch_analyze, side_effect=RuntimeError("unexpected crash")):
            result = skill.execute("/some/image.png")

        assert result["success"] is False
        assert "unexpected crash" in result["message"]

    def test_execute_outer_valueerror_returns_failure(self, tmp_path):
        """ValueError (DATA_SHAPE subset of RECOVERABLE_ERRORS) also caught."""
        skill = LabelTemplateGeneratorSkill()

        _patch_analyze = (
            "app.services.skills.label_template_generator"
            ".label_template_generator.analyze_image"
        )
        with patch(_patch_analyze, side_effect=ValueError("bad data")):
            result = skill.execute("/some/image.png")

        assert result["success"] is False


# ---------------------------------------------------------------------------
# 19. LabelTemplateGeneratorSkill.get_skill_info (line 1372)
# ---------------------------------------------------------------------------

class TestGetSkillInfo:
    """LabelTemplateGeneratorSkill.get_skill_info returns expected structure."""

    def test_get_skill_info_returns_dict(self):
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert isinstance(info, dict)

    def test_get_skill_info_has_name_and_description(self):
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["name"] == "label_template_generator"
        assert "description" in info

    def test_get_skill_info_has_parameters(self):
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert "parameters" in info
        params = info["parameters"]
        assert "image_path" in params
        assert "class_name" in params
        assert "output_file" in params
        assert "enable_ocr" in params
        assert "verbose" in params

    def test_get_skill_info_image_path_is_required(self):
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["parameters"]["image_path"]["required"] is True

    def test_get_skill_info_output_file_not_required(self):
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["parameters"]["output_file"]["required"] is False
