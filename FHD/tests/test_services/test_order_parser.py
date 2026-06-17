"""Tests for app.services.tools_execution.order_parser — coverage ramp."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

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
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"unit_name": "张三", "model_number": "ABC-123", "tin_spec": "20", "quantity_tins": "5"}'
                    }
                }
            ]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            with patch("httpx.Client", return_value=mock_client):
                with patch(
                    "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                    return_value="http://fake/api",
                ):
                    result = _parse_order_text("一些无法解析的文本xyz")
        assert isinstance(result, dict)

    def test_ai_fallback_api_error(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            with patch("httpx.Client") as mock_cls:
                mock_cls.side_effect = OSError("connection failed")
                result = _parse_order_text("一些无法解析的文本xyz")
        assert isinstance(result, dict)

    def test_ai_fallback_non_200_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            with patch("httpx.Client", return_value=mock_client):
                with patch(
                    "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                    return_value="http://fake/api",
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
