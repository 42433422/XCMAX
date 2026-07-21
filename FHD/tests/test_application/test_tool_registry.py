"""Tests for app.application.tools.workflow 注册表与分发。

验证：
- 注册表中工具总数 ≥ 15
- 13 个新工具（订单/客户/报表/RBAC）已正确注册
- 原有 8 个工具未被破坏
- 高危工具标记了 risk_level=high
- 分发器能解析所有新工具名
"""

from __future__ import annotations

import pytest

from app.application.tools.workflow import (
    _resolve_new_tool_dispatch,
    get_workflow_tool_registry,
)

# ─── 期望工具清单 ────────────────────────────────────────────────────────────

# 原 8 个工具（不能被新增工具破坏）
_EXISTING_TOOL_NAMES = {
    "excel_analysis",
    "excel_schema_understand",
    "excel_join_compare",
    "excel_chart_recommend",
    "import_excel_to_database",
    "template_preview",
    "generate_office_document",
    "products_bulk_import",
}

# 13 个新增工具
_NEW_TOOL_NAMES = {
    # 订单（出货记录）
    "delete_order",
    "update_order",
    "list_orders",
    # 客户（购买单位）
    "update_customer",
    "delete_customer",
    "list_customers",
    # 报表配置
    "configure_report",
    "list_report_configs",
    # RBAC
    "create_role",
    "update_role",
    "delete_role",
    "assign_role",
    "list_roles",
}

# 高危工具（必须 risk_level=high）
_HIGH_RISK_TOOLS = {
    "delete_order",
    "delete_customer",
    "create_role",
    "delete_role",
    "assign_role",
}


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> list[dict]:
    """获取工作流工具注册表。"""
    return get_workflow_tool_registry()


@pytest.fixture
def registry_by_name(registry: list[dict]) -> dict[str, dict]:
    """按工具名建索引便于查询。"""
    return {entry["function"]["name"]: entry for entry in registry}


# ─── 工具数量与存在性 ────────────────────────────────────────────────────────


class TestRegistrySize:
    """注册表规模测试。"""

    def test_registry_has_at_least_15_tools(self, registry: list[dict]):
        """注册表工具总数至少 15 个（当前 8 基础 + 13 新增 = 21+）。"""
        assert len(registry) >= 15, f"registry 只有 {len(registry)} 个工具，期望 ≥ 15"

    def test_registry_entries_are_well_formed(self, registry: list[dict]):
        """每个工具条目结构合法：type=function + function.name + function.parameters。"""
        for entry in registry:
            assert entry.get("type") == "function", f"非 function 类型: {entry}"
            fn = entry.get("function") or {}
            assert "name" in fn, f"缺少 function.name: {entry}"
            assert isinstance(fn.get("name"), str) and fn["name"], f"工具名为空: {entry}"
            assert "parameters" in fn, f"缺少 function.parameters: {entry}"
            assert "description" in fn, f"缺少 function.description: {entry}"


class TestExistingToolsPreserved:
    """原有 8 个工具不应被新增工具破坏。"""

    def test_all_existing_tools_present(self, registry_by_name: dict[str, dict]):
        """所有原 8 工具仍存在于注册表中。"""
        missing = _EXISTING_TOOL_NAMES - set(registry_by_name.keys())
        assert not missing, f"原工具缺失: {missing}"


class TestNewToolsRegistered:
    """13 个新工具应全部注册到 registry。"""

    def test_all_new_tools_present(self, registry_by_name: dict[str, dict]):
        """所有 13 个新工具名应出现在注册表中。"""
        missing = _NEW_TOOL_NAMES - set(registry_by_name.keys())
        assert not missing, f"新工具缺失: {missing}"

    def test_new_tool_count_is_13(self, registry_by_name: dict[str, dict]):
        """新工具数量恰好等于 13。"""
        present = _NEW_TOOL_NAMES & set(registry_by_name.keys())
        assert len(present) == 13, f"新工具数量异常: {len(present)}/13"

    def test_all_new_tools_have_parameters(self, registry_by_name: dict[str, dict]):
        """每个新工具的 parameters 字段应是非空 dict。"""
        for name in _NEW_TOOL_NAMES:
            params = registry_by_name[name]["function"]["parameters"]
            assert isinstance(params, dict), f"{name}.parameters 不是 dict"
            assert params.get("type") == "object", f"{name}.parameters.type 不是 object"


# ─── risk_level 标注 ────────────────────────────────────────────────────────


class TestRiskLevelMarking:
    """高危工具必须显式标记 risk_level=high。"""

    def test_high_risk_tools_marked_high(self, registry_by_name: dict[str, dict]):
        """delete/clear/assign 等高危工具应标记 risk_level=high。"""
        for name in _HIGH_RISK_TOOLS:
            assert registry_by_name[name].get("risk_level") == "high", (
                f"{name} 应标记 risk_level=high，实际: {registry_by_name[name].get('risk_level')}"
            )

    def test_list_only_tools_marked_low(self, registry_by_name: dict[str, dict]):
        """只读查询类工具应标记 risk_level=low。"""
        low_risk_new_tools = {"list_orders", "list_customers", "list_report_configs", "list_roles"}
        for name in low_risk_new_tools:
            assert registry_by_name[name].get("risk_level") == "low", (
                f"{name} 应标记 risk_level=low，实际: {registry_by_name[name].get('risk_level')}"
            )

    def test_update_tools_marked_medium(self, registry_by_name: dict[str, dict]):
        """更新类工具应标记 risk_level=medium。"""
        medium_risk_new_tools = {
            "update_order",
            "update_customer",
            "configure_report",
            "update_role",
        }
        for name in medium_risk_new_tools:
            assert registry_by_name[name].get("risk_level") == "medium", (
                f"{name} 应标记 risk_level=medium，实际: {registry_by_name[name].get('risk_level')}"
            )


# ─── 高危工具 confirm 参数 ──────────────────────────────────────────────────


class TestHighRiskConfirmParameter:
    """高危工具的 parameters 必须包含 confirm 字段以守护二次确认。"""

    def test_high_risk_tools_have_confirm_param(self, registry_by_name: dict[str, dict]):
        """所有高危工具的 parameters.properties 应包含 confirm 布尔字段。"""
        for name in _HIGH_RISK_TOOLS:
            params = registry_by_name[name]["function"]["parameters"]
            props = params.get("properties") or {}
            assert "confirm" in props, f"{name} 缺少 confirm 参数"
            assert props["confirm"].get("type") == "boolean", (
                f"{name}.confirm 类型应为 boolean，实际: {props['confirm'].get('type')}"
            )


# ─── 工具分发器 ─────────────────────────────────────────────────────────────


class TestDispatcherResolution:
    """分发器 _resolve_new_tool_dispatch 应能解析所有新工具名。"""

    def test_dispatcher_resolves_all_new_tools(self):
        """每个新工具名应解析到可调用执行器。"""
        for name in _NEW_TOOL_NAMES:
            executor = _resolve_new_tool_dispatch(name)
            assert callable(executor), f"{name} 未找到可调用执行器"

    def test_dispatcher_returns_none_for_unknown(self):
        """未知工具名应返回 None。"""
        assert _resolve_new_tool_dispatch("non_existent_tool_xyz") is None

    def test_dispatcher_uses_cache(self):
        """重复调用应命中缓存（返回相同对象）。"""
        first = _resolve_new_tool_dispatch("delete_order")
        second = _resolve_new_tool_dispatch("delete_order")
        assert first is second, "分发器未使用缓存"


# ─── 工具分发执行（端到端，不实际执行业务） ─────────────────────────────────


class TestDispatcherExecution:
    """分发器在缺少 confirm 时应返回 needs_confirm，不应调用 service。"""

    def test_delete_order_without_confirm_returns_needs_confirm(self):
        """delete_order 通过分发器调用，未传 confirm 应返回 needs_confirm。"""
        import json

        from app.application.tools.workflow import execute_workflow_tool

        result_json = execute_workflow_tool(
            "delete_order", {"order_number": "42", "confirm": False}
        )
        result = json.loads(result_json)
        assert result["success"] is False
        assert result.get("needs_confirm") is True

    def test_create_role_without_confirm_returns_needs_confirm(self):
        """create_role 通过分发器调用，未传 confirm 应返回 needs_confirm。"""
        import json

        from app.application.tools.workflow import execute_workflow_tool

        result_json = execute_workflow_tool(
            "create_role",
            {"name": "test_role", "permissions": [], "confirm": False},
        )
        result = json.loads(result_json)
        assert result["success"] is False
        assert result.get("needs_confirm") is True

    def test_unknown_tool_returns_unknown_tool_error(self):
        """未知工具名应返回 unknown_tool 错误。"""
        import json

        from app.application.tools.workflow import execute_workflow_tool

        result_json = execute_workflow_tool("totally_unknown_tool", {})
        result = json.loads(result_json)
        assert result["success"] is False
        assert result["error"] == "unknown_tool"
        assert result["tool"] == "totally_unknown_tool"
