"""Behavior tests for app/domain/context/session_context.py.

Each test asserts the concrete return value / produced line content (exact
strings, exact dict shape, exact header rows) rather than mere non-emptiness,
and exercises both the success and the fall-through / failure branch of the
helper under test.  No external I/O — all pure logic.
"""

from __future__ import annotations

from app.domain.context.session_context import (
    _excel_analysis_from_runtime,
    _format_kitten_runtime_for_llm,
    _sanitize_untrusted_context_line,
    detected_excel_header_row_1based,
    enrich_excel_tool_arguments,
    enrich_template_preview_arguments,
    format_excel_analysis_for_llm,
    format_recent_messages_excerpt_for_llm,
    format_runtime_context_for_llm,
    merge_system_prompt,
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)

# ─────────────── detected_excel_header_row_1based ───────────────


class TestDetectedHeaderRow:
    """Covers all branches in the header-row detection logic (lines 25-110)."""

    def test_non_dict_returns_none(self):
        assert detected_excel_header_row_1based(None) is None
        assert detected_excel_header_row_1based("string") is None
        assert detected_excel_header_row_1based([]) is None
        assert detected_excel_header_row_1based(42) is None

    # ---------- _from_tables branches (lines ~35-45) ----------

    def test_from_tables_non_list_returns_none(self):
        ea = {"preview_data": {"tables": "oops"}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_empty_list_returns_none(self):
        ea = {"preview_data": {"tables": []}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_first_not_dict_returns_none(self):
        ea = {"preview_data": {"tables": ["not_a_dict"]}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_header_none_returns_none(self):
        ea = {"preview_data": {"tables": [{}]}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_header_zero_returns_none(self):
        # header_row == 0 is below the 1-based floor → rejected.
        ea = {"preview_data": {"tables": [{"header_row": 0}]}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_bad_type_returns_none(self):
        ea = {"preview_data": {"tables": [{"header_row": "abc"}]}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_valid(self):
        ea = {"preview_data": {"tables": [{"header_row": 3}]}}
        assert detected_excel_header_row_1based(ea) == 3

    def test_from_tables_numeric_string_coerced(self):
        # "5" coerces via int() to a valid 1-based row.
        ea = {"preview_data": {"tables": [{"header_row": "5"}]}}
        assert detected_excel_header_row_1based(ea) == 5

    def test_from_tables_float_truncates_to_int(self):
        ea = {"preview_data": {"tables": [{"header_row": 2.9}]}}
        assert detected_excel_header_row_1based(ea) == 2

    # ---------- _from_sheet_entry branches (lines ~47-59) ----------

    def test_from_sheet_entry_non_dict_returns_none(self):
        ea = {"sheets": ["oops"]}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_none_hri(self):
        ea = {"sheets": [{"grid_preview": {}}]}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_bad_type(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": "bad"}}]}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_zero_falls_to_tables(self):
        # hri==0 rejected; no tables present → None overall.
        ea = {"sheets": [{"grid_preview": {"header_row_index": 0}}]}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_zero_uses_tables_fallback(self):
        # hri==0 rejected → _from_tables on same entry yields the value.
        ea = {"sheets": [{"grid_preview": {"header_row_index": 0}, "tables": [{"header_row": 9}]}]}
        assert detected_excel_header_row_1based(ea) == 9

    def test_from_sheet_entry_grid_preview_valid(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": 2}}]}
        assert detected_excel_header_row_1based(ea) == 2

    def test_from_sheet_entry_tables_fallback(self):
        ea = {"sheets": [{"tables": [{"header_row": 4}]}]}
        assert detected_excel_header_row_1based(ea) == 4

    # ---------- preferred_sheet_name branches (lines ~62-87) ----------

    def test_preferred_sheet_no_match_falls_through(self):
        # preferred "B" doesn't match → code falls through to the top-level
        # sheets[0] fallback which returns its header_row_index.
        ea = {"sheets": [{"sheet_name": "A", "grid_preview": {"header_row_index": 2}}]}
        result = detected_excel_header_row_1based(ea, preferred_sheet_name="B")
        assert result == 2

    def test_preferred_sheet_match_in_sheets(self):
        # Match on "B" wins over sheets[0]="A" — proves the preferred lookup
        # short-circuits before the sheets[0] fallback.
        ea = {
            "sheets": [
                {"sheet_name": "A", "grid_preview": {"header_row_index": 2}},
                {"sheet_name": "B", "grid_preview": {"header_row_index": 5}},
            ]
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="B") == 5

    def test_preferred_sheet_whitespace_trimmed_on_both_sides(self):
        # both the requested name and the stored name are stripped before compare.
        ea = {
            "sheets": [
                {"sheet_name": "  B  ", "grid_preview": {"header_row_index": 8}},
            ]
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name=" B ") == 8

    def test_preferred_sheet_non_dict_entry_in_sheets(self):
        ea = {
            "sheets": [
                "not_a_dict",
                {"sheet_name": "B", "grid_preview": {"header_row_index": 5}},
            ]
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="B") == 5

    def test_preferred_sheet_mismatch_uses_sheets_fallback(self):
        ea = {
            "sheets": [
                {"sheet_name": "A", "grid_preview": {"header_row_index": 2}},
            ]
        }
        result = detected_excel_header_row_1based(ea, preferred_sheet_name="B")
        assert result == 2  # sheets[0] fallback fires

    def test_preferred_sheet_hit_returns_none_falls_to_preview(self):
        """Sheet found but entry yields None — fallback to top-level preview."""
        ea = {
            "sheets": [{"sheet_name": "B"}],
            "preview_data": {"grid_preview": {"header_row_index": 7}},
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="B") == 7

    def test_preferred_via_all_sheets_in_preview_data(self):
        ea = {
            "preview_data": {
                "all_sheets": [
                    {"sheet_name": "S1", "grid_preview": {"header_row_index": 6}},
                ]
            }
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="S1") == 6

    def test_preferred_via_all_sheets_non_dict_entry_skipped(self):
        ea = {
            "preview_data": {
                "all_sheets": [
                    "oops",
                    {"sheet_name": "S1", "grid_preview": {"header_row_index": 6}},
                ]
            }
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="S1") == 6

    def test_preferred_all_sheets_name_mismatch(self):
        # No "S1" anywhere and no other fallback present → None.
        ea = {
            "preview_data": {
                "all_sheets": [
                    {"sheet_name": "S2", "grid_preview": {"header_row_index": 6}},
                ]
            }
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="S1") is None

    def test_sheets_match_wins_over_preview_data(self):
        # Preferred match in `sheets` is consulted before top-level preview_data.
        ea = {
            "sheets": [{"sheet_name": "X", "grid_preview": {"header_row_index": 3}}],
            "preview_data": {"grid_preview": {"header_row_index": 9}},
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="X") == 3

    # ---------- top-level fallbacks (lines ~88-110) ----------

    def test_top_level_preview_data_not_dict(self):
        ea = {"preview_data": "string"}
        assert detected_excel_header_row_1based(ea) is None

    def test_top_level_preview_grid_bad_hri(self):
        ea = {"preview_data": {"grid_preview": {"header_row_index": "nope"}}}
        assert detected_excel_header_row_1based(ea) is None

    def test_top_level_preview_grid_zero(self):
        ea = {"preview_data": {"grid_preview": {"header_row_index": 0}}}
        assert detected_excel_header_row_1based(ea) is None

    def test_top_level_preview_grid_valid(self):
        ea = {"preview_data": {"grid_preview": {"header_row_index": 5}}}
        assert detected_excel_header_row_1based(ea) == 5

    def test_top_level_preview_grid_preferred_over_tables(self):
        # grid_preview wins over tables when both present at top-level preview.
        ea = {
            "preview_data": {
                "grid_preview": {"header_row_index": 5},
                "tables": [{"header_row": 1}],
            }
        }
        assert detected_excel_header_row_1based(ea) == 5

    def test_top_level_preview_tables_hit(self):
        ea = {"preview_data": {"tables": [{"header_row": 3}]}}
        assert detected_excel_header_row_1based(ea) == 3

    def test_sheets_empty_list_returns_none(self):
        ea = {"sheets": []}
        assert detected_excel_header_row_1based(ea) is None

    def test_sheets_first_not_dict_skips(self):
        ea = {"sheets": ["x"]}
        assert detected_excel_header_row_1based(ea) is None


# ─────────────── enrich_excel_tool_arguments ────────────────────


class TestEnrichExcelToolArgs:
    def test_none_context_returns_args_unchanged(self):
        args = {"a": 1}
        out = enrich_excel_tool_arguments("excel_analysis", args, None)
        assert out == {"a": 1}
        # None context returns the SAME object (no copy) per source.
        assert out is args

    def test_wrong_tool_name_returns_args_unchanged(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        args = {"keep": "me"}
        out = enrich_excel_tool_arguments("other_tool", args, ctx)
        assert out == {"keep": "me"}
        assert out is args

    def test_ea_not_dict_returns_copy_of_args(self):
        ctx = {"excel_analysis": "bad"}
        args = {"k": "v"}
        out = enrich_excel_tool_arguments("excel_analysis", args, ctx)
        assert out == {"k": "v"}
        # When ea is not a dict the source still returns a copy, not the original.
        assert out is not args

    def test_fills_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/path/to/x.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out == {"file_path": "/path/to/x.xlsx"}

    def test_fills_file_path_from_preview_data(self):
        ctx = {"excel_analysis": {"preview_data": {"file_path": "/preview/x.xlsx"}}}
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["file_path"] == "/preview/x.xlsx"

    def test_does_not_overwrite_different_basename_file_path(self):
        # Different basename → context path must NOT clobber the caller's path.
        ctx = {"excel_analysis": {"file_path": "/uploads/file_a.xlsx"}}
        out = enrich_excel_tool_arguments(
            "excel_analysis", {"file_path": "/local/file_b.xlsx"}, ctx
        )
        assert out["file_path"] == "/local/file_b.xlsx"

    def test_overrides_when_same_basename(self):
        # Same basename → server path replaces the caller's path.
        ctx = {"excel_analysis": {"file_path": "/server/x.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {"file_path": "/local/x.xlsx"}, ctx)
        assert out["file_path"] == "/server/x.xlsx"

    def test_overrides_when_basename_matches_file_name(self):
        # ctx file_path basename differs from tool path, but ctx file_name matches.
        ctx = {
            "excel_analysis": {
                "file_path": "/server/canonical.xlsx",
                "file_name": "report.xlsx",
            }
        }
        out = enrich_excel_tool_arguments(
            "excel_analysis", {"file_path": "/local/report.xlsx"}, ctx
        )
        assert out["file_path"] == "/server/canonical.xlsx"

    def test_fills_sheet_name_from_selected(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Sheet2"},
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["sheet_name"] == "Sheet2"

    def test_fills_sheet_name_from_preferred(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "preferred_sheet_name": "Pref",
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["sheet_name"] == "Pref"

    def test_selected_sheet_wins_over_preferred(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Selected"},
            "preferred_sheet_name": "Preferred",
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["sheet_name"] == "Selected"

    def test_existing_sheet_name_not_overwritten(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "FromCtx"},
        }
        out = enrich_excel_tool_arguments("excel_analysis", {"sheet_name": "Caller"}, ctx)
        assert out["sheet_name"] == "Caller"

    def test_schema_understand_does_not_fill_sheet_name(self):
        """excel_schema_understand does NOT fill sheet_name (only excel_analysis does)."""
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Sheet2"},
        }
        out = enrich_excel_tool_arguments("excel_schema_understand", {}, ctx)
        assert "sheet_name" not in out
        # but file_path is still filled for excel_schema_understand
        assert out["file_path"] == "/x.xlsx"

    def test_fills_header_from_sheet_context(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "S", "grid_preview": {"header_row_index": 3}}],
            },
            "excel_analysis_selected_sheet": {"sheet_name": "S"},
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out == {"file_path": "/x.xlsx", "sheet_name": "S", "header_row": 3}

    def test_does_not_overwrite_existing_header_row(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            }
        }
        out = enrich_excel_tool_arguments("excel_analysis", {"header_row": 5}, ctx)
        assert out["header_row"] == 5

    def test_does_not_overwrite_existing_header_row_index(self):
        # If header_row_index already provided, detected header_row is NOT added.
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            }
        }
        out = enrich_excel_tool_arguments("excel_analysis", {"header_row_index": 4}, ctx)
        assert "header_row" not in out
        assert out["header_row_index"] == 4

    def test_no_header_when_hdr_is_none(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out == {"file_path": "/x.xlsx"}
        assert "header_row" not in out

    def test_sheet_for_hdr_from_sel2_when_no_sheet_name(self):
        # For excel_schema_understand sheet_name isn't filled, but the selected
        # sheet still drives header detection (sel2 branch).
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "S2", "tables": [{"header_row": 4}]}],
            },
            "excel_analysis_selected_sheet": {"sheet_name": "S2"},
        }
        out = enrich_excel_tool_arguments("excel_schema_understand", {}, ctx)
        assert out.get("header_row") == 4
        assert "sheet_name" not in out


# ─────────────── _excel_analysis_from_runtime ───────────────────


class TestExcelAnalysisFromRuntime:
    def test_none_returns_none(self):
        assert _excel_analysis_from_runtime(None) is None

    def test_empty_returns_none(self):
        assert _excel_analysis_from_runtime({}) is None

    def test_direct_ea_dict_returned_as_same_object(self):
        ea = {"file_path": "/x.xlsx"}
        ctx = {"excel_analysis": ea}
        result = _excel_analysis_from_runtime(ctx)
        assert result == {"file_path": "/x.xlsx"}
        assert result is ea  # returns the live ea object, not a copy

    def test_last_excel_analysis_with_nested(self):
        nested = {"file_path": "/n.xlsx"}
        ctx = {"last_excel_analysis_context": {"excel_analysis": nested}}
        result = _excel_analysis_from_runtime(ctx)
        assert result is nested

    def test_last_excel_analysis_direct_dict(self):
        # last context has no nested excel_analysis → the whole dict is returned.
        last = {"file_path": "/last.xlsx"}
        ctx = {"last_excel_analysis_context": last}
        result = _excel_analysis_from_runtime(ctx)
        assert result is last

    def test_direct_ea_wins_over_last_context(self):
        ctx = {
            "excel_analysis": {"file_path": "/direct.xlsx"},
            "last_excel_analysis_context": {"file_path": "/last.xlsx"},
        }
        assert _excel_analysis_from_runtime(ctx) == {"file_path": "/direct.xlsx"}

    def test_last_excel_analysis_not_dict(self):
        ctx = {"last_excel_analysis_context": "not_a_dict"}
        assert _excel_analysis_from_runtime(ctx) is None


# ─────────────── enrich_template_preview_arguments ──────────────


class TestEnrichTemplatePreviewArgs:
    def test_none_context_returns_copy(self):
        args = {"a": 1}
        out = enrich_template_preview_arguments(args, None)
        assert out == {"a": 1}
        assert out is not args  # always a fresh dict

    def test_no_ea_returns_out_unchanged(self):
        assert enrich_template_preview_arguments({}, {"other": "x"}) == {}

    def test_fills_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/t.xlsx"}}
        out = enrich_template_preview_arguments({}, ctx)
        assert out["file_path"] == "/t.xlsx"

    def test_does_not_overwrite_existing_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/server.xlsx"}}
        out = enrich_template_preview_arguments({"file_path": "/local.xlsx"}, ctx)
        assert out["file_path"] == "/local.xlsx"

    def test_fills_sheet_name_from_selected(self):
        ctx = {
            "excel_analysis": {"file_path": "/t.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Tab1"},
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["sheet_name"] == "Tab1"
        # selected sheet also drives template_name.
        assert out["template_name"] == "Tab1-模板"

    def test_fills_sheet_name_from_preferred(self):
        ctx = {
            "excel_analysis": {"file_path": "/t.xlsx"},
            "preferred_sheet_name": "PrefTab",
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["sheet_name"] == "PrefTab"

    def test_fills_sheet_name_from_ea_sheets(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/t.xlsx",
                "sheets": [{"sheet_name": "FirstSheet"}],
            }
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["sheet_name"] == "FirstSheet"

    def test_ea_sheets_first_not_dict_skips(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/t.xlsx",
                "sheets": ["oops"],
            }
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert "sheet_name" not in out
        assert "template_name" not in out

    def test_fills_header_row(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/t.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            }
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["header_row"] == 2

    def test_does_not_overwrite_existing_header(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/t.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            }
        }
        out = enrich_template_preview_arguments({"header_row": 9}, ctx)
        assert out["header_row"] == 9

    def test_sets_template_name_from_sheet(self):
        ctx = {
            "excel_analysis": {"file_path": "/t.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Orders"},
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["template_name"] == "Orders-模板"

    def test_existing_template_name_not_overwritten(self):
        ctx = {
            "excel_analysis": {"file_path": "/t.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Orders"},
        }
        out = enrich_template_preview_arguments({"template_name": "Custom"}, ctx)
        assert out["template_name"] == "Custom"

    def test_sets_unit_name_from_customer_hint(self):
        ctx = {"excel_analysis": {"file_path": "/t.xlsx", "customer_hint": "ACME Corp"}}
        out = enrich_template_preview_arguments({}, ctx)
        assert out["unit_name"] == "ACME Corp"

    def test_sets_unit_name_from_preview_data_customer_hint(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/t.xlsx",
                "preview_data": {"customer_hint": "Preview Corp"},
            }
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["unit_name"] == "Preview Corp"

    def test_top_level_customer_hint_wins_over_preview(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/t.xlsx",
                "customer_hint": "Top Corp",
                "preview_data": {"customer_hint": "Preview Corp"},
            }
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["unit_name"] == "Top Corp"

    def test_does_not_overwrite_existing_unit_name(self):
        ctx = {"excel_analysis": {"file_path": "/t.xlsx", "customer_hint": "ACME"}}
        out = enrich_template_preview_arguments({"unit_name": "Existing"}, ctx)
        assert out["unit_name"] == "Existing"

    def test_no_customer_hint_no_unit_name(self):
        ctx = {"excel_analysis": {"file_path": "/t.xlsx"}}
        out = enrich_template_preview_arguments({}, ctx)
        assert "unit_name" not in out

    def test_pulls_from_last_excel_analysis_context(self):
        # No top-level excel_analysis → uses last_excel_analysis_context.
        ctx = {
            "last_excel_analysis_context": {
                "file_path": "/last.xlsx",
                "customer_hint": "Last Corp",
            }
        }
        out = enrich_template_preview_arguments({}, ctx)
        assert out["file_path"] == "/last.xlsx"
        assert out["unit_name"] == "Last Corp"


# ─────────────── _sanitize_untrusted_context_line ───────────────


class TestSanitize:
    def test_removes_control_chars(self):
        out = _sanitize_untrusted_context_line("a\x00\x01\x08b", 100)
        # control bytes stripped, printable text preserved verbatim & contiguous.
        assert out == "ab"

    def test_collapses_triple_newlines_to_double(self):
        out = _sanitize_untrusted_context_line("a\n\n\n\nb", 100)
        assert out == "a\n\nb"

    def test_truncates_with_ellipsis(self):
        out = _sanitize_untrusted_context_line("x" * 20, 10)
        assert out == "x" * 10 + "…"
        assert len(out) == 11

    def test_no_truncation_at_exact_max_len(self):
        # len == max_len is not > max_len → no ellipsis appended.
        out = _sanitize_untrusted_context_line("y" * 10, 10)
        assert out == "y" * 10

    def test_keeps_short_strings_unchanged(self):
        assert _sanitize_untrusted_context_line("hello", 100) == "hello"

    def test_crlf_normalized_to_lf(self):
        assert _sanitize_untrusted_context_line("a\r\nb", 100) == "a\nb"

    def test_lone_cr_normalized_to_lf(self):
        assert _sanitize_untrusted_context_line("a\rb", 100) == "a\nb"

    def test_leading_trailing_whitespace_stripped(self):
        assert _sanitize_untrusted_context_line("  spaced  ", 100) == "spaced"

    def test_none_input_becomes_empty(self):
        assert _sanitize_untrusted_context_line(None, 100) == ""


# ─────────────── format_recent_messages_excerpt_for_llm ─────────


class TestFormatRecentMessages:
    def test_none_returns_none(self):
        assert format_recent_messages_excerpt_for_llm(None) is None

    def test_no_recent_messages_key(self):
        assert format_recent_messages_excerpt_for_llm({"other": 1}) is None

    def test_empty_list(self):
        assert format_recent_messages_excerpt_for_llm({"recent_messages": []}) is None

    def test_non_list_value(self):
        assert format_recent_messages_excerpt_for_llm({"recent_messages": "x"}) is None

    def test_all_non_dict_entries_yields_header_only_so_none(self):
        # No dict messages → only the header line survives → returns None.
        assert format_recent_messages_excerpt_for_llm({"recent_messages": [1, "x"]}) is None

    def test_empty_content_skipped(self):
        ctx = {"recent_messages": [{"role": "user", "content": ""}]}
        assert format_recent_messages_excerpt_for_llm(ctx) is None

    def test_builds_valid_excerpt_exact(self):
        ctx = {
            "recent_messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        }
        out = format_recent_messages_excerpt_for_llm(ctx)
        assert out == "【近期对话摘要】\n- [user] hi\n- [assistant] hello"

    def test_role_defaults_to_user_when_missing(self):
        ctx = {"recent_messages": [{"content": "anon"}]}
        out = format_recent_messages_excerpt_for_llm(ctx)
        assert out == "【近期对话摘要】\n- [user] anon"

    def test_only_last_six_messages_included(self):
        ctx = {"recent_messages": [{"role": "user", "content": f"msg{i}"} for i in range(10)]}
        out = format_recent_messages_excerpt_for_llm(ctx)
        # msg0..msg3 dropped; msg4..msg9 kept in order.
        for dropped in ("msg0", "msg1", "msg2", "msg3"):
            assert f"[user] {dropped}" not in out
        body = out.splitlines()[1:]
        assert body == [f"- [user] msg{i}" for i in range(4, 10)]

    def test_content_sanitized_in_excerpt(self):
        ctx = {"recent_messages": [{"role": "user", "content": "a\x00\x01b"}]}
        out = format_recent_messages_excerpt_for_llm(ctx)
        assert out == "【近期对话摘要】\n- [user] ab"


# ─────────────── format_runtime_context_for_llm ─────────────────


class TestFormatRuntimeContextForLlm:
    def test_none_returns_none(self):
        assert format_runtime_context_for_llm(None) is None

    def test_no_signals_returns_none(self):
        # Only the header line would be produced → returns None.
        assert format_runtime_context_for_llm({"unrelated": 1}) is None

    def test_excel_file_path_top_level(self):
        ctx = {"excel_file_path": "/top.xlsx"}
        out = format_runtime_context_for_llm(ctx)
        assert "- excel_file_path: /top.xlsx" in out
        assert out.startswith("【当前对话运行时上下文】")

    def test_excel_analysis_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/ea.xlsx"}}
        out = format_runtime_context_for_llm(ctx)
        assert "- excel_file_path: /ea.xlsx" in out

    def test_top_level_excel_file_path_wins_over_analysis(self):
        ctx = {
            "excel_file_path": "/top.xlsx",
            "excel_analysis": {"file_path": "/ea.xlsx"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- excel_file_path: /top.xlsx" in out
        assert "/ea.xlsx" not in out

    def test_select_all_sheets_branch_lists_names_and_count(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": [
                {"sheet_name": "S1"},
                {"sheet_name": "S2"},
            ],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- 用户当前选择：全部工作表（2 个）: S1, S2" in out
        # the per-sheet read instruction line appears in this branch.
        assert "逐表读取并汇总" in out

    def test_select_all_sheets_with_non_dict_items_skipped_in_count(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": ["oops", {"sheet_name": "S1"}],
        }
        out = format_runtime_context_for_llm(ctx)
        # only the one valid sheet counts.
        assert "全部工作表（1 个）: S1" in out

    def test_single_sheet_name_from_selected(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Sheet1"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- 用户当前选中的工作表: Sheet1" in out
        assert '"sheet_name": "Sheet1"' in out

    def test_sheet_name_from_preferred(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "preferred_sheet_name": "Pref",
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- 用户当前选中的工作表: Pref" in out

    def test_fallback_call_example_when_no_sheet(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = format_runtime_context_for_llm(ctx)
        assert '- 调用示例: {"file_path": "/x.xlsx", "action": "read"}' in out
        # without a sheet there is no "选中的工作表" line.
        assert "选中的工作表" not in out

    def test_linked_grid_preview_rendered(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": "row1\nrow2"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- 关联工作表真实网格预览（来自前端 linked-grid-preview）:" in out
        assert "row1\nrow2" in out

    def test_linked_grid_preview_empty_text_skipped(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": ""},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "linked-grid-preview" not in out

    def test_linked_grid_previews_list_count_and_text(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_previews": [
                {"preview_text": "preview content"},
                {"preview_text": ""},
            ],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- 已提供多工作表真实网格预览: 2 份" in out
        assert "  - 预览1: preview content" in out
        # the second (empty) preview produces no 预览2 line.
        assert "预览2" not in out

    def test_linked_grid_previews_non_dict_skipped(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_previews": ["oops", {"preview_text": "ok"}],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- 已提供多工作表真实网格预览: 2 份" in out
        assert "  - 预览2: ok" in out

    def test_chat_db_write_authorized_branch(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "chat_db_write_authorized": True,
        }
        out = format_runtime_context_for_llm(ctx)
        assert "【写入授权】" in out
        # the un-authorized alternative must NOT appear.
        assert "若工具返回 requires_token" not in out

    def test_no_write_authorized_alternative_branch(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = format_runtime_context_for_llm(ctx)
        assert "若工具返回 requires_token" in out
        assert "【写入授权】" not in out

    def test_excel_customer_hint_added(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_customer_hint": "CustomerCo",
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- excel_customer_hint（作 unit_name / 客户）: CustomerCo" in out

    def test_excel_customer_hint_only_with_file_path(self):
        # customer hint line lives inside the fp_single block — no fp → no line.
        ctx = {"excel_customer_hint": "CustomerCo", "ai_tier": "x"}
        out = format_runtime_context_for_llm(ctx)
        assert "CustomerCo" not in out

    def test_db_write_stream_resume_appends_resume_text(self):
        ctx = {"db_write_stream_resume": "previous output"}
        out = format_runtime_context_for_llm(ctx)
        assert "【同一轮对话续跑】" in out
        assert "previous output" in out

    def test_db_write_stream_resume_blank_skipped(self):
        ctx = {"db_write_stream_resume": "   ", "ai_tier": "x"}
        out = format_runtime_context_for_llm(ctx)
        assert "续跑" not in out

    def test_excel_file_paths_list_joins_nonblank(self):
        ctx = {"excel_file_paths": ["/a.xlsx", "/b.xlsx", ""]}
        out = format_runtime_context_for_llm(ctx)
        assert "- excel_file_paths: /a.xlsx, /b.xlsx" in out

    def test_excel_file_paths_all_blank_no_line(self):
        ctx = {"excel_file_paths": ["", "   "], "ai_tier": "x"}
        out = format_runtime_context_for_llm(ctx)
        assert "excel_file_paths" not in out

    def test_ai_tier_line(self):
        ctx = {"ai_tier": "premium"}
        out = format_runtime_context_for_llm(ctx)
        assert "- ai_tier: premium" in out

    def test_ai_tier_blank_string_no_line_returns_none(self):
        # blank tier is the only signal and produces no line → None overall.
        assert format_runtime_context_for_llm({"ai_tier": "   "}) is None

    def test_ea0_header_row_added_with_example(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 3}},
            }
        }
        out = format_runtime_context_for_llm(ctx)
        assert "- extract-grid 检测到的表头行（Excel 行号，从 1 开始）: 3" in out
        # example line omits empty sheet_name and carries header_row 3.
        assert '"header_row": 3' in out
        assert '"sheet_name": ""' not in out

    def test_recent_messages_appended_to_runtime_block(self):
        ctx = {
            "ai_tier": "std",
            "recent_messages": [{"role": "user", "content": "ping"}],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "【近期对话摘要】" in out
        assert "- [user] ping" in out

    def test_kitten_block_appended(self):
        ctx = {"ai_tier": "std", "kitten_analyzer": True}
        out = format_runtime_context_for_llm(ctx)
        assert "【小猫分析 · 角色】" in out


# ─────────────── _format_kitten_runtime_for_llm ─────────────────


class TestFormatKittenRuntime:
    def test_none_returns_none(self):
        assert _format_kitten_runtime_for_llm(None) is None

    def test_no_kitten_analyzer_key(self):
        assert _format_kitten_runtime_for_llm({"other": 1}) is None

    def test_kitten_analyzer_false(self):
        assert _format_kitten_runtime_for_llm({"kitten_analyzer": False}) is None

    def test_basic_kitten_no_dataset(self):
        ctx = {"kitten_analyzer": True}
        out = _format_kitten_runtime_for_llm(ctx)
        assert out.startswith("【小猫分析 · 角色】")
        assert "- 当前未在上下文中附带解析后的表格摘要；可结合用户描述与工具回答。" in out
        # no dataset → no 数据文件 line.
        assert "数据文件" not in out

    def test_kitten_dataset_with_fields_lists_each(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {
                "file_name": "data.csv",
                "rows": 100,
                "columns": 5,
                "fields": ["col1", "col2", "col3"],
            },
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 数据文件: data.csv" in out
        assert "- 行数: 100" in out
        assert "- 列数: 5" in out
        assert "- 字段: col1, col2, col3" in out
        # no truncation marker for short field list.
        assert "字段已截断" not in out

    def test_kitten_dataset_file_name_falls_back_to_name(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {"name": "fallback.csv"},
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 数据文件: fallback.csv" in out

    def test_kitten_dataset_rows_zero_still_rendered(self):
        # rows is not None (0) → line appears (guard is `is not None`, not truthiness).
        ctx = {"kitten_analyzer": True, "kitten_dataset": {"rows": 0}}
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 行数: 0" in out

    def test_kitten_dataset_with_preview(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {
                "file_name": "d.csv",
                "preview_text": "col1,col2\n1,2",
            },
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 样本预览:" in out
        assert "col1,col2\n1,2" in out

    def test_kitten_dataset_fields_truncated_at_sixty(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {"fields": [f"col{i}" for i in range(65)]},
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- …（字段已截断）" in out
        # only the first 60 fields are listed.
        assert "col59" in out
        assert "col60" not in out

    def test_kitten_business_snapshot(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_business_snapshot": {"text": "snapshot data"},
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 业务库快照:" in out
        assert "snapshot data" in out

    def test_kitten_business_snapshot_blank_text_skipped(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_business_snapshot": {"text": "   "},
        }
        out = _format_kitten_runtime_for_llm(ctx)
        # The label line "- 业务库快照:" must be absent (note: the phrase
        # "业务库快照" also appears in the static role header, so we match the
        # specific label line, not the bare substring).
        assert "- 业务库快照:" not in out

    def test_kitten_web_search_with_results(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_meta": {"provider": "bing", "query": "test"},
            "web_search_results": [
                {
                    "title": "Result 1",
                    "url": "http://example.com",
                    "snippet": "snippet text",
                },
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 联网检索: provider=bing query=test" in out
        assert "  1. Result 1 | http://example.com" in out
        assert "     snippet text" in out

    def test_kitten_web_search_title_falls_back_to_url(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": [
                {"title": "", "url": "http://only-url.com", "snippet": ""},
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "  1. http://only-url.com | http://only-url.com" in out

    def test_kitten_web_search_with_error(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_error": "no results",
            "web_search_results": [],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "- 联网检索未返回结果: no results" in out

    def test_kitten_web_search_error_suppressed_when_results_present(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_error": "partial failure",
            "web_search_results": [
                {"title": "T", "url": "http://u.com", "snippet": "s"},
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "未返回结果" not in out

    def test_kitten_web_search_no_meta_no_query_no_search_line(self):
        ctx = {"kitten_analyzer": True, "kitten_web_search": True}
        out = _format_kitten_runtime_for_llm(ctx)
        # web search enabled but nothing to report → no 联网检索 provider line.
        assert "联网检索: provider" not in out
        # still a valid kitten block (role header present).
        assert out.startswith("【小猫分析 · 角色】")

    def test_kitten_web_search_result_non_dict_skipped(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": [
                "oops",
                {"title": "Real", "url": "http://r.com", "snippet": "s"},
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        # enumerate(start=1) advances over the skipped non-dict, so the real
        # hit keeps its original list position (index 2), leaving no "1." line.
        assert "  2. Real | http://r.com" in out
        assert "  1. " not in out
        assert "oops" not in out

    def test_kitten_web_search_long_snippet_truncated_at_450(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": [
                {"title": "T", "url": "http://u.com", "snippet": "x" * 500},
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "x" * 450 + "…" in out
        assert "x" * 451 not in out


# ─────────────── format_excel_analysis_for_llm ──────────────────


class TestFormatExcelAnalysisForLlm:
    def test_none_returns_none(self):
        assert format_excel_analysis_for_llm(None) is None

    def test_no_ea_returns_none(self):
        assert format_excel_analysis_for_llm({"other": 1}) is None

    def test_ea_not_dict(self):
        assert format_excel_analysis_for_llm({"excel_analysis": "bad"}) is None

    def test_basic_with_file_name(self):
        ctx = {"excel_analysis": {"file_name": "test.xlsx"}}
        out = format_excel_analysis_for_llm(ctx)
        assert out.startswith("【Excel 分析摘要")
        assert "- 文件: test.xlsx" in out

    def test_file_name_falls_back_to_excel_file_path(self):
        ctx = {"excel_analysis": {}, "excel_file_path": "/ctx/path.xlsx"}
        out = format_excel_analysis_for_llm(ctx)
        assert "- 文件: /ctx/path.xlsx" in out

    def test_file_path_from_ea(self):
        ctx = {"excel_analysis": {"file_path": "/server/data.xlsx"}}
        out = format_excel_analysis_for_llm(ctx)
        assert "- 服务端保存路径 file_path（调用工具时使用）: /server/data.xlsx" in out

    def test_file_path_from_preview_data(self):
        ctx = {"excel_analysis": {"preview_data": {"file_path": "/preview/data.xlsx"}}}
        out = format_excel_analysis_for_llm(ctx)
        assert "/preview/data.xlsx" in out

    def test_header_row_from_selected_sheet(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "S", "grid_preview": {"header_row_index": 3}}],
            },
            "excel_analysis_selected_sheet": {"sheet_name": "S"},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "- 检测到的表头行 header_row（1-based，须传给 excel_analysis）: 3" in out

    def test_header_row_from_preferred_sheet_name(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "P", "grid_preview": {"header_row_index": 4}}],
            },
            "preferred_sheet_name": "P",
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "- 检测到的表头行 header_row（1-based，须传给 excel_analysis）: 4" in out

    def test_select_all_sheets_lists_names(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": [
                {"sheet_name": "Tab1"},
                {"sheet_name": "Tab2"},
            ],
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "- 前端已关联全部工作表（2 个）: Tab1, Tab2" in out

    def test_summary_included_sanitized(self):
        ctx = {"excel_analysis": {"summary": "This is a\x00 summary"}}
        out = format_excel_analysis_for_llm(ctx)
        assert "- 摘要: This is a summary" in out

    def test_customer_hint_from_ea(self):
        ctx = {"excel_analysis": {"customer_hint": "Acme Inc"}}
        out = format_excel_analysis_for_llm(ctx)
        assert "Acme Inc" in out
        # the follow-up guidance line about not re-asking the company name fires.
        assert "请勿在回复中要求用户再次提供同一公司名称" in out

    def test_customer_hint_from_preview_data(self):
        ctx = {"excel_analysis": {"preview_data": {"customer_hint": "Beta Corp"}}}
        out = format_excel_analysis_for_llm(ctx)
        assert "Beta Corp" in out

    def test_fields_label_and_name_used_empty_skipped(self):
        ctx = {
            "excel_analysis": {
                "fields": [
                    {"label": "Name"},
                    {"name": "Age"},
                    {},  # empty → skipped
                ]
            }
        }
        out = format_excel_analysis_for_llm(ctx)
        # label preferred over name, empty dict produces no extra entry.
        assert "- 字段: Name, Age" in out

    def test_preview_data_sheet_names_and_sample_rows(self):
        ctx = {
            "excel_analysis": {
                "preview_data": {
                    "sheet_names": ["Sheet1", "Sheet2"],
                    "sample_rows": [{"col": "val"}],
                }
            }
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "- 工作表: Sheet1, Sheet2" in out
        # sample rows serialized as compact JSON with non-ASCII preserved.
        assert '- 样例行: [{"col": "val"}]' in out

    def test_linked_grid_preview_text(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": "preview data"},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "- 关联工作表真实网格预览: preview data" in out

    def test_linked_grid_preview_empty_text_skipped(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": ""},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "关联工作表真实网格预览" not in out

    def test_trailing_tool_reminder_always_present(self):
        ctx = {"excel_analysis": {"file_name": "x.xlsx"}}
        out = format_excel_analysis_for_llm(ctx)
        assert out.rstrip().endswith("请调用 excel_analysis 工具。")


# ─────────────── merge_system_prompt ────────────────────────────


class TestMergeSystemPrompt:
    def test_none_context_no_base(self):
        assert merge_system_prompt(None, None) is None

    def test_base_only(self):
        assert merge_system_prompt("You are an assistant.", None) == "You are an assistant."

    def test_base_only_stripped(self):
        assert merge_system_prompt("  spaced base  ", None) == "spaced base"

    def test_context_only_wraps_untrusted_block(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt(None, ctx)
        assert out.startswith("【运行时上下文（不可信数据）】")
        assert "<xcagi_untrusted_runtime>" in out
        assert "</xcagi_untrusted_runtime>" in out
        assert "- excel_file_path: /x.xlsx" in out

    def test_base_plus_context_order(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt("Base prompt.", ctx)
        # base comes first, then the untrusted runtime block.
        assert out.startswith("Base prompt.")
        idx_base = out.index("Base prompt.")
        idx_block = out.index("【运行时上下文（不可信数据）】")
        assert idx_base < idx_block

    def test_empty_base_yields_only_context_block(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt("", ctx)
        assert out.startswith("【运行时上下文（不可信数据）】")

    def test_include_products_context_false_no_effect_on_output(self):
        # The flag is currently a no-op in source; output matches the default.
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        with_flag = merge_system_prompt("Base.", ctx, include_products_context=False)
        without_flag = merge_system_prompt("Base.", ctx, include_products_context=True)
        assert with_flag == without_flag

    def test_no_signals_returns_base_unchanged(self):
        out = merge_system_prompt("Base.", {"only_unrelated": True})
        assert out == "Base."

    def test_all_empty_returns_none(self):
        assert merge_system_prompt("", {}) is None

    def test_both_runtime_and_excel_summary_joined(self):
        # excel_analysis with a summary feeds BOTH format_runtime_context_for_llm
        # and format_excel_analysis_for_llm → both summaries present in one block.
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx", "summary": "the summary"},
        }
        out = merge_system_prompt(None, ctx)
        assert "- excel_file_path: /x.xlsx" in out
        assert "- 摘要: the summary" in out


# ─────────────── planner_workflow_interrupt_reply ────────────────


class TestPlannerWorkflowInterruptReply:
    EXPECTED = "已中断当前流程。你可以继续提问新的任务。"

    def test_pause_message(self):
        assert planner_workflow_interrupt_reply("暂停流程") == self.EXPECTED

    def test_interrupt_message(self):
        assert planner_workflow_interrupt_reply("中断流程") == self.EXPECTED

    def test_stop_message(self):
        assert planner_workflow_interrupt_reply("停止流程") == self.EXPECTED

    def test_cancel_message(self):
        assert planner_workflow_interrupt_reply("取消流程") == self.EXPECTED

    def test_slash_interrupt(self):
        assert planner_workflow_interrupt_reply("/interrupt") == self.EXPECTED

    def test_slash_interrupt_case_insensitive_and_trimmed(self):
        # source lowercases + strips before matching the trigger set.
        assert planner_workflow_interrupt_reply("  /INTERRUPT  ") == self.EXPECTED

    def test_other_message_returns_none(self):
        assert planner_workflow_interrupt_reply("something else") is None

    def test_partial_match_not_triggered(self):
        # "请暂停流程" is not an exact member of the trigger set → None.
        assert planner_workflow_interrupt_reply("请暂停流程") is None

    def test_none_returns_none(self):
        assert planner_workflow_interrupt_reply(None) is None

    def test_empty_returns_none(self):
        assert planner_workflow_interrupt_reply("") is None


# ─────────────── runtime_context_after_workflow_interrupt ────────


class TestRuntimeContextAfterWorkflowInterrupt:
    def test_none_returns_empty(self):
        assert runtime_context_after_workflow_interrupt(None) == {}

    def test_removes_workflow_state(self):
        ctx = {"workflow_state": {"step": 1}, "other": "val"}
        out = runtime_context_after_workflow_interrupt(ctx)
        assert out == {"other": "val"}

    def test_no_workflow_state_passes_through(self):
        ctx = {"key": "value"}
        out = runtime_context_after_workflow_interrupt(ctx)
        assert out == {"key": "value"}

    def test_does_not_mutate_original(self):
        ctx = {"workflow_state": "x", "k": "v"}
        out = runtime_context_after_workflow_interrupt(ctx)
        assert ctx == {"workflow_state": "x", "k": "v"}  # original untouched
        assert out == {"k": "v"}
        assert out is not ctx
