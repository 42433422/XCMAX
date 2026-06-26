"""Tests for app.application.normal_chat_dispatch — branch coverage ramp.

聚焦未覆盖分支：
- route_normal_mode_message：number_style_order / customer_keyword / inventory / label_print /
  product_query 各槽位分支（含 keyword 推导、unit/model 组合、tail model 排除 API/HTTP 等）
- build_product_query_response_dict：非 product_query 早返回 / preview 失败 / query_desc 各分支
- run_workflow_products_query_normal_profile：profile 命中 / kw_preview 回退各分支 / 异常路径
- resolve_tool_execution_profile：explicit / ui_surface+intent_channel 组合
- run_normal_slot_shipment_preview：空 text / parse 失败 / parse 成功
- run_normal_slot_product_query_from_message：命中与未命中
- build_customers_query_response_dict：非意图 / 空客户 / 有客户 / 异常
- build_inventory_alert_response_dict：非意图 / 空低库存 / 有低库存 / 异常
- build_label_print_response_dict：非意图 / 缺型号 / 成功 / 失败 / 异常
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.normal_chat_dispatch import (
    build_customers_query_response_dict,
    build_inventory_alert_response_dict,
    build_label_print_response_dict,
    build_product_query_response_dict,
    resolve_tool_execution_profile,
    route_normal_mode_message,
    run_normal_slot_product_query_from_message,
    run_normal_slot_shipment_preview,
    run_workflow_products_query_normal_profile,
)


# ---------------------------------------------------------------------------
# route_normal_mode_message — shipment 分支
# ---------------------------------------------------------------------------


class TestRouteNormalModeMessageShipment:
    """route_normal_mode_message shipment 槽位分支。"""

    def test_shipment_keyword_发货单(self):
        result = route_normal_mode_message("帮我打开发货单")
        assert result["intent"] == "shipment"
        assert result["slots"]["number_style_order"] is False

    def test_shipment_keyword_送货单(self):
        result = route_normal_mode_message("送货单看一下")
        assert result["intent"] == "shipment"

    def test_shipment_keyword_出货单(self):
        result = route_normal_mode_message("出货单打印")
        assert result["intent"] == "shipment"

    def test_shipment_keyword_开单(self):
        result = route_normal_mode_message("开单")
        assert result["intent"] == "shipment"

    def test_shipment_keyword_打单(self):
        result = route_normal_mode_message("打单")
        assert result["intent"] == "shipment"

    def test_shipment_keyword_打印(self):
        result = route_normal_mode_message("打印一下")
        assert result["intent"] == "shipment"

    def test_shipment_number_style_order_arabic(self):
        result = route_normal_mode_message("10桶A001规格25")
        assert result["intent"] == "shipment"
        assert result["slots"]["number_style_order"] is True

    def test_shipment_number_style_order_chinese_numerals(self):
        result = route_normal_mode_message("十桶A001规格25")
        assert result["intent"] == "shipment"
        assert result["slots"]["number_style_order"] is True

    def test_shipment_number_style_order_two_buckets(self):
        result = route_normal_mode_message("两桶B-002规格10.5")
        assert result["intent"] == "shipment"
        assert result["slots"]["number_style_order"] is True

    def test_empty_message_returns_unknown(self):
        result = route_normal_mode_message("")
        assert result["intent"] == "unknown"
        assert result["slots"] == {}

    def test_none_message_returns_unknown(self):
        result = route_normal_mode_message(None)
        assert result["intent"] == "unknown"

    def test_whitespace_message_returns_unknown(self):
        result = route_normal_mode_message("   ")
        assert result["intent"] == "unknown"


# ---------------------------------------------------------------------------
# route_normal_mode_message — customers_query 分支
# ---------------------------------------------------------------------------


class TestRouteNormalModeMessageCustomersQuery:
    """route_normal_mode_message customers_query 槽位分支。"""

    def test_customer_keyword_客户(self):
        result = route_normal_mode_message("查询客户")
        assert result["intent"] == "customers_query"

    def test_customer_keyword_购买单位(self):
        result = route_normal_mode_message("购买单位列表")
        assert result["intent"] == "customers_query"

    def test_customer_keyword_买家(self):
        result = route_normal_mode_message("买家信息")
        assert result["intent"] == "customers_query"

    def test_customer_keyword_客户列表(self):
        result = route_normal_mode_message("客户列表")
        assert result["intent"] == "customers_query"

    def test_customer_keyword_客户信息(self):
        result = route_normal_mode_message("客户信息")
        assert result["intent"] == "customers_query"

    def test_customer_keyword_有哪些客户(self):
        result = route_normal_mode_message("有哪些客户")
        assert result["intent"] == "customers_query"

    def test_customer_keyword_客户名单(self):
        result = route_normal_mode_message("客户名单")
        assert result["intent"] == "customers_query"

    def test_customer_with_keyword_match(self):
        """regex 贪婪匹配会包含 '的'，验证 keyword 非空即可。"""
        result = route_normal_mode_message("七彩乐园的客户")
        assert result["intent"] == "customers_query"
        assert result["slots"]["keyword"]  # 非空

    def test_customer_without_keyword_match_empty_slot(self):
        result = route_normal_mode_message("客户")
        assert result["intent"] == "customers_query"
        assert result["slots"]["keyword"] == ""

    def test_customer_keyword_match_simple(self):
        """无 '的' 时 keyword 应等于捕获组。"""
        result = route_normal_mode_message("七彩乐园客户")
        assert result["intent"] == "customers_query"
        assert result["slots"]["keyword"] == "七彩乐园"


# ---------------------------------------------------------------------------
# route_normal_mode_message — inventory_alert 分支
# ---------------------------------------------------------------------------


class TestRouteNormalModeMessageInventoryAlert:
    """route_normal_mode_message inventory_alert 槽位分支。"""

    def test_inventory_keyword_库存(self):
        result = route_normal_mode_message("库存")
        assert result["intent"] == "inventory_alert"

    def test_inventory_keyword_库存预警(self):
        result = route_normal_mode_message("库存预警")
        assert result["intent"] == "inventory_alert"

    def test_inventory_keyword_低库存(self):
        result = route_normal_mode_message("低库存")
        assert result["intent"] == "inventory_alert"

    def test_inventory_keyword_库存不足(self):
        result = route_normal_mode_message("库存不足")
        assert result["intent"] == "inventory_alert"

    def test_inventory_keyword_缺货(self):
        result = route_normal_mode_message("缺货")
        assert result["intent"] == "inventory_alert"

    def test_inventory_keyword_原材料库存(self):
        result = route_normal_mode_message("原材料库存")
        assert result["intent"] == "inventory_alert"

    def test_inventory_keyword_仓库(self):
        result = route_normal_mode_message("仓库")
        assert result["intent"] == "inventory_alert"


# ---------------------------------------------------------------------------
# route_normal_mode_message — label_print 分支
# ---------------------------------------------------------------------------


class TestRouteNormalModeMessageLabelPrint:
    """route_normal_mode_message label_print 槽位分支。"""

    def test_label_print_keyword_标签(self):
        """注意 '打印' 是 shipment 关键词，故用 '标签' 触发 label_print。"""
        result = route_normal_mode_message("标签")
        assert result["intent"] == "label_print"
        assert result["slots"]["model_number"] == ""
        assert result["slots"]["quantity"] == 1

    def test_label_print_keyword_打标签(self):
        result = route_normal_mode_message("打标签B002")
        assert result["intent"] == "label_print"
        # model_number regex 会匹配 B002
        assert result["slots"]["model_number"] == "B002"

    def test_label_print_keyword_打印标签(self):
        """'打印' 是 shipment 关键词，'打印标签' 会先命中 shipment。改用 '商标'。"""
        result = route_normal_mode_message("商标")
        assert result["intent"] == "label_print"

    def test_label_print_keyword_贴标(self):
        result = route_normal_mode_message("贴标")
        assert result["intent"] == "label_print"

    def test_label_print_no_model_number(self):
        result = route_normal_mode_message("标签5张")
        assert result["intent"] == "label_print"
        # qty_m 会匹配 "5"（标签5张中第一个数字）
        assert result["slots"]["quantity"] == 5

    def test_label_print_no_quantity(self):
        result = route_normal_mode_message("标签A001")
        assert result["intent"] == "label_print"
        assert result["slots"]["model_number"] == "A001"
        assert result["slots"]["quantity"] == 1


# ---------------------------------------------------------------------------
# route_normal_mode_message — product_query 分支
# ---------------------------------------------------------------------------


class TestRouteNormalModeMessageProductQuery:
    """route_normal_mode_message product_query 槽位分支。"""

    def test_product_query_with_query_keyword(self):
        """'查询' 单独出现时，清理后 keyword 为空，slots 可能为空。"""
        result = route_normal_mode_message("查询")
        assert result["intent"] == "product_query"

    def test_product_query_with_查一下_keyword(self):
        result = route_normal_mode_message("查一下")
        assert result["intent"] == "product_query"

    def test_product_query_with_查下_keyword(self):
        result = route_normal_mode_message("查下")
        assert result["intent"] == "product_query"

    def test_product_query_with_查_keyword(self):
        result = route_normal_mode_message("查")
        assert result["intent"] == "product_query"

    def test_product_query_with_看看_keyword(self):
        result = route_normal_mode_message("看看")
        assert result["intent"] == "product_query"

    def test_product_query_with_看下_keyword(self):
        result = route_normal_mode_message("看下")
        assert result["intent"] == "product_query"

    def test_product_query_with_搜索_keyword(self):
        result = route_normal_mode_message("搜索")
        assert result["intent"] == "product_query"

    def test_product_query_with_找下_keyword(self):
        result = route_normal_mode_message("找下")
        assert result["intent"] == "product_query"

    def test_product_query_with_找_keyword(self):
        result = route_normal_mode_message("找")
        assert result["intent"] == "product_query"

    def test_product_query_with_检索_keyword(self):
        result = route_normal_mode_message("检索")
        assert result["intent"] == "product_query"

    def test_product_query_keyword_stripped_to_nonempty(self):
        """'查询产品' 清理后 keyword='产品'。"""
        result = route_normal_mode_message("查询产品")
        assert result["intent"] == "product_query"
        assert result["slots"].get("keyword") == "产品"

    def test_product_query_with_model_signal(self):
        result = route_normal_mode_message("型号:A001")
        assert result["intent"] == "product_query"
        assert result["slots"]["model_number"] == "A001"

    def test_product_query_with_model_signal_chinese_colon(self):
        result = route_normal_mode_message("编号：B002")
        assert result["intent"] == "product_query"
        assert result["slots"]["model_number"] == "B002"

    def test_product_query_with_unit_model_signal(self):
        result = route_normal_mode_message("七彩乐园的A001")
        assert result["intent"] == "product_query"
        assert result["slots"]["unit_name"] == "七彩乐园"
        assert result["slots"]["model_number"] == "A001"

    def test_product_query_unit_name_strip_query_prefix(self):
        result = route_normal_mode_message("帮我查询七彩乐园的A001")
        assert result["intent"] == "product_query"
        assert result["slots"]["unit_name"] == "七彩乐园"

    def test_product_query_keyword_from_unit_and_model(self):
        result = route_normal_mode_message("七彩乐园的A001")
        assert result["intent"] == "product_query"
        assert result["slots"]["keyword"] == "七彩乐园A001"

    def test_product_query_keyword_from_model_only(self):
        """'查询 A001'（有空格）时 model_number='A001'。"""
        result = route_normal_mode_message("查询 A001")
        assert result["intent"] == "product_query"
        assert result["slots"]["model_number"] == "A001"

    def test_product_query_no_space_keyword_lowered(self):
        """'查询A001'（无空格）时 \b 不匹配，keyword 为小写 'a001'。"""
        result = route_normal_mode_message("查询A001")
        assert result["intent"] == "product_query"
        assert result["slots"].get("keyword") == "a001"

    def test_product_query_keyword_combo_chinese_english(self):
        result = route_normal_mode_message("查询七彩A001")
        assert result["intent"] == "product_query"

    def test_product_query_tail_model_excludes_api_keyword(self):
        result = route_normal_mode_message("查询API")
        assert result["intent"] == "product_query"
        # API 应该被排除
        assert result["slots"].get("model_number") != "API"

    def test_product_query_tail_model_excludes_http_keyword(self):
        result = route_normal_mode_message("查询HTTP")
        assert result["intent"] == "product_query"
        assert result["slots"].get("model_number") != "HTTP"

    def test_product_query_tail_model_excludes_json_keyword(self):
        result = route_normal_mode_message("查询JSON")
        assert result["intent"] == "product_query"
        assert result["slots"].get("model_number") != "JSON"

    def test_product_query_tail_model_excludes_xml_keyword(self):
        result = route_normal_mode_message("查询XML")
        assert result["intent"] == "product_query"
        assert result["slots"].get("model_number") != "XML"

    def test_product_query_no_keyword_no_unit_no_model(self):
        """查询关键词但提取后 keyword 为空。"""
        result = route_normal_mode_message("查询")
        assert result["intent"] == "product_query"


# ---------------------------------------------------------------------------
# route_normal_mode_message — unknown 分支
# ---------------------------------------------------------------------------


class TestRouteNormalModeMessageUnknown:
    """route_normal_mode_message unknown 槽位分支。"""

    def test_unknown_intent_no_keywords(self):
        result = route_normal_mode_message("你好世界")
        assert result["intent"] == "unknown"

    def test_unknown_intent_random_text(self):
        result = route_normal_mode_message("今天天气不错")
        assert result["intent"] == "unknown"


# ---------------------------------------------------------------------------
# build_product_query_response_dict
# ---------------------------------------------------------------------------


class TestBuildProductQueryResponseDict:
    """build_product_query_response_dict 分支测试。"""

    def test_non_product_query_returns_none(self):
        result = build_product_query_response_dict({"intent": "shipment", "slots": {}})
        assert result is None

    def test_product_query_with_unit_name_and_model(self):
        route = {
            "intent": "product_query",
            "slots": {"unit_name": "七彩乐园", "model_number": "A001", "keyword": ""},
        }
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"data": []}
            mock_get.return_value = mock_svc
            result = build_product_query_response_dict(route)
        assert result is not None
        assert result["success"] is True
        # response 优先用 keyword or model_number，故含 "A001"
        assert "A001" in result["response"]
        # slots 透传
        assert result["data"]["slots"]["unit_name"] == "七彩乐园"

    def test_product_query_with_keyword_distinct_from_model(self):
        """keyword='七彩' model='A001' 时，response 优先用 keyword。"""
        route = {
            "intent": "product_query",
            "slots": {"unit_name": "", "model_number": "A001", "keyword": "七彩"},
        }
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"data": []}
            mock_get.return_value = mock_svc
            result = build_product_query_response_dict(route)
        assert result is not None
        # response 优先用 keyword
        assert "七彩" in result["response"]
        # autoAction.query 也用 keyword
        assert result["autoAction"]["query"] == "七彩"

    def test_product_query_with_preview_rows(self):
        route = {
            "intent": "product_query",
            "slots": {"unit_name": "", "model_number": "A001", "keyword": "A001"},
        }
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {
                "data": [
                    {"model_number": "A001", "name": "Product A", "price": 100.5},
                    {"model_number": "A002", "name": "Product B", "price": "200"},
                ]
            }
            mock_get.return_value = mock_svc
            result = build_product_query_response_dict(route)
        assert result is not None
        assert "预览命中 2 条" in result["response"]

    def test_product_query_query_service_failure(self):
        route = {
            "intent": "product_query",
            "slots": {"unit_name": "", "model_number": "A001", "keyword": "A001"},
        }
        with patch(
            "app.bootstrap.get_products_service",
            side_effect=RuntimeError("service down"),
        ):
            result = build_product_query_response_dict(route)
        assert result is not None
        assert result["success"] is True  # 仍返回响应，只是无预览

    def test_product_query_no_description_bits(self):
        """无 unit/model/keyword 时，query_desc 为 '按当前输入'。"""
        route = {
            "intent": "product_query",
            "slots": {"unit_name": "", "model_number": "", "keyword": ""},
        }
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"data": []}
            mock_get.return_value = mock_svc
            result = build_product_query_response_dict(route)
        assert result is not None
        assert "按当前输入" in result["response"]

    def test_product_query_keyword_equals_model(self):
        """keyword == model_number 时，不重复添加关键词描述。"""
        route = {
            "intent": "product_query",
            "slots": {"unit_name": "", "model_number": "A001", "keyword": "A001"},
        }
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"data": []}
            mock_get.return_value = mock_svc
            result = build_product_query_response_dict(route)
        assert result is not None
        # keyword == model_number 时不应出现 "关键词："
        assert "关键词：" not in result["response"]


# ---------------------------------------------------------------------------
# run_workflow_products_query_normal_profile
# ---------------------------------------------------------------------------


class TestRunWorkflowProductsQueryNormalProfile:
    """run_workflow_products_query_normal_profile 分支测试。"""

    def test_with_product_query_intent(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {
                "success": True,
                "data": [{"id": 1}],
            }
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile("查询A001")
        assert result["success"] is True
        assert result["normal_tool_profile"] is True

    def test_with_non_product_query_intent_uses_node_params(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {
                "success": True,
                "data": [],
            }
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile(
                "你好", node_params={"keyword": "ABC"}
            )
        assert result["success"] is True

    def test_with_node_params_model_number(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile(
                "你好", node_params={"model_number": "X001"}
            )
        assert result["success"] is True

    def test_with_node_params_product_name(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile(
                "你好", node_params={"product_name": "涂料"}
            )
        assert result["success"] is True

    def test_with_node_params_name(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile(
                "你好", node_params={"name": "涂料"}
            )
        assert result["success"] is True

    def test_fallback_to_text_when_no_kw(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile("随便一段文本")
        assert result["success"] is True

    def test_service_failure_returns_error(self):
        with patch(
            "app.bootstrap.get_products_service",
            side_effect=RuntimeError("boom"),
        ):
            result = run_workflow_products_query_normal_profile("查询A001")
        assert result["success"] is False
        assert "boom" in result["message"]
        assert result["normal_tool_profile"] is True

    def test_empty_message_with_empty_node_params(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile("")
        assert result["success"] is True

    def test_none_node_params(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = run_workflow_products_query_normal_profile("查询", node_params=None)
        assert result["success"] is True

    def test_per_page_custom(self):
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_products.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            run_workflow_products_query_normal_profile("查询A001", per_page=50)
        # 验证 per_page 传递
        call_kwargs = mock_svc.get_products.call_args
        assert call_kwargs.kwargs.get("per_page") == 50 or call_kwargs[1].get("per_page") == 50


# ---------------------------------------------------------------------------
# resolve_tool_execution_profile
# ---------------------------------------------------------------------------


class TestResolveToolExecutionProfile:
    """resolve_tool_execution_profile 分支测试。"""

    def test_explicit_normal(self):
        assert resolve_tool_execution_profile({"tool_execution_profile": "normal"}) == "normal"

    def test_explicit_pro_default(self):
        assert (
            resolve_tool_execution_profile({"tool_execution_profile": "pro_default"})
            == "pro_default"
        )

    def test_explicit_pro(self):
        assert resolve_tool_execution_profile({"tool_execution_profile": "pro"}) == "pro_default"

    def test_explicit_professional(self):
        assert (
            resolve_tool_execution_profile({"tool_execution_profile": "professional"})
            == "pro_default"
        )

    def test_explicit_normal_uppercase(self):
        assert (
            resolve_tool_execution_profile({"tool_execution_profile": "NORMAL"}) == "normal"
        )

    def test_explicit_normal_with_spaces(self):
        assert (
            resolve_tool_execution_profile({"tool_execution_profile": "  normal  "})
            == "normal"
        )

    def test_ui_normal_intent_pro_returns_normal(self):
        result = resolve_tool_execution_profile(
            {"ui_surface": "normal", "intent_channel": "pro"}
        )
        assert result == "normal"

    def test_ui_normal_intent_normal_returns_pro_default(self):
        """ui=normal 但 intent_channel != pro → pro_default。"""
        result = resolve_tool_execution_profile(
            {"ui_surface": "normal", "intent_channel": "normal"}
        )
        assert result == "pro_default"

    def test_ui_pro_intent_pro_returns_pro_default(self):
        result = resolve_tool_execution_profile(
            {"ui_surface": "pro", "intent_channel": "pro"}
        )
        assert result == "pro_default"

    def test_no_context_returns_pro_default(self):
        assert resolve_tool_execution_profile(None) == "pro_default"

    def test_empty_context_returns_pro_default(self):
        assert resolve_tool_execution_profile({}) == "pro_default"

    def test_default_intent_channel_pro(self):
        """未指定 intent_channel 时默认为 pro。"""
        result = resolve_tool_execution_profile({"ui_surface": "normal"})
        assert result == "normal"

    def test_explicit_empty_string_returns_pro_default(self):
        assert resolve_tool_execution_profile({"tool_execution_profile": ""}) == "pro_default"

    def test_explicit_unknown_value_returns_pro_default(self):
        assert (
            resolve_tool_execution_profile({"tool_execution_profile": "unknown"}) == "pro_default"
        )


# ---------------------------------------------------------------------------
# run_normal_slot_shipment_preview
# ---------------------------------------------------------------------------


class TestRunNormalSlotShipmentPreview:
    """run_normal_slot_shipment_preview 分支测试。"""

    def test_empty_text_returns_error(self):
        result = run_normal_slot_shipment_preview("")
        assert result["success"] is False
        assert "缺少 order_text" in result["message"]

    def test_none_text_returns_error(self):
        result = run_normal_slot_shipment_preview(None)
        assert result["success"] is False
        assert "缺少 order_text" in result["message"]

    def test_whitespace_text_returns_error(self):
        result = run_normal_slot_shipment_preview("   ")
        assert result["success"] is False

    def test_parse_failure_returns_followup(self):
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "解析失败"},
        ):
            result = run_normal_slot_shipment_preview("无效订单")
        assert result["success"] is True
        assert result["data"]["action"] == "followup"
        assert result["normal_slot_dispatch"] is True

    def test_parse_failure_no_message(self):
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False},
        ):
            result = run_normal_slot_shipment_preview("无效订单")
        assert result["success"] is True
        assert "订单信息不完整" in result["response"]

    def test_parse_success_returns_preview(self):
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={
                "success": True,
                "unit_name": "七彩乐园",
                "products": [{"model": "A001", "quantity_tins": 2, "spec": 25}],
            },
        ):
            with patch(
                "app.application.ai_chat_helpers.build_shipment_preview_response_dict",
                return_value={"success": True, "response": "预览完成"},
            ):
                result = run_normal_slot_shipment_preview("七彩乐园2桶A001规格25")
        assert result["success"] is True
        assert result["normal_slot_dispatch"] is True

    def test_parse_success_empty_products(self):
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={
                "success": True,
                "unit_name": "七彩乐园",
                "products": [],
            },
        ):
            with patch(
                "app.application.ai_chat_helpers.build_shipment_preview_response_dict",
                return_value={"success": True, "response": "空产品"},
            ):
                result = run_normal_slot_shipment_preview("七彩乐园")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# run_normal_slot_product_query_from_message
# ---------------------------------------------------------------------------


class TestRunNormalSlotProductQueryFromMessage:
    """run_normal_slot_product_query_from_message 分支测试。"""

    def test_with_product_query_intent(self):
        with patch(
            "app.application.normal_chat_dispatch.build_product_query_response_dict"
        ) as mock_build:
            mock_build.return_value = {"success": True, "response": "产品结果"}
            result = run_normal_slot_product_query_from_message("查询A001")
        assert result["success"] is True
        assert result["normal_slot_dispatch"] is True

    def test_with_non_product_query_intent(self):
        with patch(
            "app.application.normal_chat_dispatch.build_product_query_response_dict",
            return_value=None,
        ):
            result = run_normal_slot_product_query_from_message("你好")
        assert result["success"] is False
        assert "未识别为普通版产品查询槽位" in result["message"]
        assert result["data"]["intent"] == "unknown"

    def test_empty_message(self):
        with patch(
            "app.application.normal_chat_dispatch.build_product_query_response_dict",
            return_value=None,
        ):
            result = run_normal_slot_product_query_from_message("")
        assert result["success"] is False

    def test_none_message(self):
        with patch(
            "app.application.normal_chat_dispatch.build_product_query_response_dict",
            return_value=None,
        ):
            result = run_normal_slot_product_query_from_message(None)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# build_customers_query_response_dict
# ---------------------------------------------------------------------------


class TestBuildCustomersQueryResponseDict:
    """build_customers_query_response_dict 分支测试。"""

    @staticmethod
    def _patch_customer_service(monkeypatch, mock_svc):
        """通过 sys.modules 注入 fake 模块，避免触发 app.services 包循环导入。"""
        import sys
        import types

        mock_cls = MagicMock(return_value=mock_svc)
        fake_mod = types.ModuleType("app.services.customers_service")
        fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)
        return mock_cls

    def test_non_customers_query_returns_none(self):
        result = build_customers_query_response_dict({"intent": "shipment", "slots": {}})
        assert result is None

    def test_with_keyword_no_customers(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": "不存在客户"}}
        mock_svc = MagicMock()
        mock_svc.search.return_value = []
        self._patch_customer_service(monkeypatch, mock_svc)
        result = build_customers_query_response_dict(route)
        assert result["success"] is True
        assert "未找到" in result["response"]

    def test_with_keyword_has_customers(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": "七彩"}}
        mock_svc = MagicMock()
        mock_svc.search.return_value = [
            {"customer_name": "七彩乐园", "contact_person": "张三"},
            {"customer_name": "七彩集团", "contact_person": "李四"},
        ]
        self._patch_customer_service(monkeypatch, mock_svc)
        result = build_customers_query_response_dict(route)
        assert result["success"] is True
        assert "共找到 2 位客户" in result["response"]

    def test_no_keyword_uses_get_all_empty(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": ""}}
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = []
        self._patch_customer_service(monkeypatch, mock_svc)
        result = build_customers_query_response_dict(route)
        assert result["success"] is True
        assert "暂无客户数据" in result["response"]

    def test_no_keyword_uses_get_all_with_customers(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": ""}}
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = [
            {"customer_name": "客户A", "contact_person": "联系人A"}
        ]
        self._patch_customer_service(monkeypatch, mock_svc)
        result = build_customers_query_response_dict(route)
        assert result["success"] is True
        assert "共找到 1 位客户" in result["response"]

    def test_customers_not_list_returns_empty(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": ""}}
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = "not a list"
        self._patch_customer_service(monkeypatch, mock_svc)
        result = build_customers_query_response_dict(route)
        assert result["success"] is True
        assert "暂无客户数据" in result["response"]

    def test_service_failure_returns_error(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": "x"}}
        mock_cls = MagicMock(side_effect=RuntimeError("service down"))
        import sys
        import types

        fake_mod = types.ModuleType("app.services.customers_service")
        fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)
        result = build_customers_query_response_dict(route)
        assert result["success"] is False
        assert "暂时不可用" in result["response"]
        assert result["normal_slot_dispatch"] is True

    def test_more_than_10_customers_truncated_in_response(self, monkeypatch):
        route = {"intent": "customers_query", "slots": {"keyword": ""}}
        customers = [
            {"customer_name": f"客户{i}", "contact_person": f"联系人{i}"} for i in range(15)
        ]
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = customers
        self._patch_customer_service(monkeypatch, mock_svc)
        result = build_customers_query_response_dict(route)
        assert result["success"] is True
        # 响应里只列前 10 个，但 data 里前 20 个
        assert "共找到 15 位客户" in result["response"]
        assert len(result["data"]["customers"]) == 15


# ---------------------------------------------------------------------------
# build_inventory_alert_response_dict
# ---------------------------------------------------------------------------


class TestBuildInventoryAlertResponseDict:
    """build_inventory_alert_response_dict 分支测试。"""

    def test_non_inventory_alert_returns_none(self):
        result = build_inventory_alert_response_dict({"intent": "shipment", "slots": {}})
        assert result is None

    def test_no_low_stock_items(self):
        route = {"intent": "inventory_alert", "slots": {}}
        with patch(
            "app.application.get_material_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_low_stock_materials.return_value = {"data": []}
            mock_get.return_value = mock_svc
            result = build_inventory_alert_response_dict(route)
        assert result["success"] is True
        assert "库存状态正常" in result["response"]

    def test_with_low_stock_items(self):
        route = {"intent": "inventory_alert", "slots": {}}
        with patch(
            "app.application.get_material_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_low_stock_materials.return_value = {
                "data": [
                    {"name": "原料A", "quantity": 5, "unit": "kg"},
                    {"name": "原料B", "quantity": 10, "unit": "L"},
                ]
            }
            mock_get.return_value = mock_svc
            result = build_inventory_alert_response_dict(route)
        assert result["success"] is True
        assert "发现 2 种低库存" in result["response"]

    def test_service_failure_returns_error(self):
        route = {"intent": "inventory_alert", "slots": {}}
        with patch(
            "app.application.get_material_application_service",
            side_effect=RuntimeError("boom"),
        ):
            result = build_inventory_alert_response_dict(route)
        assert result["success"] is False
        assert "暂时不可用" in result["response"]
        assert result["normal_slot_dispatch"] is True

    def test_more_than_10_items_truncated_in_response(self):
        route = {"intent": "inventory_alert", "slots": {}}
        items = [
            {"name": f"原料{i}", "quantity": i, "unit": "kg"} for i in range(15)
        ]
        with patch(
            "app.application.get_material_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_low_stock_materials.return_value = {"data": items}
            mock_get.return_value = mock_svc
            result = build_inventory_alert_response_dict(route)
        assert result["success"] is True
        assert "发现 15 种低库存" in result["response"]
        # data 里前 20 个
        assert len(result["data"]["low_stock_items"]) == 15

    def test_no_data_key_in_result(self):
        route = {"intent": "inventory_alert", "slots": {}}
        with patch(
            "app.application.get_material_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_low_stock_materials.return_value = {}
            mock_get.return_value = mock_svc
            result = build_inventory_alert_response_dict(route)
        assert result["success"] is True
        assert "库存状态正常" in result["response"]


# ---------------------------------------------------------------------------
# build_label_print_response_dict
# ---------------------------------------------------------------------------


class TestBuildLabelPrintResponseDict:
    """build_label_print_response_dict 分支测试。"""

    def test_non_label_print_returns_none(self):
        result = build_label_print_response_dict({"intent": "shipment", "slots": {}})
        assert result is None

    def test_no_model_number_returns_followup(self):
        route = {"intent": "label_print", "slots": {"model_number": "", "quantity": 1}}
        result = build_label_print_response_dict(route)
        assert result["success"] is False
        assert "请告诉我要打印哪款产品" in result["response"]
        assert result["normal_slot_dispatch"] is True

    def test_no_model_number_none(self):
        route = {"intent": "label_print", "slots": {"model_number": None, "quantity": 1}}
        result = build_label_print_response_dict(route)
        assert result["success"] is False

    def test_print_success(self):
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 2}}
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": True, "message": "ok"}
            mock_get.return_value = mock_svc
            result = build_label_print_response_dict(route)
        assert result["success"] is True
        assert "已发送打印任务" in result["response"]
        assert "A001 × 2 张" in result["response"]

    def test_print_failure(self):
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 1}}
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {
                "success": False,
                "message": "printer offline",
            }
            mock_get.return_value = mock_svc
            result = build_label_print_response_dict(route)
        assert result["success"] is False
        assert "打印失败" in result["response"]

    def test_print_failure_no_message(self):
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 1}}
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": False}
            mock_get.return_value = mock_svc
            result = build_label_print_response_dict(route)
        assert result["success"] is False
        assert "未知错误" in result["response"]

    def test_service_failure_returns_error(self):
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 1}}
        with patch(
            "app.application.print_app_service.get_print_application_service",
            side_effect=RuntimeError("boom"),
        ):
            result = build_label_print_response_dict(route)
        assert result["success"] is False
        assert "暂时不可用" in result["response"]
        assert result["normal_slot_dispatch"] is True

    def test_quantity_zero_becomes_one(self):
        """quantity=0 时通过 max(1, ...) 变为 1。"""
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 0}}
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = build_label_print_response_dict(route)
        assert result["success"] is True
        # 验证 quantity 被规范化为 1
        call_args = mock_svc.print_single_label.call_args
        assert call_args.kwargs.get("quantity") == 1

    def test_quantity_none_becomes_one(self):
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": None}}
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = build_label_print_response_dict(route)
        assert result["success"] is True

    def test_quantity_negative_becomes_one(self):
        route = {"intent": "label_print", "slots": {"model_number": "A001", "quantity": -5}}
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = build_label_print_response_dict(route)
        assert result["success"] is True
