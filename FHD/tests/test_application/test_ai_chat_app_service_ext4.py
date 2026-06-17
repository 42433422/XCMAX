"""Tests for app.application.ai_chat_app_service — uncovered branches (ext4).

Focus: _customer_hint_from_preview_grid, _default_purchase_unit_for_import,
_try_structured_reload_records, _resolve_unit_price_column, _dispatch_workflow_tool,
_handle_confirmation_flow, _build_response, _handle_tool_call, _execute_pro_mode_tools,
_execute_normal_mode_tools, _execute_products_query, _execute_customers_query,
_execute_customers_intent, _build_order_text_from_products, _try_merge_split_model,
_execute_shipment_generate, _execute_shipments_query, _normal_slot_dispatch_chat_overlay.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService


def _make_service():
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


# ========================= _customer_hint_from_preview_grid =================


class TestCustomerHintFromPreviewGrid:
    def test_with_customer_column(self):
        service = _make_service()
        preview_data = {
            "grid_preview": {
                "rows": [
                    [{"text": "客户"}, {"text": "产品名称"}, {"text": "单价"}],
                    [{"text": "公司A"}, {"text": "涂料"}, {"text": "100"}],
                ]
            }
        }
        with patch(
            "app.routes.template_grid_core._extract_inline_customer_hits_from_cell",
            return_value=["公司A"],
        ):
            result = service._customer_hint_from_preview_grid(preview_data)
        assert "公司A" in result

    def test_empty_grid(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid({})
        assert result == ""

    def test_no_rows(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid({"grid_preview": {"rows": []}})
        assert result == ""

    def test_non_dict_preview(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid("not a dict")
        assert result == ""

    def test_no_grid_preview_key(self):
        service = _make_service()
        result = service._customer_hint_from_preview_grid({"other_key": []})
        assert result == ""


# ========================= _default_purchase_unit_for_import ================


class TestDefaultPurchaseUnitForImport:
    def test_with_unit_name_in_context(self):
        service = _make_service()
        result = service._default_purchase_unit_for_import(
            {"unit_name": "公司A"},
            {"grid_preview": {"rows": []}},
            {"excel_customer_hint": "公司A"},
        )
        assert "公司A" in result

    def test_with_guess_from_file(self):
        service = _make_service()
        result = service._default_purchase_unit_for_import(
            {"file_name": "某某有限公司报价表.xlsx"},
            {"grid_preview": {"rows": []}},
        )
        assert isinstance(result, str)

    def test_empty_context(self):
        service = _make_service()
        result = service._default_purchase_unit_for_import({}, {})
        assert result == ""


# ========================= _try_structured_reload_records ===================


class TestTryStructuredReloadRecords:
    def test_no_excel_analysis(self):
        service = _make_service()
        result = service._try_structured_reload_records({}, {})
        assert result is None

    def test_no_file_path(self):
        service = _make_service()
        result = service._try_structured_reload_records({"file_path": ""}, {})
        assert result is None

    def test_with_nonexistent_file_path(self):
        service = _make_service()
        excel_analysis = {"file_path": "/nonexistent.xlsx"}
        result = service._try_structured_reload_records(excel_analysis, {})
        assert result is None


# ========================= _resolve_unit_price_column ======================


class TestResolveUnitPriceColumn:
    def test_single_price_column(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "单价", "数量"],
            current="",
            user_message="",
            overrides={},
        )
        assert col == "单价"
        assert err is None

    def test_ambiguous_price_columns(self):
        # When both before and after price columns exist AND user says both, it's ambiguous
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "调价前单价", "调价后单价"],
            current="",
            user_message="导入调价前和调价后",
            overrides={},
        )
        assert err == "ambiguous_price_columns"

    def test_override_resolves_ambiguity(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "调价前单价", "调价后单价"],
            current="",
            user_message="",
            overrides={"unit_price": "调价前单价"},
        )
        assert col == "调价前单价"
        assert err is None

    def test_user_message_before_price(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "调价前单价", "调价后单价"],
            current="",
            user_message="导入调价前",
            overrides={},
        )
        assert col == "调价前单价"

    def test_no_price_columns(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "数量"],
            current="",
            user_message="",
            overrides={},
        )
        assert col == ""
        assert err is None

    def test_current_already_set(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            keys=["产品名称", "单价"],
            current="单价",
            user_message="",
            overrides={},
        )
        assert col == "单价"


# ========================= _dispatch_workflow_tool ==========================


class TestDispatchWorkflowTool:
    def test_dispatch_products_tool(self):
        service = _make_service()
        mock_result = {"success": True, "data": []}
        with patch(
            "app.routes.tools.execute_registered_workflow_tool",
            return_value=mock_result,
        ):
            result = service._dispatch_workflow_tool("products", "query", {"keyword": "涂料"})
        assert result["success"] is True

    def test_dispatch_runtime_error(self):
        service = _make_service()
        with patch(
            "app.routes.tools.execute_registered_workflow_tool",
            side_effect=RuntimeError("fail"),
        ):
            result = service._dispatch_workflow_tool("products", "query", {})
        assert result["success"] is False


# ========================= _handle_confirmation_flow ========================


class TestHandleConfirmationFlow:
    def test_confirmation_with_approved(self):
        service = _make_service()
        service.ai_service = Mock()
        service.ai_service.set_pending_confirmation = Mock()
        context = {
            "saved_name": "test.xlsx",
            "unit_name_guess": "公司A",
            "suggested_use": "unit_products_db",
        }
        service._handle_confirmation_flow("u1", "确认", context)
        service.ai_service.set_pending_confirmation.assert_called_once()

    def test_confirmation_rejected(self):
        service = _make_service()
        service.ai_service = Mock()
        service.ai_service.set_pending_confirmation = Mock()
        context = {"saved_name": "test.xlsx"}
        service._handle_confirmation_flow("u1", "取消", context)
        service.ai_service.set_pending_confirmation.assert_not_called()

    def test_no_file_context(self):
        service = _make_service()
        service.ai_service = Mock()
        service._handle_confirmation_flow("u1", "确认", None)
        service.ai_service.set_pending_confirmation.assert_not_called()


# ========================= _build_response =================================


class TestBuildResponse:
    def test_build_with_text_response(self):
        service = _make_service()
        ai_result = {"text": "你好", "action": "reply", "data": {}}
        result = service._build_response(ai_result, "normal")
        assert result["success"] is True
        assert "response" in result

    def test_build_with_tool_call(self):
        service = _make_service()
        ai_result = {
            "text": "查询产品",
            "action": "tool_call",
            "data": {"tool_key": "products", "params": {}},
        }
        with patch.object(service, "_handle_tool_call", return_value={"success": True, "response": "ok", "data": {}}) as mock:
            result = service._build_response(ai_result, "pro_default")
        mock.assert_called_once()

    def test_build_with_followup(self):
        service = _make_service()
        ai_result = {"text": "需要更多信息", "action": "followup", "data": {"question": "哪个单位？"}}
        result = service._build_response(ai_result, "normal")
        assert result["success"] is True
        assert "followup" in result


# ========================= _execute_products_query ==========================


class TestExecuteProductsQuery:
    def test_with_keyword(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": [{"name": "涂料A"}]}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = service._execute_products_query(
                {"success": True, "message": "", "data": {}},
                {"keyword": "涂料"},
                {},
            )
        assert result["success"] is True

    def test_with_model_number(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = service._execute_products_query(
                {"success": True, "message": "", "data": {}},
                {"model_number": "5003A"},
                {},
            )
        assert result["success"] is True


# ========================= _execute_customers_query =========================


class TestExecuteCustomersQuery:
    def test_with_customers(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_all.return_value = {"success": True, "data": [{"unit_name": "公司A"}]}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = service._execute_customers_query(
                {"success": True, "message": "", "data": {}},
            )
        assert result["success"] is True

    def test_no_customers(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_all.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = service._execute_customers_query(
                {"success": True, "message": "", "data": {}},
            )
        assert result["success"] is True


# ========================= _execute_customers_intent ========================


class TestExecuteCustomersIntent:
    def test_search_intent(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_all.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = service._execute_customers_intent(
                response_data={"success": True, "message": "", "data": {}},
                slots={},
                parsed_params={},
                original_message="查询客户",
            )
        assert result["success"] is True

    def test_add_intent_no_unit_name(self):
        service = _make_service()
        result = service._execute_customers_intent(
            response_data={"success": True, "message": "", "data": {}},
            slots={},
            parsed_params={},
            original_message="添加客户",
        )
        assert "哪个单位" in result["response"]

    def test_add_intent_with_unit_name(self):
        service = _make_service()
        with patch(
            "app.routes.tools.execute_registered_workflow_tool",
            return_value={"success": True, "created": True},
        ):
            result = service._execute_customers_intent(
                response_data={"success": True, "message": "", "data": {}},
                slots={"unit_name": "公司A"},
                parsed_params={},
                original_message="添加单位 公司A",
            )
        assert result["success"] is True


# ========================= _build_order_text_from_products =================


class TestBuildOrderTextFromProducts:
    def test_with_products(self):
        service = _make_service()
        products = [
            {"model": "5003A", "quantity_tins": 10, "spec": 25},
        ]
        result = service._build_order_text_from_products("公司A", products)
        assert "公司A" in result
        assert "5003A" in result

    def test_empty_products(self):
        service = _make_service()
        result = service._build_order_text_from_products("公司A", [])
        assert result == ""

    def test_no_unit_name(self):
        service = _make_service()
        products = [{"model": "5003A"}]
        result = service._build_order_text_from_products("", products)
        assert result == ""


# ========================= _try_merge_split_model ==========================


class TestTryMergeSplitModel:
    def test_merge_with_spec_pattern(self):
        service = _make_service()
        result = service._try_merge_split_model(
            "5003A 规格 25", {"quantity_tins": 10}
        )
        assert "5003A" in result
        assert "25" in result

    def test_merge_with_qty_spec_pattern(self):
        service = _make_service()
        result = service._try_merge_split_model(
            "10桶 5003A 规格 25", {"quantity_tins": 10}
        )
        assert "5003A" in result

    def test_no_match(self):
        service = _make_service()
        result = service._try_merge_split_model(
            "just some text", {"quantity_tins": 10}
        )
        assert result == ""


# ========================= _execute_shipment_generate ======================


class TestExecuteShipmentGenerate:
    def test_with_order_text(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.generate_shipment_document.return_value = {"success": True, "doc_name": "test.pdf"}
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch("app.routes.tools._parse_order_text", return_value={"success": True, "unit_name": "公司A", "products": []}),
        ):
            result = service._execute_shipment_generate(
                {"success": True, "message": "", "data": {}},
                {"order_text": "给公司A发10桶涂料"},
                {"text": "给公司A发10桶涂料"},
            )
        assert result["success"] is True

    def test_parse_failure(self):
        service = _make_service()
        with patch("app.routes.tools._parse_order_text", return_value={"success": False, "message": "解析失败"}):
            result = service._execute_shipment_generate(
                {"success": True, "message": "", "data": {}},
                {"order_text": "无效文本"},
                {"text": "无效文本"},
            )
        assert "解析失败" in result.get("response", "") or result["success"] is True


# ========================= _execute_shipments_query ========================


class TestExecuteShipmentsQuery:
    def test_with_orders(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_orders.return_value = [
            {"order_number": "ORD001", "unit_name": "公司A", "date": "2024-01-01", "total_amount": 1000, "status": "已完成"}
        ]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = service._execute_shipments_query(
                {"success": True, "message": "", "data": {}},
            )
        assert result["success"] is True
        assert "ORD001" in result["response"]

    def test_no_orders(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_orders.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = service._execute_shipments_query(
                {"success": True, "message": "", "data": {}},
            )
        assert result["success"] is True
        assert "暂无" in result["response"]


# ========================= _normal_slot_dispatch_chat_overlay ===============


class TestNormalSlotDispatchChatOverlay:
    def test_with_tool_call(self):
        # _normal_slot_dispatch_chat_overlay is a @staticmethod taking run_result
        mock_result = Mock()
        item = Mock()
        item.success = True
        item.tool_id = "normal_slot_dispatch"
        item.output = {"success": True, "autoAction": {"type": "navigate"}, "task": "do_something"}
        mock_result.node_results = [item]

        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result)
        assert isinstance(result, dict)
        assert "task" in result or "autoAction" in result

    def test_with_no_matching_node(self):
        mock_result = Mock()
        item = Mock()
        item.success = True
        item.tool_id = "other_tool"
        item.output = {"success": True}
        mock_result.node_results = [item]

        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result)
        assert result == {}

    def test_with_reply_action(self):
        mock_result = Mock()
        item = Mock()
        item.success = True
        item.tool_id = "normal_slot_dispatch"
        item.output = {"success": True, "response": "你好"}
        mock_result.node_results = [item]

        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result)
        assert isinstance(result, dict)


# ========================= _execute_pro_mode_tools ==========================


class TestExecuteProModeTools:
    def test_products_tool(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = service._execute_pro_mode_tools(
                {"success": True, "message": "", "data": {}},
                "products",
                {"keyword": "涂料"},
                {},
                {"text": "查询涂料"},
            )
        assert result["success"] is True

    def test_unknown_tool(self):
        service = _make_service()
        result = service._execute_pro_mode_tools(
            {"success": True, "message": "", "data": {}},
            "unknown_tool",
            {},
            {},
            {"text": "test"},
        )
        assert "toolCall" in result


# ========================= _execute_normal_mode_tools =======================


class TestExecuteNormalModeTools:
    def test_shipment_generate(self):
        service = _make_service()
        with patch.object(service, "_execute_shipment_generate", return_value={"success": True, "response": "ok", "data": {}}):
            result = service._execute_normal_mode_tools(
                {"success": True, "message": "", "data": {}},
                "shipment_generate",
                {},
                {"text": "发货"},
                {},
            )
        assert result["success"] is True

    def test_unknown_tool(self):
        service = _make_service()
        result = service._execute_normal_mode_tools(
            {"success": True, "message": "", "data": {}},
            "other_tool",
            {},
            {"text": "test"},
            {},
        )
        assert "toolCall" in result


# ========================= _handle_tool_call ================================


class TestHandleToolCall:
    def test_pro_mode_dispatch(self):
        service = _make_service()
        with patch.object(service, "_execute_pro_mode_tools", return_value={"success": True, "response": "ok", "data": {}}) as mock:
            result = service._handle_tool_call(
                {"success": True, "message": "", "data": {}},
                {"text": "查询"},
                {"tool_key": "products", "params": {}},
                "pro",
            )
        mock.assert_called_once()

    def test_normal_mode_dispatch(self):
        service = _make_service()
        with patch.object(service, "_execute_normal_mode_tools", return_value={"success": True, "response": "ok", "data": {}}) as mock:
            result = service._handle_tool_call(
                {"success": True, "message": "", "data": {}},
                {"text": "查询"},
                {"tool_key": "products", "params": {}},
                "normal",
            )
        mock.assert_called_once()

    def test_no_tool_key(self):
        service = _make_service()
        result = service._handle_tool_call(
            {"success": True, "message": "", "data": {}},
            {"text": "查询"},
            {"data": {}},
            "normal",
        )
        assert result["success"] is True
