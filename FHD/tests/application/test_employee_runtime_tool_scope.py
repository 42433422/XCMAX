"""employee_runtime.tool_scope 能力→工具作用域派生单元测试。

纯策略直接校验；模型目录使用真实登录身份与权威 ToolSpec，防止跨账号缓存和别名扩权。
"""

from __future__ import annotations

import pytest

from app.application.employee_runtime import tool_scope as ts
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


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

    def test_empty_list_denies_tools(self):
        assert ts._explicit_allowlist({"tools": []}, {"tools": ["excel_analysis"]}) == []

    @pytest.mark.parametrize(
        ("config", "manifest", "expected"),
        [
            ({"tools": ["customers"]}, {"tools": ["customers.query"]}, ["customers.query"]),
            ({"tools": ["customers.query"]}, {"tools": ["customers"]}, ["customers.query"]),
            ({"tools": ["customers.query"]}, {"tools": ["customers.export"]}, []),
            ({"tools": ["customers"]}, {"tools": []}, []),
            ({"tools": ["customers"]}, {"tools": "customers"}, []),
            (
                {"tools": ["customers"], "actions": {"agent": {"tools": ["customers.query"]}}},
                {"employee_config_v2": {"tools": ["customers.export"]}},
                [],
            ),
        ],
    )
    def test_every_explicit_layer_narrows_authority(self, config, manifest, expected):
        assert ts._explicit_allowlist(config, manifest) == expected


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
    def test_direct_workspace_policy(self):
        assert ts.is_read_only({}, {"workspace_policy": {"read_only": True}})

    def test_actions_agent_workspace(self):
        assert ts.is_read_only({}, {"actions": {"agent": {"workspace": {"read_only": True}}}})

    def test_v2_workspace_policy(self):
        assert ts.is_read_only(
            {"employee_config_v2": {"workspace_policy": {"read_only": True}}}, {}
        )

    def test_default_false(self):
        assert ts.is_read_only({}, {}) is False


class TestResolveEmployeeTools:
    def test_requires_real_runtime_actor(self):
        assert ts.resolve_employee_tools("e", {}, {"tools": ["business_db"]}) == []
        assert (
            ts.resolve_employee_tools(
                "e", {}, {"tools": ["business_db"]}, {"user_id": "1", "tenant_id": "1"}
            )
            == []
        )

    def test_canonical_allowlist_cannot_expand_account_grants(self, trusted_actor):
        actor = trusted_actor(permissions=["customer.view"])
        config = {"tools": ["business_db", "customers", "nonexistent"]}
        names = ts.employee_tool_names("e", {}, config, actor.context)
        assert names == ["business_db.read", "customers.export", "customers.query"]
        definition = ts.resolve_employee_tools("e", {}, config, actor.context)[0]
        branch = definition["function"]["parameters"]["anyOf"][0]
        assert branch["properties"]["params"]["properties"]["entity"]["enum"] == ["customers"]

    def test_explicit_action_and_readonly_restrict_same_authority(self, trusted_actor):
        actor = trusted_actor(role="admin", tier="admin")
        config = {
            "tools": [
                "excel_analysis.read",
                "excel_analysis.export",
                "excel_toolkit.view",
                "generate_office_document",
                "employee",
            ],
            "workspace_policy": {"read_only": True},
        }
        assert ts.employee_tool_names("e", {}, config, actor.context) == [
            "excel_analysis.read",
            "excel_toolkit.view",
        ]

    def test_empty_or_unknown_allowlist_cannot_gain_tools(self, trusted_actor):
        actor = trusted_actor(role="admin", tier="admin")
        for allow in ([], ["business_db_read", "products_bulk_import", "excel_chart_recommend"]):
            assert ts.resolve_employee_tools("e", {}, {"tools": allow}, actor.context) == []

    def test_excel_keyword_selects_only_registered_readonly_actions(self, trusted_actor):
        actor = trusted_actor(role="admin", tier="admin")
        names = ts.employee_tool_names(
            "e",
            {"employee": {"capabilities": ["Excel 数据分析"]}},
            {"workspace_policy": {"read_only": True}},
            actor.context,
        )
        assert set(names) == {
            "excel_analysis.read",
            "excel_analysis.query",
            "excel_analysis.statistics",
            "excel_analysis.structure",
            "excel_analysis.aggregate",
            "excel_join_compare.join",
            "excel_join_compare.diff",
        }

    def test_unregistered_lifecycle_tools_do_not_expand_model_contract(
        self, monkeypatch, trusted_actor
    ):
        from app.application import agent_tool_lifecycle

        actor = trusted_actor(permissions=["customer.view"])
        monkeypatch.setattr(
            agent_tool_lifecycle,
            "discovery",
            lambda *_: [{"function": {"name": "private_tool"}}],
        )
        names = ts.employee_tool_names(
            "e",
            {},
            {"tools": ["business_db", "private_tool"]},
            actor.context,
        )
        assert names == ["business_db.read"]


def test_pack_action_restriction_is_preserved_for_admin_actor(trusted_actor):
    actor = trusted_actor(role="admin", tier="admin")
    assert ts.employee_tool_names(
        "e",
        {"tools": ["customers.query"]},
        {"tools": ["customers"]},
        actor.context,
    ) == ["customers.query"]
