"""app/domain/context/session_context 单测：Excel 表头探测 / 工具参数补全 / LLM 上下文合并。

纯逻辑（json/re/os.path），无外部边界（铁律4）；覆盖各 dict 形状/空值/注入清洗/
多工作表/写入授权/续跑/小猫数据集与联网检索分支（铁律3）。
"""

from __future__ import annotations

from app.domain.context.session_context import (
    _format_kitten_runtime_for_llm,
    _sanitize_untrusted_context_line,
    detected_excel_header_row_1based,
    enrich_excel_tool_arguments,
    format_excel_analysis_for_llm,
    format_recent_messages_excerpt_for_llm,
    format_runtime_context_for_llm,
    merge_system_prompt,
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)


class TestDetectedHeaderRow:
    def test_non_dict_returns_none(self):
        assert detected_excel_header_row_1based("x") is None

    def test_preferred_sheet_grid_preview(self):
        ea = {
            "sheets": [
                {"sheet_name": "A", "grid_preview": {"header_row_index": 3}},
                {"sheet_name": "B", "grid_preview": {"header_row_index": 7}},
            ]
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="B") == 7

    def test_preferred_sheet_tables_fallback(self):
        ea = {"sheets": [{"sheet_name": "A", "tables": [{"header_row": 2}]}]}
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="A") == 2

    def test_preferred_via_preview_all_sheets(self):
        ea = {
            "preview_data": {
                "all_sheets": [{"sheet_name": "S", "grid_preview": {"header_row_index": 4}}]
            }
        }
        assert detected_excel_header_row_1based(ea, preferred_sheet_name="S") == 4

    def test_top_level_preview_grid(self):
        ea = {"preview_data": {"grid_preview": {"header_row_index": 5}}}
        assert detected_excel_header_row_1based(ea) == 5

    def test_top_level_preview_tables(self):
        ea = {"preview_data": {"tables": [{"header_row": 6}]}}
        assert detected_excel_header_row_1based(ea) == 6

    def test_first_sheet_fallback(self):
        ea = {"sheets": [{"grid_preview": {"header_row_index": 9}}]}
        assert detected_excel_header_row_1based(ea) == 9

    def test_invalid_header_returns_none(self):
        ea = {"preview_data": {"grid_preview": {"header_row_index": "abc"}}}
        assert detected_excel_header_row_1based(ea) is None

    def test_zero_header_returns_none(self):
        ea = {"preview_data": {"tables": [{"header_row": 0}]}}
        assert detected_excel_header_row_1based(ea) is None


class TestEnrichExcelArgs:
    def test_none_context_passthrough(self):
        assert enrich_excel_tool_arguments("excel_analysis", {"a": 1}, None) == {"a": 1}

    def test_wrong_tool_passthrough(self):
        assert enrich_excel_tool_arguments("other", {"a": 1}, {"excel_analysis": {}}) == {"a": 1}

    def test_ea_not_dict_passthrough(self):
        out = enrich_excel_tool_arguments("excel_analysis", {"a": 1}, {"excel_analysis": "x"})
        assert out == {"a": 1}

    def test_fills_file_path_and_header(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/tmp/x.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            }
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["file_path"] == "/tmp/x.xlsx"
        assert out["header_row"] == 2

    def test_fills_sheet_name_from_selected(self):
        ctx = {
            "excel_analysis": {"file_path": "/tmp/x.xlsx"},
            "excel_analysis_selected_sheet": {"sheet_name": "Sheet2"},
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["sheet_name"] == "Sheet2"

    def test_fills_sheet_name_from_preferred(self):
        ctx = {
            "excel_analysis": {"file_path": "/tmp/x.xlsx"},
            "preferred_sheet_name": "Pref",
        }
        out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
        assert out["sheet_name"] == "Pref"


class TestSanitize:
    def test_collapses_newlines_and_strips_control(self):
        out = _sanitize_untrusted_context_line("a\r\n\n\n\nb\x00c", 100)
        assert "\x00" not in out
        assert "\n\n\n" not in out
        assert "a" in out and "b" in out

    def test_truncates(self):
        out = _sanitize_untrusted_context_line("x" * 50, 10)
        assert out.endswith("…")
        assert len(out) == 11


class TestRecentMessages:
    def test_none(self):
        assert format_recent_messages_excerpt_for_llm(None) is None

    def test_no_messages(self):
        assert format_recent_messages_excerpt_for_llm({"recent_messages": []}) is None

    def test_builds_excerpt(self):
        ctx = {"recent_messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]}
        out = format_recent_messages_excerpt_for_llm(ctx)
        assert "近期对话摘要" in out
        assert "[user] hi" in out

    def test_skips_non_dict_and_empty(self):
        ctx = {"recent_messages": ["x", {"role": "user", "content": ""}]}
        assert format_recent_messages_excerpt_for_llm(ctx) is None


class TestRuntimeContextForLlm:
    def test_none(self):
        assert format_runtime_context_for_llm(None) is None

    def test_minimal_no_signal_returns_none(self):
        assert format_runtime_context_for_llm({"unrelated": 1}) is None

    def test_with_excel_file_path(self):
        out = format_runtime_context_for_llm({"excel_file_path": "/tmp/a.xlsx"})
        assert "excel_file_path: /tmp/a.xlsx" in out

    def test_select_all_sheets(self):
        ctx = {
            "excel_file_path": "/tmp/a.xlsx",
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": [{"sheet_name": "S1"}, {"sheet_name": "S2"}],
        }
        out = format_runtime_context_for_llm(ctx)
        assert "全部工作表" in out
        assert "S1" in out and "S2" in out

    def test_selected_single_sheet(self):
        ctx = {
            "excel_file_path": "/tmp/a.xlsx",
            "excel_analysis_selected_sheet": {"sheet_name": "Only"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "当前选中的工作表: Only" in out

    def test_write_authorized_branch(self):
        ctx = {"excel_file_path": "/tmp/a.xlsx", "chat_db_write_authorized": True}
        out = format_runtime_context_for_llm(ctx)
        assert "写入授权" in out

    def test_resume_branch(self):
        ctx = {"db_write_stream_resume": "previous stream content"}
        out = format_runtime_context_for_llm(ctx)
        assert "同一轮对话续跑" in out

    def test_extra_fields(self):
        ctx = {
            "excel_file_paths": ["/a", "/b"],
            "ai_tier": "pro",
        }
        out = format_runtime_context_for_llm(ctx)
        assert "excel_file_paths: /a, /b" in out
        assert "ai_tier: pro" in out


class TestKittenRuntime:
    def test_none_without_flag(self):
        assert _format_kitten_runtime_for_llm({}) is None

    def test_with_dataset(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_dataset": {"file_name": "d.csv", "rows": 10, "columns": 3, "fields": ["a", "b"]},
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "数据文件: d.csv" in out
        assert "行数: 10" in out
        assert "字段: a, b" in out

    def test_without_dataset_uses_placeholder(self):
        out = _format_kitten_runtime_for_llm({"kitten_analyzer": True})
        assert "未在上下文中附带" in out

    def test_web_search_hits(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_meta": {"provider": "bing", "query": "q"},
            "web_search_results": [{"title": "T", "url": "http://x", "snippet": "s"}],
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "联网检索" in out
        assert "http://x" in out

    def test_web_search_error(self):
        ctx = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": [],
            "web_search_error": "boom",
        }
        out = _format_kitten_runtime_for_llm(ctx)
        assert "未返回结果" in out


class TestRuntimeContextRich:
    def test_rich_context_hits_many_branches(self):
        ctx = {
            "excel_file_path": "/tmp/a.xlsx",
            "excel_analysis": {
                "file_path": "/tmp/a.xlsx",
                "preview_data": {"grid_preview": {"header_row_index": 2}},
            },
            "excel_analysis_selected_sheet": {"sheet_name": "Only"},
            "excel_linked_grid_preview": {"preview_text": "网格A"},
            "excel_linked_grid_previews": [
                {"preview_text": "p1"},
                {"preview_text": "p2"},
            ],
            "excel_customer_hint": "甲公司",
            "ai_tier": "pro",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "kitten_analyzer": True,
            "kitten_business_snapshot": {"text": "快照内容"},
        }
        out = format_runtime_context_for_llm(ctx)
        assert "网格A" in out
        assert "excel_customer_hint" in out
        assert "表头行" in out
        assert "近期对话摘要" in out
        assert "快照" in out


class TestExcelAnalysisForLlm:
    def test_none(self):
        assert format_excel_analysis_for_llm(None) is None

    def test_select_all_sheets_and_linked_preview(self):
        ctx = {
            "excel_analysis": {
                "file_name": "f.xlsx",
                "preview_data": {"sample_rows": [{"a": 1}], "sheet_names": ["S1", "S2"]},
            },
            "excel_analysis_select_all_sheets": True,
            "excel_analysis_selected_sheets": [{"sheet_name": "S1"}, {"sheet_name": "S2"}],
            "excel_linked_grid_preview": {"preview_text": "网格预览"},
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "全部工作表" in out
        assert "网格预览" in out
        assert "样例行" in out

    def test_not_dict(self):
        assert format_excel_analysis_for_llm({"excel_analysis": "x"}) is None

    def test_builds_summary(self):
        ctx = {
            "excel_analysis": {
                "file_name": "f.xlsx",
                "file_path": "/tmp/f.xlsx",
                "summary": "总览",
                "customer_hint": "甲公司",
                "fields": [{"label": "列A"}, {"name": "列B"}],
                "preview_data": {
                    "grid_preview": {"header_row_index": 2},
                    "sheet_names": ["S1"],
                    "sample_rows": [{"a": 1}],
                },
            }
        }
        out = format_excel_analysis_for_llm(ctx)
        assert "文件: f.xlsx" in out
        assert "总览" in out
        assert "甲公司" in out
        assert "列A" in out
        assert "S1" in out


class TestMergeSystemPrompt:
    def test_base_only(self):
        assert merge_system_prompt("base prompt", None) == "base prompt"

    def test_empty_returns_none(self):
        assert merge_system_prompt(None, None) is None

    def test_wraps_untrusted_runtime(self):
        ctx = {"excel_file_path": "/tmp/a.xlsx"}
        out = merge_system_prompt("base", ctx)
        assert "base" in out
        assert "xcagi_untrusted_runtime" in out


class TestInterruptHelpers:
    def test_interrupt_reply_matches(self):
        assert planner_workflow_interrupt_reply("暂停流程") is not None
        assert planner_workflow_interrupt_reply("/interrupt") is not None

    def test_interrupt_reply_no_match(self):
        assert planner_workflow_interrupt_reply("继续吧") is None
        assert planner_workflow_interrupt_reply(None) is None

    def test_runtime_after_interrupt_pops_state(self):
        out = runtime_context_after_workflow_interrupt({"workflow_state": {"x": 1}, "keep": 2})
        assert "workflow_state" not in out
        assert out["keep"] == 2

    def test_runtime_after_interrupt_none(self):
        assert runtime_context_after_workflow_interrupt(None) == {}
