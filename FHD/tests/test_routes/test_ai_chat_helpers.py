"""Tests for app.application.ai_chat_helpers pure helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.ai_chat_helpers import (
    _build_number_preview_items,
    _fetch_product_meta_by_models,
    _resolve_mode_scoped_user_id,
    build_shipment_preview_response_dict,
    normalize_batch_messages_payload,
    recognize_intents,
    unified_chat_single_payload,
)

# ========================= _fetch_product_meta_by_models =================


class TestFetchProductMetaByModels:
    def test_empty_models_returns_empty(self):
        result = _fetch_product_meta_by_models([])
        assert result == {}

    def test_none_models_filtered(self):
        result = _fetch_product_meta_by_models([None, "", "M1"])
        assert isinstance(result, dict)

    def test_with_model_found(self):
        mock_service = MagicMock()
        mock_service.get_products.return_value = {
            "data": [{"model_number": "M1", "name": "Widget", "price": 100}]
        }
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["M1"])
            assert "M1" in result
            assert result["M1"]["name"] == "Widget"
            assert result["M1"]["price"] == 100.0

    def test_with_model_found_with_unit(self):
        mock_service = MagicMock()
        mock_service.get_products.side_effect = [
            {"data": [{"model_number": "M1", "name": "Widget", "price": 50}]},
        ]
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["M1"], unit_name="TestUnit")
            assert "M1" in result

    def test_with_model_fallback_to_keyword(self):
        mock_service = MagicMock()
        mock_service.get_products.side_effect = [
            {"data": []},
            {"data": [{"model_number": "M1", "name": "Widget", "price": 99}]},
        ]
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["M1"])
            assert "M1" in result

    def test_with_model_no_results(self):
        mock_service = MagicMock()
        mock_service.get_products.return_value = {"data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["UNKNOWN"])
            assert result == {}

    def test_recoverable_error_returns_empty(self):
        with patch("app.bootstrap.get_products_service", side_effect=ImportError("no module")):
            result = _fetch_product_meta_by_models(["M1"])
            assert result == {}

    def test_pick_best_record_exact_match(self):
        mock_service = MagicMock()
        mock_service.get_products.return_value = {
            "data": [
                {"model_number": "M1-A", "name": "Other", "price": 10},
                {"model_number": "M1", "name": "Exact Match", "price": 20},
            ]
        }
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["M1"])
            assert result["M1"]["name"] == "Exact Match"

    def test_pick_best_record_name_contains(self):
        mock_service = MagicMock()
        mock_service.get_products.return_value = {
            "data": [
                {"model_number": "X1", "name": "M1 Widget", "price": 30},
            ]
        }
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["M1"])
            assert "M1" in result

    def test_normalized_model_key(self):
        mock_service = MagicMock()
        mock_service.get_products.return_value = {
            "data": [{"model_number": "M1", "name": "Widget", "price": 100}]
        }
        with patch("app.bootstrap.get_products_service", return_value=mock_service):
            result = _fetch_product_meta_by_models(["m-1"])
            assert "M1" in result


# ========================= _build_number_preview_items ===================


class TestBuildNumberPreviewItems:
    def test_empty_products(self):
        result = _build_number_preview_items("TestUnit", [])
        assert result["items"] == []
        assert result["grand_total"] is None

    def test_none_products(self):
        result = _build_number_preview_items("TestUnit", None)
        assert result["items"] == []

    def test_product_with_price_and_quantity(self):
        products = [
            {
                "model_number": "M1",
                "quantity_tins": 10,
                "unit_price": 5.0,
                "name": "Widget",
            }
        ]
        with patch(
            "app.application.ai_chat_helpers._fetch_product_meta_by_models", return_value={}
        ):
            result = _build_number_preview_items("TestUnit", products)
            assert len(result["items"]) == 1
            assert result["items"][0]["型号"] == "M1"
            assert result["items"][0]["桶数"] == 10
            assert result["grand_total"] == 50.0

    def test_product_with_spec_and_quantity_kg(self):
        products = [
            {
                "model_number": "M1",
                "quantity_tins": 5,
                "tin_spec": "20",
                "unit_price": 3.0,
                "name": "Widget",
            }
        ]
        with patch(
            "app.application.ai_chat_helpers._fetch_product_meta_by_models", return_value={}
        ):
            result = _build_number_preview_items("TestUnit", products)
            assert result["grand_total"] == 300.0

    def test_product_with_amount_field(self):
        products = [
            {
                "model_number": "M1",
                "amount": 200,
                "name": "Widget",
            }
        ]
        with patch(
            "app.application.ai_chat_helpers._fetch_product_meta_by_models", return_value={}
        ):
            result = _build_number_preview_items("TestUnit", products)
            assert result["grand_total"] == 200.0

    def test_product_dash_name_treated_as_empty(self):
        products = [
            {
                "model_number": "M1",
                "name": "-",
                "amount": 100,
            }
        ]
        with patch(
            "app.application.ai_chat_helpers._fetch_product_meta_by_models",
            return_value={"M1": {"name": "Real Name", "price": 50}},
        ):
            result = _build_number_preview_items("TestUnit", products)
            assert result["items"][0]["产品名称"] == "Real Name"

    def test_product_fallback_to_meta_price(self):
        products = [
            {
                "model_number": "M1",
                "quantity_tins": 2,
                "name": "Widget",
            }
        ]
        with patch(
            "app.application.ai_chat_helpers._fetch_product_meta_by_models",
            return_value={"M1": {"name": "Widget", "price": 25}},
        ):
            result = _build_number_preview_items("TestUnit", products)
            assert result["grand_total"] == 50.0

    def test_product_quantity_tins_float(self):
        products = [
            {
                "model_number": "M1",
                "quantity_tins": 2.5,
                "unit_price": 10.0,
                "name": "Widget",
            }
        ]
        with patch(
            "app.application.ai_chat_helpers._fetch_product_meta_by_models", return_value={}
        ):
            result = _build_number_preview_items("TestUnit", products)
            assert result["items"][0]["桶数"] == 2.5
            assert result["grand_total"] == 25.0


# ========================= build_shipment_preview_response_dict ==========


class TestBuildShipmentPreviewResponseDict:
    def test_basic_structure(self):
        products = [{"model_number": "M1", "quantity_tins": 5, "unit_price": 10, "name": "Widget"}]
        with patch(
            "app.application.ai_chat_helpers._build_number_preview_items",
            return_value={"items": [{"型号": "M1"}], "grand_total": 50.0},
        ):
            result = build_shipment_preview_response_dict("TestUnit", products, "order text")
            assert result["success"] is True
            assert result["task"]["type"] == "shipment_generate"
            assert "TestUnit" in result["task"]["description"]
            assert result["data"]["intent"] == "shipment_preview"

    def test_no_grand_total(self):
        with patch(
            "app.application.ai_chat_helpers._build_number_preview_items",
            return_value={"items": [], "grand_total": None},
        ):
            result = build_shipment_preview_response_dict("Unit", [], "text")
            assert "预估总价" not in result["task"]["description"]

    def test_with_grand_total(self):
        with patch(
            "app.application.ai_chat_helpers._build_number_preview_items",
            return_value={"items": [], "grand_total": 100.0},
        ):
            result = build_shipment_preview_response_dict("Unit", [], "text")
            assert "预估总价" in result["task"]["description"]


# ========================= recognize_intents =============================


class TestRecognizeIntents:
    def test_returns_expected_structure(self):
        mock_result = {
            "primary_intent": "product_query",
            "tool_key": "product_query",
            "intent_hints": ["查询"],
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "confidence": 0.8,
            "sources_used": ["rule_engine", "llm"],
        }
        with patch(
            "app.application.intent_recognition_app.recognize_intents",
            return_value=mock_result,
        ):
            result = recognize_intents("查询产品")
            assert result["primary_intent"] == "product_query"
            assert result["confidence"] == 0.8
            assert "rule_engine" in result["sources_used"]


# ========================= _resolve_mode_scoped_user_id =================


class TestResolveModeScopedUserId:
    def test_with_explicit_user_id(self):
        result = _resolve_mode_scoped_user_id("user123", "127.0.0.1", "normal")
        assert result == "user123"

    def test_with_empty_user_id(self):
        result = _resolve_mode_scoped_user_id("", "127.0.0.1", "normal")
        assert result == "user_127.0.0.1:normal"

    def test_with_none_user_id(self):
        result = _resolve_mode_scoped_user_id(None, "10.0.0.1", "default")
        assert "10.0.0.1" in result

    def test_with_empty_channel(self):
        result = _resolve_mode_scoped_user_id(None, "10.0.0.1", "")
        assert "default" in result

    def test_with_none_channel(self):
        result = _resolve_mode_scoped_user_id(None, "10.0.0.1", None)
        assert "default" in result


# ========================= normalize_batch_messages_payload ==============


class TestNormalizeBatchMessagesPayload:
    def test_with_messages_list(self):
        result = normalize_batch_messages_payload({"messages": ["hello", "world"]})
        assert result == ["hello", "world"]

    def test_with_message_list_key(self):
        result = normalize_batch_messages_payload({"message_list": ["a", "b"]})
        assert result == ["a", "b"]

    def test_with_string_messages(self):
        result = normalize_batch_messages_payload({"messages": "single message"})
        assert result == ["single message"]

    def test_with_empty_list(self):
        result = normalize_batch_messages_payload({"messages": []})
        assert result == []

    def test_with_no_messages_key(self):
        result = normalize_batch_messages_payload({})
        assert result == []

    def test_filters_empty_strings(self):
        result = normalize_batch_messages_payload({"messages": ["hello", "", "  ", "world"]})
        assert result == ["hello", "world"]

    def test_strips_whitespace(self):
        result = normalize_batch_messages_payload({"messages": ["  hello  "]})
        assert result == ["hello"]


# ========================= unified_chat_single_payload ===================


class TestUnifiedChatSinglePayload:
    def test_pro_source_rejected(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=True),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
        ):
            result = unified_chat_single_payload("hello", "user1", "127.0.0.1", "pro", None)
            assert result["success"] is False
            assert result["mode_guard"] == "normal_only"
            assert result["_http_status"] == 400

    def test_professional_mode_rejected(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=True),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
        ):
            result = unified_chat_single_payload(
                "hello", "user1", "127.0.0.1", "normal", "professional"
            )
            assert result["success"] is False

    def test_qclaw_source_allowed(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=True),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=True),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "other"},
            ),
        ):
            result = unified_chat_single_payload("hello", "user1", "127.0.0.1", "qclaw", None)
            assert result.get("mode_guard") != "normal_only"

    def test_excel_analysis_with_import_keyword(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch("app.application.get_ai_chat_app_service") as mock_svc,
        ):
            mock_service = MagicMock()
            mock_service.process_chat.return_value = {"success": True, "data": {}}
            mock_svc.return_value = mock_service
            result = unified_chat_single_payload(
                "导入数据",
                "user1",
                "127.0.0.1",
                "normal",
                None,
                context={"excel_analysis": {"sheets": 1}},
            )
            mock_service.process_chat.assert_called_once()

    def test_shipment_intent(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "shipment"},
            ),
            patch(
                "app.application.facades.tools_facade._parse_order_text",
                return_value={
                    "success": True,
                    "unit_name": "TestUnit",
                    "products": [{"model_number": "M1"}],
                },
            ),
            patch(
                "app.application.ai_chat_helpers.build_shipment_preview_response_dict",
                return_value={"success": True, "task": {"type": "shipment_generate"}},
            ),
        ):
            result = unified_chat_single_payload("发货单", "user1", "127.0.0.1", "normal", None)
            assert result["success"] is True

    def test_shipment_intent_parse_fails(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "shipment"},
            ),
            patch(
                "app.application.facades.tools_facade._parse_order_text",
                return_value={"success": False, "message": "订单信息不完整"},
            ),
        ):
            result = unified_chat_single_payload("发货单", "user1", "127.0.0.1", "normal", None)
            assert result["success"] is True

    def test_shipment_intent_parse_error(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "shipment"},
            ),
            patch(
                "app.application.facades.tools_facade._parse_order_text",
                side_effect=RuntimeError("parse error"),
            ),
        ):
            result = unified_chat_single_payload("发货单", "user1", "127.0.0.1", "normal", None)
            assert result["success"] is False

    def test_product_query_intent(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "product_query"},
            ),
            patch(
                "app.application.normal_chat_dispatch.build_product_query_response_dict",
                return_value={"success": True, "data": {}},
            ),
        ):
            result = unified_chat_single_payload("查询产品", "user1", "127.0.0.1", "normal", None)
            assert result["success"] is True

    def test_product_query_intent_no_body(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "product_query"},
            ),
            patch(
                "app.application.normal_chat_dispatch.build_product_query_response_dict",
                return_value=None,
            ),
        ):
            result = unified_chat_single_payload("查询产品", "user1", "127.0.0.1", "normal", None)
            assert "success" in result

    def test_other_intent_default_response(self):
        with (
            patch("app.utils.ai_helpers.is_pro_source", return_value=False),
            patch("app.utils.ai_helpers.is_professional_mode", return_value=False),
            patch("app.utils.ai_helpers.is_qclaw_source", return_value=False),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "other"},
            ),
        ):
            result = unified_chat_single_payload("你好", "user1", "127.0.0.1", "normal", None)
            assert result["success"] is True
            assert "两套独立能力" in result["response"]
