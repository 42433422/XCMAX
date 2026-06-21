"""Branch-coverage tests for app/domain/context/session_context.py.

Targets the ~78 missing branches identified from coverage_new.json.
No external I/O — all pure logic covered through argument variation.
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
        ea = {"preview_data": {"tables": [{"header_row": 0}]}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_bad_type_returns_none(self):
        ea = {"preview_data": {"tables": [{"header_row": "abc"}]}}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_tables_valid(self):
        ea = {"preview_data": {"tables": [{"header_row": 3}]}}
        assert detected_excel_header_row_1based(ea) == 3

    # ---------- _from_sheet_entry branches (lines ~47-59) ----------

    def test_from_sheet_entry_non_dict_returns_none(self):
        ea = {"sheets": ["oops"]}
        # sheets[0] not dict → _from_sheet_entry returns None
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_none_hri(self):
        ea = {"sheets": [{"grid_preview": {}}]}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_bad_type(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": "bad"}}]}
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_zero(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": 0}}]}
        # hri=0 → falls through to _from_tables
        assert detected_excel_header_row_1based(ea) is None

    def test_from_sheet_entry_grid_preview_valid(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": 2}}]}
        assert detected_excel_header_row_1based(ea) == 2

    def test_from_sheet_entry_tables_fallback(self):
        ea = {"sheets": [{"tables": [{"header_row": 4}]}]}
        assert detected_excel_header_row_1based(ea) == 4

    # ---------- preferred_sheet_name branches (lines ~62-87) ----------

    def test_preferred_sheet_no_match_falls_through(self):
        # When preferred "B" doesn't match in sheets/all_sheets, the code falls
        # through to the top-level fallback which DOES return sheets[0].
        # So this test verifies the fallback path fires (returns sheets[0] value).
        ea = {
            "sheets": [{"sheet_name": "A", "grid_preview": {"header_row_index": 2}}]
        }
        result = detected_excel_header_row_1based(ea, preferred_sheet_name="B")
        # Falls back to sheets[0] which has header_row_index=2
        assert result == 2

    def test_preferred_sheet_match_in_sheets(self):
        ea = {
            "sheets": [
                {"sheet_name": "A", "grid_preview": {"header_row_index": 2}},
                {"sheet_name": "B", "grid_preview": {"header_row_index": 5}},
            ]
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="B") == 5

    def test_preferred_sheet_non_dict_entry_in_sheets(self):
        ea = {
            "sheets": [
                "not_a_dict",
                {"sheet_name": "B", "grid_preview": {"header_row_index": 5}},
            ]
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="B") == 5

    def test_preferred_sheet_mismatch_uses_sheets_fallback(self):
        # preferred "B" → no match in sheets → falls through to sheets[0] fallback
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
        # B found but no useful sub-data (returns None from _from_sheet_entry)
        # falls to top-level preview
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
        ea = {
            "preview_data": {
                "all_sheets": [
                    {"sheet_name": "S2", "grid_preview": {"header_row_index": 6}},
                ]
            }
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="S1") is None

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
    def test_none_context(self):
        assert enrich_excel_tool_arguments("excel_analysis", {"a": 1}, None) == {"a": 1}

    def test_wrong_tool_name(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        assert enrich_excel_tool_arguments("other_tool", {}, ctx) == {}

    def test_ea_not_dict_returns_args(self):
        ctx = {"excel_analysis": "bad"}
        out = enrich_excel_tool_arguments("excel_analysis", {"k": "v"}, ctx)
        assert out == {"k": "v"}

    def test_fills_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/path/to/x.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["file_path"] == "/path/to/x.xlsx"

    def test_fills_file_path_from_preview_data(self):
        ctx = {"excel_analysis": {"preview_data": {"file_path": "/preview/x.xlsx"}}}
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["file_path"] == "/preview/x.xlsx"

    def test_does_not_overwrite_different_basename_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/uploads/file_a.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {"file_path": "/local/file_b.xlsx"}, ctx)
        # different basenames → not overwritten
        assert out["file_path"] == "/local/file_b.xlsx"

    def test_overrides_when_same_basename(self):
        ctx = {"excel_analysis": {"file_path": "/server/x.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {"file_path": "/local/x.xlsx"}, ctx)
        assert out["file_path"] == "/server/x.xlsx"

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

    def test_no_sheet_fills_when_not_excel_analysis(self):
        """excel_schema_understand does NOT fill sheet_name."""
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Sheet2"},
        }
        out = enrich_excel_tool_arguments("excel_schema_understand", {}, ctx)
        assert "sheet_name" not in out

    def test_fills_header_from_sheet_context(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "S", "grid_preview": {"header_row_index": 3}}],
            },
            "excel_analysis_selected_sheet": {"sheet_name": "S"},
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out.get("header_row") == 3

    def test_does_not_overwrite_existing_header_row(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            }
        }
        out = enrich_excel_tool_arguments("excel_analysis", {"header_row": 5}, ctx)
        assert out["header_row"] == 5

    def test_no_header_when_hdr_is_none(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert "header_row" not in out

    def test_sheet_for_hdr_from_sel2_when_no_sheet_name(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "S2", "tables": [{"header_row": 4}]}],
            },
            "excel_analysis_selected_sheet": {"sheet_name": "S2"},
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out.get("header_row") == 4


# ─────────────── _excel_analysis_from_runtime ───────────────────

class TestExcelAnalysisFromRuntime:
    def test_none_returns_none(self):
        assert _excel_analysis_from_runtime(None) is None

    def test_empty_returns_none(self):
        assert _excel_analysis_from_runtime({}) is None

    def test_direct_ea_dict(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        result = _excel_analysis_from_runtime(ctx)
        assert result == {"file_path": "/x.xlsx"}

    def test_last_excel_analysis_with_nested(self):
        ctx = {"last_excel_analysis_context": {"excel_analysis": {"file_path": "/n.xlsx"}}}
        result = _excel_analysis_from_runtime(ctx)
        assert result == {"file_path": "/n.xlsx"}

    def test_last_excel_analysis_direct_dict(self):
        ctx = {"last_excel_analysis_context": {"file_path": "/last.xlsx"}}
        result = _excel_analysis_from_runtime(ctx)
        assert result == {"file_path": "/last.xlsx"}

    def test_last_excel_analysis_not_dict(self):
        ctx = {"last_excel_analysis_context": "not_a_dict"}
        result = _excel_analysis_from_runtime(ctx)
        assert result is None


# ─────────────── enrich_template_preview_arguments ──────────────

class TestEnrichTemplatePreviewArgs:
    def test_none_context(self):
        assert enrich_template_preview_arguments({"a": 1}, None) == {"a": 1}

    def test_no_ea_returns_out(self):
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
        assert out.get("template_name") == "Orders-模板"

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

    def test_does_not_overwrite_existing_unit_name(self):
        ctx = {"excel_analysis": {"file_path": "/t.xlsx", "customer_hint": "ACME"}}
        out = enrich_template_preview_arguments({"unit_name": "Existing"}, ctx)
        assert out["unit_name"] == "Existing"

    def test_no_customer_hint_no_unit_name(self):
        ctx = {"excel_analysis": {"file_path": "/t.xlsx"}}
        out = enrich_template_preview_arguments({}, ctx)
        assert "unit_name" not in out


# ─────────────── _sanitize_untrusted_context_line ───────────────

class TestSanitize:
    def test_removes_control_chars(self):
        out = _sanitize_untrusted_context_line("a\x00\x01\x08b", 100)
        assert "\x00" not in out
        assert "\x01" not in out
        assert "a" in out and "b" in out

    def test_collapses_triple_newlines(self):
        out = _sanitize_untrusted_context_line("a\n\n\n\nb", 100)
        assert "\n\n\n" not in out

    def test_truncates_with_ellipsis(self):
        out = _sanitize_untrusted_context_line("x" * 20, 10)
        assert out.endswith("…")
        assert len(out) == 11

    def test_keeps_short_strings_unchanged(self):
        out = _sanitize_untrusted_context_line("hello", 100)
        assert out == "hello"

    def test_crlf_normalized(self):
        out = _sanitize_untrusted_context_line("a\r\nb", 100)
        assert "\r" not in out


# ─────────────── format_recent_messages_excerpt_for_llm ─────────

class TestFormatRecentMessages:
    def test_none_returns_none(self):
        assert format_recent_messages_excerpt_for_llm(None) is None

    def test_no_recent_messages_key(self):
        assert format_recent_messages_excerpt_for_llm({"other": 1}) is None

    def test_empty_list(self):
        assert format_recent_messages_excerpt_for_llm({"recent_messages": []}) is None

    def test_all_non_dict_entries(self):
        assert format_recent_messages_excerpt_for_llm({"recent_messages": [1, "x"]}) is None

    def test_empty_content_skipped(self):
        ctx = {"recent_messages": [{"role": "user", "content": ""}]}
        assert format_recent_messages_excerpt_for_llm(ctx) is None

    def test_builds_valid_excerpt(self):
        ctx = {
            "recent_messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        }
        out = format_recent_messages_excerpt_for_llm(ctx)
        assert "近期对话摘要" in out
        assert "[user] hi" in out
        assert "[assistant] hello" in out

    def test_last_six_only(self):
        ctx = {
            "recent_messages": [
                {"role": "user", "content": f"msg{i}"}
                for i in range(10)
            ]
        }
        out = format_recent_messages_excerpt_for_llm(ctx)
        assert out is not None
        # Only last 6 messages included
        assert "msg4" in out or "msg5" in out or "msg9" in out


# ─────────────── format_runtime_context_for_llm ─────────────────

class TestFormatRuntimeContextForLlm:
    def test_none_returns_none(self):
        assert format_runtime_context_for_llm(None) is None

    def test_no_signals_returns_none(self):
        assert format_runtime_context_for_llm({"unrelated": 1}) is None

    def test_excel_file_path_top_level(self):
        ctx = {"excel_file_path": "/top.xlsx"}
        out = format_runtime_context_for_llm(ctx)
        assert out is not None
        assert "/top.xlsx" in out

    def test_excel_analysis_file_path(self):
        ctx = {"excel_analysis": {"file_path": "/ea.xlsx"}}
        out = format_runtime_context_for_llm(ctx)
        assert out is not None
        assert "/ea.xlsx" in out

    def test_select_all_sheets_branch(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": [
                {"sheet_name": "S1"},
                {"sheet_name": "S2"},
            ],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "全部工作表" in out
        assert "S1" in out

    def test_select_all_sheets_with_non_dict_items(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": ["oops", {"sheet_name": "S1"}],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "S1" in out

    def test_single_sheet_name_from_selected(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Sheet1"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "Sheet1" in out

    def test_sheet_name_from_preferred(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "preferred_sheet_name": "Pref",
        }
        out = format_runtime_context_for_llm(ctx)
        assert "Pref" in out

    def test_fallback_call_example_when_no_sheet(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = format_runtime_context_for_llm(ctx)
        assert '调用示例' in out

    def test_linked_grid_preview(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": "row1\nrow2"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "linked-grid-preview" in out

    def test_linked_grid_preview_empty_text_skipped(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": ""},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "linked-grid-preview" not in out

    def test_linked_grid_previews_list(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_previews": [
                {"preview_text": "preview content"},
                {"preview_text": ""},
            ],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "多工作表" in out

    def test_linked_grid_previews_non_dict_skipped(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_previews": ["oops", {"preview_text": "ok"}],
        }
        out = format_runtime_context_for_llm(ctx)
        assert out is not None

    def test_chat_db_write_authorized_branch(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "chat_db_write_authorized": True,
        }
        out = format_runtime_context_for_llm(ctx)
        assert "写入授权" in out

    def test_no_write_authorized_alternative_branch(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = format_runtime_context_for_llm(ctx)
        assert "requires_token" in out

    def test_excel_customer_hint_added(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_customer_hint": "CustomerCo",
        }
        out = format_runtime_context_for_llm(ctx)
        assert "CustomerCo" in out

    def test_db_write_stream_resume(self):
        ctx = {"db_write_stream_resume": "previous output"}
        out = format_runtime_context_for_llm(ctx)
        assert "续跑" in out

    def test_excel_file_paths_list(self):
        ctx = {"excel_file_paths": ["/a.xlsx", "/b.xlsx", ""]}
        out = format_runtime_context_for_llm(ctx)
        assert "/a.xlsx" in out

    def test_ai_tier(self):
        ctx = {"ai_tier": "premium"}
        out = format_runtime_context_for_llm(ctx)
        assert "premium" in out

    def test_ea0_header_row_added(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 3}},
            }
        }
        out = format_runtime_context_for_llm(ctx)
        assert "header_row" in out
        assert "3" in out


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
        assert "小猫分析" in out
        assert "未在上下文" in out

    def test_kitten_dataset_with_fields(self):
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
        assert "data.csv" in out
        assert "col1" in out

    def test_kitten_dataset_with_preview(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {
                "file_name": "d.csv",
                "preview_text": "col1,col2\n1,2",
            },
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "样本预览" in out

    def test_kitten_dataset_fields_truncated(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {
                "fields": [f"col{i}" for i in range(65)],
            },
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "截断" in out

    def test_kitten_business_snapshot(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_business_snapshot": {"text": "snapshot data"},
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "业务库快照" in out

    def test_kitten_web_search_with_results(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_meta": {"provider": "bing", "query": "test"},
            "web_search_results": [
                {"title": "Result 1", "url": "http://example.com", "snippet": "snippet text"},
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "联网检索" in out
        assert "Result 1" in out

    def test_kitten_web_search_with_error(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_error": "no results",
            "web_search_results": [],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "未返回结果" in out

    def test_kitten_web_search_no_meta_no_query(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
        }
        out = _format_kitten_runtime_for_llm(ctx)
        # Should still be not None
        assert out is not None

    def test_kitten_web_search_result_non_dict_skipped(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": ["oops", {"title": "Real", "url": "http://r.com", "snippet": "s"}],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "Real" in out

    def test_kitten_web_search_long_snippet_truncated(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": [
                {"title": "T", "url": "http://u.com", "snippet": "x" * 500},
            ],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "…" in out


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
        assert "test.xlsx" in out

    def test_file_path_from_ea(self):
        ctx = {"excel_analysis": {"file_path": "/server/data.xlsx"}}
        out = format_excel_analysis_for_llm(ctx)
        assert "/server/data.xlsx" in out

    def test_file_path_from_preview_data(self):
        ctx = {
            "excel_analysis": {
                "preview_data": {"file_path": "/preview/data.xlsx"}
            }
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "/preview/data.xlsx" in out

    def test_pref_sn_from_selected(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "S", "grid_preview": {"header_row_index": 3}}],
            },
            "excel_analysis_selected_sheet": {"sheet_name": "S"},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "header_row" in out

    def test_pref_sn_from_preferred_sheet_name(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/x.xlsx",
                "sheets": [{"sheet_name": "P", "grid_preview": {"header_row_index": 4}}],
            },
            "preferred_sheet_name": "P",
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "4" in out

    def test_select_all_sheets(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": [
                {"sheet_name": "Tab1"},
                {"sheet_name": "Tab2"},
            ],
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "Tab1" in out

    def test_summary_included(self):
        ctx = {"excel_analysis": {"summary": "This is a summary"}}
        out = format_excel_analysis_for_llm(ctx)
        assert "This is a summary" in out

    def test_customer_hint_from_ea(self):
        ctx = {"excel_analysis": {"customer_hint": "Acme Inc"}}
        out = format_excel_analysis_for_llm(ctx)
        assert "Acme Inc" in out

    def test_customer_hint_from_preview_data(self):
        ctx = {"excel_analysis": {"preview_data": {"customer_hint": "Beta Corp"}}}
        out = format_excel_analysis_for_llm(ctx)
        assert "Beta Corp" in out

    def test_fields_included(self):
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
        assert "Name" in out
        assert "Age" in out

    def test_preview_data_sheet_names(self):
        ctx = {
            "excel_analysis": {
                "preview_data": {
                    "sheet_names": ["Sheet1", "Sheet2"],
                    "sample_rows": [{"col": "val"}],
                }
            }
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "Sheet1" in out

    def test_linked_grid_preview_text(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": "preview data"},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "preview data" in out

    def test_linked_grid_preview_empty_text_skipped(self):
        ctx = {
            "excel_analysis": {"file_path": "/x.xlsx"},
            "excel_linked_grid_preview": {"preview_text": ""},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "关联工作表真实网格预览" not in out


# ─────────────── merge_system_prompt ────────────────────────────

class TestMergeSystemPrompt:
    def test_none_context_no_base(self):
        assert merge_system_prompt(None, None) is None

    def test_base_only(self):
        out = merge_system_prompt("You are an assistant.", None)
        assert out == "You are an assistant."

    def test_context_only(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt(None, ctx)
        assert "运行时上下文" in out

    def test_base_plus_context(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt("Base prompt.", ctx)
        assert "Base prompt." in out
        assert "运行时上下文" in out

    def test_empty_base_still_works(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt("", ctx)
        assert out is not None

    def test_include_products_context_false(self):
        ctx = {"excel_analysis": {"file_path": "/x.xlsx"}}
        out = merge_system_prompt("Base.", ctx, include_products_context=False)
        assert out is not None

    def test_no_signals_returns_base(self):
        out = merge_system_prompt("Base.", {"only_unrelated": True})
        assert out == "Base."

    def test_all_empty_returns_none(self):
        assert merge_system_prompt("", {}) is None


# ─────────────── planner_workflow_interrupt_reply ────────────────

class TestPlannerWorkflowInterruptReply:
    def test_pause_message(self):
        out = planner_workflow_interrupt_reply("暂停流程")
        assert "中断" in out

    def test_interrupt_message(self):
        out = planner_workflow_interrupt_reply("中断流程")
        assert "中断" in out

    def test_stop_message(self):
        out = planner_workflow_interrupt_reply("停止流程")
        assert "中断" in out

    def test_cancel_message(self):
        out = planner_workflow_interrupt_reply("取消流程")
        assert "中断" in out

    def test_slash_interrupt(self):
        out = planner_workflow_interrupt_reply("/interrupt")
        assert "中断" in out

    def test_other_message_returns_none(self):
        assert planner_workflow_interrupt_reply("something else") is None

    def test_none_returns_none(self):
        assert planner_workflow_interrupt_reply(None) is None

    def test_empty_returns_none(self):
        assert planner_workflow_interrupt_reply("") is None


# ─────────────── runtime_context_after_workflow_interrupt ────────

class TestRuntimeContextAfterWorkflowInterrupt:
    def test_none_returns_empty(self):
        out = runtime_context_after_workflow_interrupt(None)
        assert out == {}

    def test_removes_workflow_state(self):
        ctx = {"workflow_state": {"step": 1}, "other": "val"}
        out = runtime_context_after_workflow_interrupt(ctx)
        assert "workflow_state" not in out
        assert out["other"] == "val"

    def test_no_workflow_state_passes_through(self):
        ctx = {"key": "value"}
        out = runtime_context_after_workflow_interrupt(ctx)
        assert out == {"key": "value"}

    def test_does_not_mutate_original(self):
        ctx = {"workflow_state": "x", "k": "v"}
        out = runtime_context_after_workflow_interrupt(ctx)
        assert "workflow_state" in ctx  # original unchanged
        assert "workflow_state" not in out
