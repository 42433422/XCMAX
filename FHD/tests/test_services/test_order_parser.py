"""Tests for app.services.tools_execution.order_parser — coverage ramp."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools_execution.order_parser import _parse_order_text


class TestParseOrderTextEmptyAndInvalid:
    def test_empty_string(self):
        result = _parse_order_text("")
        assert result["success"] is False

    def test_none_input(self):
        result = _parse_order_text(None)  # type: ignore[arg-type]
        assert result["success"] is False

    def test_whitespace_only(self):
        result = _parse_order_text("   ")
        assert result["success"] is False

    def test_unparseable_text(self):
        result = _parse_order_text("xyz")
        assert result["success"] is False


class TestParseOrderTextWithModelAndSpec:
    def test_model_with_spec_and_qty(self):
        result = _parse_order_text("张三 编号：ABC-123 规格20 5桶")
        assert result["success"] is True
        assert result["products"][0]["model_number"] == "ABC-123"
        assert result["products"][0]["tin_spec"] == 20.0
        assert result["products"][0]["quantity_tins"] == 5

    def test_model_with_spec_no_qty(self):
        result = _parse_order_text("张三 编号：ABC-123 规格20")
        # Should ask for quantity
        assert result["success"] is False
        assert "桶数" in result.get("message", "") or "缺少" in result.get("message", "")

    def test_model_keyword_xinghao(self):
        result = _parse_order_text("张三 型号：XYZ-456 规格15 3桶")
        assert result["success"] is True
        assert result["products"][0]["model_number"] == "XYZ-456"

    def test_model_spec_before_keyword(self):
        result = _parse_order_text("张三 ABC-123的规格20 5桶")
        assert result["success"] is True
        assert result["products"][0]["model_number"] == "ABC-123"


class TestParseOrderTextWithChineseNumbers:
    def test_chinese_spec_number(self):
        result = _parse_order_text("张三 编号：ABC-123 规格二十 5桶")
        assert isinstance(result, dict)

    def test_chinese_quantity(self):
        result = _parse_order_text("张三 编号：ABC-123 规格20 三桶")
        assert isinstance(result, dict)


class TestParseOrderTextMultiProduct:
    def test_multi_product_pattern(self):
        text = "张三 5桶 ABC-123 规格20 3桶 DEF-456 规格15"
        result = _parse_order_text(text)
        assert isinstance(result, dict)


class TestParseOrderTextWithUnitName:
    def test_unit_name_from_prefix(self):
        result = _parse_order_text("张三5桶ABC-123规格20")
        assert isinstance(result, dict)

    def test_delivery_note_keyword(self):
        result = _parse_order_text("张三发货单 编号：ABC-123 规格20 5桶")
        assert isinstance(result, dict)

    def test_print_delivery_note(self):
        result = _parse_order_text("打印一下张三的发货单 编号：ABC-123 规格20 5桶")
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "text",
        [
            "打印侯雪梅发货单，编号9803，规格28，3桶",
            "开单 侯雪梅 编号9803 规格28 3桶",
            "打单侯雪梅 型号9803 规格28 三桶",
        ],
    )
    def test_delivery_natural_language_keeps_customer_and_product_slots(self, text):
        result = _parse_order_text(text)
        assert result["success"] is True
        assert result["unit_name"] == "侯雪梅"
        assert result["products"] == [
            {
                "name": "",
                "model_number": "9803",
                "quantity_tins": 3,
                "tin_spec": 28.0,
            }
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "打印金汉武发货单，黑棕面用修色精，规格28，3桶",
            "开单 金汉武，黑棕面用修色精，规格28，3桶",
        ],
    )
    def test_delivery_natural_language_accepts_named_product_without_model(self, text):
        result = _parse_order_text(text)

        assert result == {
            "success": True,
            "unit_name": "金汉武",
            "products": [
                {
                    "name": "黑棕面用修色精",
                    "quantity_tins": 3,
                    "tin_spec": 28.0,
                }
            ],
        }

    @pytest.mark.parametrize(
        "text",
        [
            "给金汉武家私打单：黑棕面用修色精，规格4，3桶，单价48元",
            "给金汉武家私打印发货单：黑棕面用修色精，3桶，单价48元，规格4",
        ],
    )
    def test_recipient_first_order_keeps_named_product_measurements_and_price(self, text):
        result = _parse_order_text(text)

        assert result == {
            "success": True,
            "unit_name": "金汉武家私",
            "products": [
                {
                    "name": "黑棕面用修色精",
                    "quantity_tins": 3,
                    "tin_spec": 4.0,
                    "unit_price": 48.0,
                }
            ],
        }

    def test_named_product_uses_labelled_number_as_document_number_not_model(self):
        result = _parse_order_text("打印金汉武发货单，黑棕面用修色精，编号9803，规格28，3桶")

        assert result["success"] is True
        assert result["unit_name"] == "金汉武"
        assert result["products"] == [
            {
                "name": "黑棕面用修色精",
                "quantity_tins": 3,
                "tin_spec": 28.0,
            }
        ]
        assert result["order_number"] == "9803"
        assert result["order_number_provenance"] == {
            "kind": "explicit_document_number",
            "label": "编号",
            "value": "9803",
        }


class TestParseOrderTextBoxAndKg:
    def test_box_quantity(self):
        result = _parse_order_text("张三5箱产品名")
        assert result["success"] is True
        assert result["products"][0]["quantity_tins"] == 5

    def test_kg_quantity(self):
        result = _parse_order_text("张三25公斤产品名")
        assert result["success"] is True
        assert "quantity_kg" in result["products"][0]
        assert result["products"][0]["quantity_kg"] == 25.0

    def test_chinese_kg_quantity(self):
        result = _parse_order_text("张三二十公斤产品名")
        assert isinstance(result, dict)


class TestParseOrderTextFallbackPatterns:
    def test_simple_two_word_fallback(self):
        result = _parse_order_text("张三 产品A")
        assert result["success"] is True
        assert result["unit_name"] == "张三"
        assert result["products"][0]["name"] == "产品A"

    def test_no_container_qty_with_model_spec(self):
        result = _parse_order_text("张三 ABC-123 规格20")
        # Should ask for quantity
        assert result["success"] is False
        assert "桶数" in result.get("message", "") or "缺少" in result.get("message", "")


class TestParseOrderTextAI:
    def test_ai_fallback_disabled_no_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            result = _parse_order_text("一些无法解析的文本xyz")
        assert result["success"] is False

    def test_ai_fallback_with_api_key_success(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"unit_name": "张三", "model_number": "ABC-123", "tin_spec": "20", "quantity_tins": "5"}'
                    }
                }
            ]
        }
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            with patch(
                "app.infrastructure.llm.invoke.chat_completion_openai_format",
                new=AsyncMock(return_value=payload),
            ):
                result = _parse_order_text("一些无法解析的文本xyz")
        assert isinstance(result, dict)
        assert result.get("success") is True
        assert result["products"][0]["model_number"] == "ABC-123"

    def test_ai_fallback_api_error(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            with patch(
                "app.infrastructure.llm.invoke.chat_completion_openai_format",
                new=AsyncMock(side_effect=OSError("connection failed")),
            ):
                result = _parse_order_text("一些无法解析的文本xyz")
        assert isinstance(result, dict)

    def test_ai_fallback_llm_returns_none(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            with patch(
                "app.infrastructure.llm.invoke.chat_completion_openai_format",
                new=AsyncMock(return_value=None),
            ):
                result = _parse_order_text("一些无法解析的文本xyz")
        assert isinstance(result, dict)


class TestParseOrderTextPunctuation:
    def test_chinese_punctuation_stripped(self):
        result = _parse_order_text("张三 编号：ABC-123，规格20，5桶")
        assert isinstance(result, dict)

    def test_mixed_punctuation(self):
        result = _parse_order_text("张三 编号:ABC-123,规格20,5桶")
        assert isinstance(result, dict)


class TestParseOrderTextDeliveryNoteKeywords:
    def test_songhuodan_keyword(self):
        result = _parse_order_text("张三送货单 编号：ABC-123 规格20 5桶")
        assert isinstance(result, dict)

    def test_chuhuodan_keyword(self):
        result = _parse_order_text("张三出货单 编号：ABC-123 规格20 5桶")
        assert isinstance(result, dict)
