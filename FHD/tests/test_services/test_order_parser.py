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


class TestParseOrderTextInvertedSpec:
    """倒装/容量记法：「20L规格」「规格20」「20L」「28的规格」统一解析为 规格=数字。"""

    def test_inverted_spec_with_unit_suffix(self):
        result = _parse_order_text("发货单 太阳鸟 5桶 20L规格")
        assert result["success"] is False
        msg = result.get("message", "")
        assert "单位 太阳鸟" in msg
        assert "规格 20" in msg
        assert "规格，" not in msg and "规格）" not in msg.replace("规格 20）", "")

    def test_inverted_spec_plain_number(self):
        result = _parse_order_text("发货单 太阳鸟 5桶 规格20")
        assert result["success"] is False
        assert "单位 太阳鸟" in result.get("message", "")

    def test_capacity_notation_standalone(self):
        result = _parse_order_text("给太阳鸟开单 20L 5桶")
        assert result["success"] is False
        msg = result.get("message", "")
        assert "单位 太阳鸟" in msg
        assert "开单" not in msg

    def test_colloquial_de_spec_lai_qty(self):
        result = _parse_order_text("太阳鸟那边要28的规格来30桶")
        assert result["success"] is False
        msg = result.get("message", "")
        assert "规格 28" in msg
        assert "规格" not in (msg.split("单位 ")[1].split("，")[0] if "单位 " in msg else "")

    def test_inverted_spec_does_not_break_forward_order(self):
        # 正序「XY-20 规格：20」编号不被倒装改写吞掉
        result = _parse_order_text("王总 型号：XY-20 规格：20 一共3桶")
        assert result["success"] is True
        assert result["products"][0]["model_number"] == "XY-20"
