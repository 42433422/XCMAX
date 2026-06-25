"""employee_runtime.tool_scope 能力→工具作用域派生单元测试。

策略：_base_tool_specs 读全局 workflow 工具注册表（I/O 边界），用 monkeypatch 注入
可控 fake base，专注验证选择逻辑（铁律4 只 mock 边界）。helpers 直接测，无需 mock。
"""

from __future__ import annotations

import pytest

from app.application.employee_runtime import tool_scope as ts

FAKE_BASE = {
    name: {"function": {"name": name}}
    for name in (
        "excel_analysis",
        "excel_schema_understand",
        "excel_join_compare",
        "excel_chart_recommend",
        "generate_office_document",
        "import_excel_to_database",
        "products_bulk_import",
    )
}


@pytest.fixture
def fake_base(monkeypatch):
    monkeypatch.setattr(ts, "_base_tool_specs", lambda: dict(FAKE_BASE))
    return FAKE_BASE


class TestExplicitAllowlist:
    def test_config_tools(self):
        names = ts._explicit_allowlist({"tools": ["a", "b"]}, {})
        assert names == ["a", "b"]

    def test_actions_tools(self):
        names = ts._explicit_allowlist({"actions": {"tools": ["x"]}}, {})
        assert names == ["x"]

    def test_actions_agent_tools(self):
        names = ts._explicit_allowlist({"actions": {"agent": {"tools": ["y"]}}}, {})
        assert names == ["y"]

    def test_v2_tools(self):
        names = ts._explicit_allowlist({}, {"employee_config_v2": {"tools": ["z"]}})
        assert names == ["z"]

    def test_manifest_tools(self):
        names = ts._explicit_allowlist({}, {"tools": ["m"]})
        assert names == ["m"]

    def test_none_when_no_lists(self):
        assert ts._explicit_allowlist({}, {}) is None

    def test_blank_entries_filtered(self):
        names = ts._explicit_allowlist({"tools": ["a", "  ", ""]}, {})
        assert names == ["a"]

    def test_empty_list_falls_through(self):
        # config.tools=[] → 无有效名 → 继续找下个候选 → None
        assert ts._explicit_allowlist({"tools": []}, {}) is None


class TestCapabilityText:
    def test_from_employee_capabilities_dict_and_str(self):
        manifest = {
            "employee": {"capabilities": [{"label": "Excel", "description": "表格"}, "图表"]}
        }
        text = ts._capability_text(manifest, {})
        assert "excel" in text and "图表" in text

    def test_from_cognition_expertise_and_skills(self):
        config = {
            "cognition": {
                "agent": {"role": {"expertise": ["报表分析"]}},
                "skills": [{"name": "OCR", "brief": "识别"}, "导入"],
            }
        }
        text = ts._capability_text({}, config)
        assert "报表分析" in text and "ocr" in text and "导入" in text

    def test_from_identity_and_description(self):
        text = ts._capability_text(
            {"description": "客服"}, {"identity": {"domain": "销售", "name": "小助手"}}
        )
        assert "客服" in text and "销售" in text


class TestIsReadOnly:
    def test_actions_agent_workspace(self):
        assert ts.is_read_only({}, {"actions": {"agent": {"workspace": {"read_only": True}}}})

    def test_v2_workspace_policy(self):
        assert ts.is_read_only(
            {"employee_config_v2": {"workspace_policy": {"read_only": True}}}, {}
        )

    def test_default_false(self):
        assert ts.is_read_only({}, {}) is False


class TestResolveEmployeeTools:
    def test_empty_base_returns_none(self, monkeypatch):
        monkeypatch.setattr(ts, "_base_tool_specs", lambda: {})
        assert ts.resolve_employee_tools("e", {}, {}) is None

    def test_explicit_allowlist_filtered_to_base(self, fake_base):
        specs = ts.resolve_employee_tools("e", {}, {"tools": ["excel_analysis", "nonexistent"]})
        names = [s["function"]["name"] for s in specs]
        assert names == ["excel_analysis"]

    def test_explicit_allowlist_none_in_base_returns_none(self, fake_base):
        assert ts.resolve_employee_tools("e", {}, {"tools": ["nope"]}) is None

    def test_excel_keyword_selects_read_tools(self, fake_base):
        manifest = {"employee": {"capabilities": ["Excel 数据分析"]}}
        names = ts.employee_tool_names("e", manifest, {})
        assert "excel_analysis" in names

    def test_chart_keyword_selects_chart_tool(self, fake_base):
        manifest = {"employee": {"capabilities": ["图表可视化"]}}
        names = ts.employee_tool_names("e", manifest, {})
        assert "excel_chart_recommend" in names

    def test_doc_keyword_selects_doc_tool(self, fake_base):
        manifest = {"employee": {"capabilities": ["报告文档生成"]}}
        names = ts.employee_tool_names("e", manifest, {})
        assert "generate_office_document" in names

    def test_import_keyword_not_readonly_selects_write(self, fake_base):
        manifest = {"employee": {"capabilities": ["批量导入入库"]}}
        names = ts.employee_tool_names("e", manifest, {})
        assert "import_excel_to_database" in names
        assert "products_bulk_import" in names

    def test_import_keyword_readonly_excludes_write(self, fake_base):
        manifest = {
            "employee": {"capabilities": ["批量导入"]},
            "employee_config_v2": {"workspace_policy": {"read_only": True}},
        }
        names = ts.employee_tool_names("e", manifest, {})
        assert "import_excel_to_database" not in names
        assert "products_bulk_import" not in names

    def test_no_keywords_uses_fallback(self, fake_base):
        names = ts.employee_tool_names("e", {"employee": {"capabilities": ["无关词"]}}, {})
        assert "excel_analysis" in names
        assert "excel_schema_understand" in names
        assert "generate_office_document" in names

    def test_employee_tool_names_empty_when_resolve_none(self, monkeypatch):
        monkeypatch.setattr(ts, "_base_tool_specs", lambda: {})
        assert ts.employee_tool_names("e", {}, {}) == []
