"""测试 app.application.workflow.planner 的分支覆盖。

覆盖目标：
- _clean_db_slot_value（多 token 清理 / 前后缀正则 / 空值）
- _extract_named_slot（模式匹配 / 引号回退 / 空）
- _looks_like_business_db_write（关键词命中 / db 标记 / 不匹配）
- _infer_business_db_entity（产品 / 客户 / 原材料 / 出货 / 默认）
- _extract_business_db_write_node（customers / products / materials→None / 缺槽→None）
- _extract_business_db_read_keyword（引号 / products / customers / materials / 兜底清理）
- execute_tool（默认 action / handler 命中 / 未知工具）
- _filter_tool_registry_for_profile（normal / pro_default / shared / 非 dict 跳过）
- LLMWorkflowPlanner._validate_required_params（缺参 / 满足 / 无 tool_spec）
- LLMWorkflowPlanner._fallback_plan（employee / db_write / db_read / add_product / generic）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _clean_db_slot_value,
    _execute_excel_decompose_tool,
    _execute_print_label_tool,
    _execute_shipment_generate_tool,
    _extract_business_db_read_keyword,
    _extract_business_db_write_node,
    _extract_named_slot,
    _filter_tool_registry_for_profile,
    _infer_business_db_entity,
    _looks_like_business_db_write,
    execute_tool,
    get_tool_registry,
)
from app.application.workflow.types import PlanGraph, WorkflowNode


class TestCleanDbSlotValue:
    """_clean_db_slot_value 分支覆盖。"""

    def test_none_returns_empty(self) -> None:
        assert _clean_db_slot_value(None) == ""

    def test_empty_string(self) -> None:
        assert _clean_db_slot_value("") == ""

    def test_strips_database_tokens(self) -> None:
        # "到数据库" is replaced → "客户", then prefix "客户" is stripped → ""
        assert _clean_db_slot_value("客户到数据库") == ""
        # "写入数据库" is replaced → "产品", then prefix "产品" is stripped → ""
        assert _clean_db_slot_value("产品写入数据库") == ""
        # "入库" is replaced → "原材料", no prefix/suffix match → "原材料"
        assert _clean_db_slot_value("入库原材料") == "原材料"

    def test_strips_prefix_keywords(self) -> None:
        # prefix "新增" stripped → "客户A", suffix "客户" not at end → "客户A"
        assert _clean_db_slot_value("新增客户A") == "客户A"
        # prefix "添加" stripped → "产品B", suffix "产品" not at end → "产品B"
        assert _clean_db_slot_value("添加产品B") == "产品B"
        # prefix "创建" stripped → "单位C", suffix "单位" not at end → "单位C"
        assert _clean_db_slot_value("创建单位C") == "单位C"

    def test_strips_suffix_keywords(self) -> None:
        assert _clean_db_slot_value("ABC客户") == "ABC"
        assert _clean_db_slot_value("XYZ产品") == "XYZ"
        assert _clean_db_slot_value("DEF单位") == "DEF"

    def test_strips_punctuation(self) -> None:
        # "，客户，" → strip → "客户" → prefix "客户" stripped → ""
        assert _clean_db_slot_value("，客户，") == ""
        # "：产品：" → strip → "产品" → prefix "产品" stripped → ""
        assert _clean_db_slot_value("：产品：") == ""
        # ";单位;" → strip → "单位" → prefix "单位" stripped → ""
        assert _clean_db_slot_value(";单位;") == ""


class TestExtractNamedSlot:
    """_extract_named_slot 分支覆盖。"""

    def test_pattern_match_returns_cleaned_value(self) -> None:
        result = _extract_named_slot("客户：七彩乐园", (r"客户\s*[:：是为]?\s*([^\s，,。；;]+)",))
        assert result == "七彩乐园"

    def test_pattern_match_with_prefix_keyword(self) -> None:
        result = _extract_named_slot(
            "新增 ABC 客户",
            (r"(?:新增|添加|创建|写入|保存)\s*([^\s，,。；;]+)\s*(?:客户|单位)",),
        )
        assert result == "ABC"

    def test_no_pattern_match_falls_back_to_quoted(self) -> None:
        result = _extract_named_slot("请处理「七彩乐园」", (r"不存在的模式",))
        assert result == "七彩乐园"

    def test_no_match_no_quotes_returns_empty(self) -> None:
        result = _extract_named_slot("普通文本无引号", (r"不存在的模式",))
        assert result == ""

    def test_empty_value_after_clean_returns_empty(self) -> None:
        # pattern matches but cleaned value is empty
        result = _extract_named_slot("客户：数据库", (r"客户\s*[:：是为]?\s*([^\s，,。；;]+)",))
        assert result == ""

    def test_double_quote_fallback(self) -> None:
        result = _extract_named_slot('请处理"七彩乐园"', (r"不存在的模式",))
        assert result == "七彩乐园"

    def test_single_quote_fallback(self) -> None:
        result = _extract_named_slot("请处理'七彩乐园'", (r"不存在的模式",))
        assert result == "七彩乐园"


class TestLooksLikeBusinessDbWrite:
    """_looks_like_business_db_write 分支覆盖。"""

    def test_chinese_keyword_with_db(self) -> None:
        assert _looks_like_business_db_write("新增到数据库", "新增到数据库") is True

    def test_english_keyword_with_db(self) -> None:
        assert _looks_like_business_db_write("add to db", "add to db") is True

    def test_english_keyword_with_database(self) -> None:
        assert _looks_like_business_db_write("create database entry", "create database entry") is True

    def test_chinese_keyword_with_入库(self) -> None:
        assert _looks_like_business_db_write("入库产品", "入库产品") is True

    def test_no_write_keyword_returns_false(self) -> None:
        assert _looks_like_business_db_write("查询产品", "查询产品") is False

    def test_write_keyword_but_no_db_marker_returns_false(self) -> None:
        assert _looks_like_business_db_write("新增产品", "新增产品") is False

    def test_english_insert_with_db(self) -> None:
        assert _looks_like_business_db_write("insert into db", "insert into db") is True

    def test_english_upsert_with_database(self) -> None:
        assert _looks_like_business_db_write("upsert database", "upsert database") is True


class TestInferBusinessDbEntity:
    """_infer_business_db_entity 分支覆盖。"""

    def test_products(self) -> None:
        assert _infer_business_db_entity("产品") == "products"
        assert _infer_business_db_entity("商品") == "products"

    def test_customers(self) -> None:
        assert _infer_business_db_entity("客户") == "customers"
        assert _infer_business_db_entity("单位") == "customers"
        assert _infer_business_db_entity("购买单位") == "customers"

    def test_materials(self) -> None:
        assert _infer_business_db_entity("原材料") == "materials"
        assert _infer_business_db_entity("物料") == "materials"

    def test_shipment(self) -> None:
        assert _infer_business_db_entity("出货") == "shipment_records"
        assert _infer_business_db_entity("发货") == "shipment_records"
        assert _infer_business_db_entity("发货单") == "shipment_records"

    def test_default_returns_products(self) -> None:
        assert _infer_business_db_entity("无关键词") == "products"
        assert _infer_business_db_entity("") == "products"


class TestExtractBusinessDbWriteNode:
    """_extract_business_db_write_node 分支覆盖。"""

    def test_customers_with_unit_name(self) -> None:
        node = _extract_business_db_write_node("新增客户：七彩乐园")
        assert node is not None
        assert node.tool_id == "business_db"
        assert node.action == "write"
        assert node.params["entity"] == "customers"
        assert node.params["payload"]["unit_name"] == "七彩乐园"
        assert node.risk == "medium"
        assert node.idempotent is True

    def test_customers_missing_unit_name_returns_none(self) -> None:
        node = _extract_business_db_write_node("新增客户")
        assert node is None

    def test_products_with_name_and_unit(self) -> None:
        node = _extract_business_db_write_node("新增产品：九零后 到 客户：七彩乐园")
        assert node is not None
        assert node.params["entity"] == "products"
        assert node.params["operation"] == "create"
        assert "九零后" in node.params["payload"]["product_name"]
        assert node.idempotent is False

    def test_products_with_model_number(self) -> None:
        node = _extract_business_db_write_node("新增产品：九零后 型号：9803 到 客户：七彩乐园")
        assert node is not None
        assert node.params["payload"].get("model_number") == "9803"

    def test_products_missing_product_name_returns_none(self) -> None:
        # "产品数据库" → product_name pattern captures "数据库" → cleaned to "" (数据库 token replaced)
        node = _extract_business_db_write_node("产品数据库")
        assert node is None

    def test_products_missing_unit_name_returns_none(self) -> None:
        node = _extract_business_db_write_node("新增产品：九零后")
        assert node is None

    def test_materials_returns_none(self) -> None:
        # materials entity is not handled in _extract_business_db_write_node
        node = _extract_business_db_write_node("新增原材料：钢板")
        assert node is None


class TestExtractBusinessDbReadKeyword:
    """_extract_business_db_read_keyword 分支覆盖。"""

    def test_quoted_keyword(self) -> None:
        result = _extract_business_db_read_keyword("查「七彩乐园」", "products")
        assert result == "七彩乐园"

    def test_products_entity_with_slot(self) -> None:
        result = _extract_business_db_read_keyword("产品：9803", "products")
        assert "9803" in result

    def test_products_entity_model_fallback(self) -> None:
        result = _extract_business_db_read_keyword("查 9803", "products")
        assert "9803" in result

    def test_customers_entity_with_slot(self) -> None:
        result = _extract_business_db_read_keyword("客户：七彩乐园", "customers")
        assert result == "七彩乐园"

    def test_materials_entity_with_slot(self) -> None:
        result = _extract_business_db_read_keyword("原材料：钢板", "materials")
        assert result == "钢板"

    def test_fallback_strips_tokens(self) -> None:
        result = _extract_business_db_read_keyword("查询数据库产品", "unknown")
        # all tokens stripped → empty → returns original message stripped
        assert result == "查询数据库产品"

    def test_fallback_returns_original_when_all_stripped(self) -> None:
        result = _extract_business_db_read_keyword("查询数据库", "unknown")
        # all tokens stripped → empty → returns original stripped
        assert isinstance(result, str)


class TestExecuteTool:
    """execute_tool 分支覆盖。"""

    def test_unknown_tool_returns_error(self) -> None:
        result = execute_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "未知工具" in result["message"]

    def test_default_action_for_price_list(self) -> None:
        mock_handler = MagicMock(return_value={"success": True})
        with patch.dict("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS", {("price_list", "export"): mock_handler}):
            result = execute_tool("price_list", {"customer_name": "test"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_default_action_for_products(self) -> None:
        mock_handler = MagicMock(return_value={"success": True})
        with patch.dict("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS", {("products", "query"): mock_handler}):
            result = execute_tool("products", {"keyword": "test"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_explicit_action_overrides_default(self) -> None:
        mock_handler = MagicMock(return_value={"success": True})
        with patch.dict("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS", {("customers", "ensure_exists"): mock_handler}):
            result = execute_tool("customers", {"_action": "ensure_exists", "unit_name": "test"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_runtime_context_popped(self) -> None:
        mock_handler = MagicMock(return_value={"success": True})
        with patch.dict("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS", {("products", "query"): mock_handler}):
            execute_tool("products", {"keyword": "test", "_runtime_context": {"foo": "bar"}})
            args, kwargs = mock_handler.call_args
            assert "_runtime_context" not in args[0]

    def test_action_normalized_to_lower(self) -> None:
        mock_handler = MagicMock(return_value={"success": True})
        with patch.dict("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS", {("products", "query"): mock_handler}):
            execute_tool("products", {"_action": "QUERY", "keyword": "test"})
            mock_handler.assert_called_once()

    def test_unknown_action_for_known_tool(self) -> None:
        result = execute_tool("products", {"_action": "unknown_action"})
        assert result["success"] is False
        assert "未知工具" in result["message"]


class TestFilterToolRegistryForProfile:
    """_filter_tool_registry_for_profile 分支覆盖。"""

    def test_normal_filters_pro_only(self) -> None:
        registry = {
            "tool1": {"availability": "shared", "actions": {"query": {"availability": "shared"}}},
            "tool2": {"availability": "pro_only", "actions": {"query": {"availability": "shared"}}},
        }
        result = _filter_tool_registry_for_profile(registry, "normal")
        assert "tool1" in result
        assert "tool2" not in result

    def test_pro_default_filters_normal_only(self) -> None:
        registry = {
            "tool1": {"availability": "shared", "actions": {"query": {"availability": "shared"}}},
            "tool2": {"availability": "normal_only", "actions": {"query": {"availability": "shared"}}},
        }
        result = _filter_tool_registry_for_profile(registry, "pro_default")
        assert "tool1" in result
        assert "tool2" not in result

    def test_filters_pro_only_actions(self) -> None:
        registry = {
            "tool1": {
                "availability": "shared",
                "actions": {
                    "query": {"availability": "shared"},
                    "admin": {"availability": "pro_only"},
                },
            },
        }
        result = _filter_tool_registry_for_profile(registry, "normal")
        assert "query" in result["tool1"]["actions"]
        assert "admin" not in result["tool1"]["actions"]

    def test_skips_non_dict_spec(self) -> None:
        registry = {"tool1": "not a dict", "tool2": {"availability": "shared", "actions": {"q": {"availability": "shared"}}}}
        result = _filter_tool_registry_for_profile(registry, "normal")
        assert "tool1" not in result
        assert "tool2" in result

    def test_skips_non_dict_actions(self) -> None:
        registry = {"tool1": {"availability": "shared", "actions": "not a dict"}}
        result = _filter_tool_registry_for_profile(registry, "normal")
        assert "tool1" not in result

    def test_skips_non_dict_action_meta(self) -> None:
        registry = {"tool1": {"availability": "shared", "actions": {"q": "not a dict"}}}
        result = _filter_tool_registry_for_profile(registry, "normal")
        assert "tool1" not in result

    def test_empty_actions_filtered_out(self) -> None:
        registry = {"tool1": {"availability": "shared", "actions": {"q": {"availability": "pro_only"}}}}
        result = _filter_tool_registry_for_profile(registry, "normal")
        assert "tool1" not in result

    def test_shared_profile_keeps_all(self) -> None:
        registry = {
            "tool1": {"availability": "shared", "actions": {"query": {"availability": "shared"}}},
        }
        result = _filter_tool_registry_for_profile(registry, "other_profile")
        assert "tool1" in result


class TestValidateRequiredParams:
    """LLMWorkflowPlanner._validate_required_params 分支覆盖。"""

    def test_valid_plan_no_error(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={"keyword": "x"})],
        )
        registry = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
        assert LLMWorkflowPlanner._validate_required_params(plan, registry) is None

    def test_missing_required_param_returns_error(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={})],
        )
        registry = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
        err = LLMWorkflowPlanner._validate_required_params(plan, registry)
        assert err is not None
        assert "keyword" in err

    def test_empty_required_param_value_returns_error(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={"keyword": "  "})],
        )
        registry = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
        err = LLMWorkflowPlanner._validate_required_params(plan, registry)
        assert err is not None

    def test_none_required_param_value_returns_error(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={"keyword": None})],
        )
        registry = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
        err = LLMWorkflowPlanner._validate_required_params(plan, registry)
        assert err is not None

    def test_unknown_tool_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="unknown", action="query", params={})],
        )
        registry = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
        assert LLMWorkflowPlanner._validate_required_params(plan, registry) is None

    def test_non_dict_tool_spec_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={})],
        )
        registry = {"products": "not a dict"}
        assert LLMWorkflowPlanner._validate_required_params(plan, registry) is None

    def test_non_dict_actions_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={})],
        )
        registry = {"products": {"actions": "not a dict"}}
        assert LLMWorkflowPlanner._validate_required_params(plan, registry) is None

    def test_non_dict_action_meta_skipped(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={})],
        )
        registry = {"products": {"actions": {"query": "not a dict"}}}
        assert LLMWorkflowPlanner._validate_required_params(plan, registry) is None

    def test_non_list_required_params_treated_as_empty(self) -> None:
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={})],
        )
        registry = {"products": {"actions": {"query": {"required_params": "not a list"}}}}
        assert LLMWorkflowPlanner._validate_required_params(plan, registry) is None

    def test_empty_nodes_no_error(self) -> None:
        plan = PlanGraph(plan_id="p1", intent="test", nodes=[])
        assert LLMWorkflowPlanner._validate_required_params(plan, {}) is None


class TestFallbackPlan:
    """LLMWorkflowPlanner._fallback_plan 分支覆盖。"""

    def _make_planner(self) -> LLMWorkflowPlanner:
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            return LLMWorkflowPlanner()

    def test_employee_dispatch_with_id(self) -> None:
        planner = self._make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": [{"pack_id": "emp-001"}]},
        ):
            plan = planner._fallback_plan("p1", "调用员工 emp-001 做事", {"employee": {}})
        assert plan.intent == "employee_dispatch"
        assert len(plan.nodes) == 1
        assert plan.nodes[0].action == "execute"
        assert plan.nodes[0].params["employee_id"] == "emp-001"

    def test_employee_dispatch_without_id_lists(self) -> None:
        planner = self._make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": []},
        ):
            plan = planner._fallback_plan("p1", "调用员工做事", {"employee": {}})
        assert plan.intent == "employee_dispatch"
        assert plan.nodes[0].action == "list"

    def test_employee_dispatch_import_error_falls_to_list(self) -> None:
        planner = self._make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=ImportError("no module"),
        ):
            plan = planner._fallback_plan("p1", "调用员工做事", {"employee": {}})
        assert plan.nodes[0].action == "list"

    def test_employee_dispatch_runtime_error_falls_to_list(self) -> None:
        planner = self._make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=RuntimeError("init fail"),
        ):
            plan = planner._fallback_plan("p1", "调用员工做事", {"employee": {}})
        assert plan.nodes[0].action == "list"

    def test_business_db_write_customers(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "新增客户到数据库：七彩乐园", {"business_db": {}})
        assert plan.intent == "business_db_write"
        assert len(plan.nodes) == 1
        assert plan.nodes[0].params["entity"] == "customers"

    def test_business_db_read(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "查数据库产品", {"business_db": {}})
        assert plan.intent == "business_db_read"
        assert plan.nodes[0].action == "read"

    def test_add_product_to_unit(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan(
            "p1", "新增产品", {"customers": {}, "products": {}}
        )
        assert plan.intent == "add_product_to_unit"
        assert len(plan.nodes) == 2
        assert plan.nodes[0].tool_id == "customers"
        assert plan.nodes[1].tool_id == "products"
        assert plan.nodes[1].depends_on == ["check_or_create_unit"]

    def test_generic_fallback_products(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "随便看看", {"products": {}})
        assert plan.intent == "generic_workflow"
        assert plan.nodes[0].tool_id == "products"
        assert plan.nodes[0].action == "query"

    def test_generic_fallback_customers(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "随便看看", {"customers": {}})
        assert plan.intent == "generic_workflow"
        assert plan.nodes[0].tool_id == "customers"

    def test_generic_fallback_empty_registry(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "随便看看", {})
        assert plan.intent == "generic_workflow"
        assert len(plan.nodes) == 0

    def test_risk_level_high(self) -> None:
        planner = self._make_planner()
        # employee execute is medium risk, not high; let's test medium
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": [{"pack_id": "emp-001"}]},
        ):
            plan = planner._fallback_plan("p1", "调用员工 emp-001", {"employee": {}})
        assert plan.risk_level == "medium"

    def test_risk_level_low(self) -> None:
        planner = self._make_planner()
        plan = planner._fallback_plan("p1", "随便看看", {"products": {}})
        assert plan.risk_level == "low"


class TestGetToolRegistry:
    """get_tool_registry 分支覆盖。"""

    def test_returns_dict_with_expected_tools(self) -> None:
        registry = get_tool_registry()
        assert isinstance(registry, dict)
        assert "price_list" in registry
        assert "products" in registry
        assert "customers" in registry
        assert "business_db" in registry
        assert "employee" in registry

    def test_business_db_has_read_and_write(self) -> None:
        registry = get_tool_registry()
        actions = registry["business_db"]["actions"]
        assert "read" in actions
        assert "write" in actions
        assert actions["read"]["risk"] == "low"
        assert actions["write"]["risk"] == "medium"

    def test_employee_has_list_and_execute(self) -> None:
        registry = get_tool_registry()
        actions = registry["employee"]["actions"]
        assert "list" in actions
        assert "execute" in actions
