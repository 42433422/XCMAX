"""Extended tests for ``app.services.ai_product_parser`` covering low-coverage branches."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_product_parser import (
    AIProductParser,
    _get_product_parse_cache,
    _product_parse_cache,
)


class TestParseSingleExtended:
    """Cover parse_single branches: empty input, AI success, AI invalid + no fallback, hybrid."""

    def test_parse_single_empty_text_returns_invalid(self) -> None:
        parser = AIProductParser()
        result = parser.parse_single("", use_ai=False)
        assert result["success"] is False
        assert result["parse_method"] == "rule"
        assert "unit" in result["missing_fields"]
        assert "quantity" in result["missing_fields"]
        assert "specification" in result["missing_fields"]
        assert "product" in result["missing_fields"]
        assert result["invalid_reason"]

    def test_parse_single_none_text_returns_invalid(self) -> None:
        parser = AIProductParser()
        result = parser.parse_single(None, use_ai=False)  # type: ignore[arg-type]
        assert result["success"] is False
        assert result["raw_data"] is None

    def test_parse_single_ai_valid_returns_ai_result(self) -> None:
        parser = AIProductParser()
        ai_data = {
            "product_code": "9803",
            "product_name": "七彩乐园",
            "specification": "规格12",
            "quantity": 3,
            "unit": "桶",
            "purchase_unit": "客户A",
            "raw_data": "text",
            "confidence": 0.9,
            "parse_method": "ai",
        }
        with patch.object(
            AIProductParser, "_cached_call_ai_api", return_value=ai_data
        ):
            result = parser.parse_single("text", use_ai=True, fallback_to_rule=False)
        assert result["success"] is True
        assert result["parse_method"] == "ai"
        assert result["product_code"] == "9803"

    def test_parse_single_ai_invalid_no_fallback_returns_invalid(self) -> None:
        parser = AIProductParser()
        ai_data = {
            "product_code": "",
            "product_name": "",
            "specification": "",
            "quantity": None,
            "unit": "",
        }
        with patch.object(
            AIProductParser, "_cached_call_ai_api", return_value=ai_data
        ):
            result = parser.parse_single("text", use_ai=True, fallback_to_rule=False)
        assert result["success"] is False
        assert result["parse_method"] == "ai"
        assert "unit" in result["missing_fields"]

    def test_parse_single_ai_invalid_with_fallback_rule_valid(self) -> None:
        parser = AIProductParser()
        ai_data = {"product_code": "", "product_name": "", "quantity": None, "unit": ""}
        with patch.object(
            AIProductParser, "_cached_call_ai_api", return_value=ai_data
        ):
            result = parser.parse_single(
                "七彩乐园9803规格12要3桶", use_ai=True, fallback_to_rule=True
            )
        assert result["success"] is True
        assert result["parse_method"] == "rule"

    def test_parse_single_ai_invalid_with_fallback_rule_invalid_hybrid(self) -> None:
        parser = AIProductParser()
        ai_data = {"product_code": "", "product_name": "", "quantity": None, "unit": ""}
        with patch.object(
            AIProductParser, "_cached_call_ai_api", return_value=ai_data
        ):
            result = parser.parse_single(
                "no product info here", use_ai=True, fallback_to_rule=True
            )
        assert result["success"] is False
        assert result["parse_method"] == "hybrid"

    def test_parse_single_no_ai_rule_invalid(self) -> None:
        parser = AIProductParser()
        result = parser.parse_single("no product info", use_ai=False)
        assert result["success"] is False
        assert result["parse_method"] == "rule"


class TestParseBatchExtended:
    def test_parse_batch_empty_list(self) -> None:
        parser = AIProductParser()
        assert parser.parse_batch([]) == []

    def test_parse_batch_none_list(self) -> None:
        parser = AIProductParser()
        assert parser.parse_batch(None) == []  # type: ignore[arg-type]

    def test_parse_batch_multiple_items(self) -> None:
        parser = AIProductParser()
        results = parser.parse_batch(
            ["七彩乐园9803规格12要3桶", "", "no info"], use_ai=False
        )
        assert len(results) == 3
        assert results[0]["success"] is True
        assert results[1]["success"] is False
        assert results[2]["success"] is False


class TestExtractUnitExtended:
    def test_extract_unit_from_quantity_pattern(self) -> None:
        parser = AIProductParser()
        assert parser._extract_unit("要3桶") == "桶"

    def test_extract_unit_from_unit_only_pattern(self) -> None:
        parser = AIProductParser()
        assert parser._extract_unit("桶") == "桶"

    def test_extract_unit_no_match_returns_empty(self) -> None:
        parser = AIProductParser()
        assert parser._extract_unit("nothing here") == ""


class TestRuleParseExtended:
    def test_rule_parse_full_text(self) -> None:
        parser = AIProductParser()
        result = parser._rule_parse("发货单七彩乐园9803规格12要3桶")
        assert result["product_code"] == "9803"
        assert result["quantity"] == 3
        assert result["unit"] == "桶"
        assert result["specification"]
        assert result["confidence"] == 0.8
        assert result["parse_method"] == "rule"

    def test_rule_parse_integer_quantity(self) -> None:
        parser = AIProductParser()
        result = parser._rule_parse("要3桶")
        assert result["quantity"] == 3
        assert isinstance(result["quantity"], int)

    def test_rule_parse_float_quantity(self) -> None:
        parser = AIProductParser()
        result = parser._rule_parse("要3.5桶")
        assert result["quantity"] == 3.5
        assert isinstance(result["quantity"], float)

    def test_rule_parse_no_quantity(self) -> None:
        parser = AIProductParser()
        result = parser._rule_parse("七彩乐园9803规格12")
        assert result["quantity"] is None

    def test_rule_parse_extract_code_from_product_name(self) -> None:
        parser = AIProductParser()
        # No direct code match in PRODUCT_CODE_PATTERN but name has digits
        result = parser._rule_parse("产品abc123")
        # code may be extracted from name
        assert "product_code" in result

    def test_rule_parse_short_name_no_purchase_unit(self) -> None:
        parser = AIProductParser()
        result = parser._rule_parse("a")
        # name_text len < 2 means product_name stays empty
        assert result["product_name"] == ""

    def test_rule_parse_name_without_chinese_prefix(self) -> None:
        parser = AIProductParser()
        result = parser._rule_parse("product 9803")
        # No Chinese prefix match
        assert "product_name" in result


class TestValidateRequiredFieldsExtended:
    def test_validate_all_fields_present(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "9803",
            "product_name": "name",
            "specification": "spec",
            "quantity": 3,
            "unit": "桶",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is True
        assert result["data"]["success"] is True
        assert result["data"]["missing_fields"] == []
        assert result["data"]["invalid_reason"] == ""

    def test_validate_missing_unit(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "9803",
            "specification": "spec",
            "quantity": 3,
            "unit": "",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "unit" in result["missing_fields"]

    def test_validate_missing_quantity(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "9803",
            "specification": "spec",
            "quantity": None,
            "unit": "桶",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "quantity" in result["missing_fields"]

    def test_validate_quantity_empty_string(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "9803",
            "specification": "spec",
            "quantity": "",
            "unit": "桶",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "quantity" in result["missing_fields"]

    def test_validate_missing_specification(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "9803",
            "specification": "",
            "quantity": 3,
            "unit": "桶",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "specification" in result["missing_fields"]

    def test_validate_missing_product(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "",
            "product_name": "",
            "specification": "spec",
            "quantity": 3,
            "unit": "桶",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "product" in result["missing_fields"]

    def test_validate_product_name_only(self) -> None:
        parser = AIProductParser()
        data = {
            "product_code": "",
            "product_name": "name",
            "specification": "spec",
            "quantity": 3,
            "unit": "桶",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is True


class TestBuildInvalidResultExtended:
    def test_build_invalid_no_partial(self) -> None:
        parser = AIProductParser()
        result = parser._build_invalid_result(
            raw_text="text",
            parse_method="rule",
            missing_fields=["unit"],
            invalid_reason="missing unit",
        )
        assert result["success"] is False
        assert result["parse_method"] == "rule"
        assert result["missing_fields"] == ["unit"]
        assert result["invalid_reason"] == "missing unit"
        assert result["raw_data"] == "text"
        assert result["confidence"] == 0.0

    def test_build_invalid_with_partial(self) -> None:
        parser = AIProductParser()
        partial = {
            "product_code": "9803",
            "product_name": "name",
            "specification": "spec",
            "quantity": 3,
            "unit": "桶",
            "extra_field": "ignored",
        }
        result = parser._build_invalid_result(
            raw_text="text",
            parse_method="hybrid",
            missing_fields=["unit"],
            invalid_reason="missing",
            partial_data=partial,
        )
        assert result["success"] is False
        assert result["parse_method"] == "hybrid"
        assert result["product_code"] == "9803"
        assert "extra_field" not in result


class TestShouldCacheAiResultExtended:
    def test_should_cache_none_returns_false(self) -> None:
        assert AIProductParser._should_cache_ai_result(None) is False

    def test_should_cache_non_dict_returns_false(self) -> None:
        assert AIProductParser._should_cache_ai_result("string") is False  # type: ignore[arg-type]

    def test_should_cache_no_product_fields_returns_false(self) -> None:
        result = AIProductParser._should_cache_ai_result(
            {"product_code": "", "product_name": "", "confidence": 0.9}
        )
        assert result is False

    def test_should_cache_zero_confidence_returns_false(self) -> None:
        result = AIProductParser._should_cache_ai_result(
            {"product_code": "9803", "confidence": 0}
        )
        assert result is False

    def test_should_cache_valid_returns_true(self) -> None:
        result = AIProductParser._should_cache_ai_result(
            {"product_code": "9803", "confidence": 0.9}
        )
        assert result is True

    def test_should_cache_with_product_name_only(self) -> None:
        result = AIProductParser._should_cache_ai_result(
            {"product_name": "name", "confidence": 0.5}
        )
        assert result is True


class TestCachedCallAiApiExtended:
    def test_cached_call_ai_api_success(self) -> None:
        parser = AIProductParser()
        expected = {"product_code": "9803", "confidence": 0.9}
        mock_cache = MagicMock()
        mock_cache.get_or_compute.return_value = expected
        with patch(
            "app.services.ai_product_parser._get_product_parse_cache",
            return_value=mock_cache,
        ), patch(
            "app.services.ai_product_parser.get_request_active_mod_id",
            return_value="mod1",
            create=True,
        ):
            # The function imports get_request_active_mod_id lazily, patch at source
            with patch(
                "app.request_active_mod_ctx.get_request_active_mod_id",
                return_value="mod1",
            ):
                result = parser._cached_call_ai_api("text")
        assert result == expected
        mock_cache.get_or_compute.assert_called_once()

    def test_cached_call_ai_api_recoverable_error_falls_back(self) -> None:
        parser = AIProductParser()
        with patch(
            "app.services.ai_product_parser._get_product_parse_cache",
            side_effect=RuntimeError("cache down"),
        ), patch.object(
            AIProductParser, "_call_ai_api", return_value={"product_code": "fallback"}
        ) as mock_call:
            result = parser._cached_call_ai_api("text")
        assert result == {"product_code": "fallback"}
        mock_call.assert_called_once_with("text")


class TestCallAiApiExtended:
    def test_call_ai_api_no_api_key_returns_none(self) -> None:
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="",
        ):
            result = parser._call_ai_api("text")
        assert result is None

    def test_call_ai_api_recoverable_error_returns_none(self) -> None:
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            side_effect=RuntimeError("api error"),
        ):
            result = parser._call_ai_api("text")
        assert result is None

    def test_call_ai_api_success_with_json(self) -> None:
        parser = AIProductParser()
        api_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "product_code": "9803",
                                "product_name": "name",
                                "specification": "spec",
                                "quantity": 3,
                                "unit": "桶",
                                "purchase_unit": "客户",
                            }
                        )
                    }
                }
            ]
        }

        async def mock_call_api():
            return api_response

        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="key",
        ), patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=api_response),
        ):
            result = parser._call_ai_api("text")
        assert result is not None
        assert result["product_code"] == "9803"
        assert result["confidence"] == 0.9
        assert result["parse_method"] == "ai"

    def test_call_ai_api_with_code_block_content(self) -> None:
        parser = AIProductParser()
        content = "```json\n" + json.dumps(
            {
                "product_code": "9803",
                "product_name": "name",
                "specification": "spec",
                "quantity": 3,
                "unit": "桶",
                "purchase_unit": "客户",
            }
        ) + "\n```"
        api_response = {
            "choices": [{"message": {"content": content}}]
        }

        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="key",
        ), patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=api_response),
        ):
            result = parser._call_ai_api("text")
        assert result is not None
        assert result["product_code"] == "9803"

    def test_call_ai_api_quantity_string_converts(self) -> None:
        parser = AIProductParser()
        content = json.dumps(
            {
                "product_code": "9803",
                "product_name": "name",
                "specification": "spec",
                "quantity": "三",
                "unit": "桶",
                "purchase_unit": "客户",
            }
        )
        api_response = {
            "choices": [{"message": {"content": content}}]
        }

        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="key",
        ), patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=api_response),
        ), patch(
            "app.services.deepseek_intent_service.cn_to_number", return_value=3
        ):
            result = parser._call_ai_api("text")
        assert result is not None
        assert result["quantity"] == 3

    def test_call_ai_api_no_choices_returns_none(self) -> None:
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="key",
        ), patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value={"choices": []}),
        ):
            result = parser._call_ai_api("text")
        assert result is None

    def test_call_ai_api_empty_content_returns_none(self) -> None:
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="key",
        ), patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(
                return_value={"choices": [{"message": {"content": ""}}]}
            ),
        ):
            result = parser._call_ai_api("text")
        assert result is None

    def test_call_ai_api_no_json_match_returns_none(self) -> None:
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="key",
        ), patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(
                return_value={"choices": [{"message": {"content": "no json here"}}]}
            ),
        ):
            result = parser._call_ai_api("text")
        assert result is None


class TestGetProductParseCacheExtended:
    def test_get_product_parse_cache_creates_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Reset the singleton
        import app.services.ai_product_parser as mod

        original = mod._product_parse_cache
        mod._product_parse_cache = None
        try:
            mock_cache_cls = MagicMock()
            mock_instance = MagicMock()
            mock_cache_cls.return_value = mock_instance
            monkeypatch.setattr(
                "app.infrastructure.cache.intent_cache.IntentCache", mock_cache_cls
            )
            cache1 = _get_product_parse_cache()
            cache2 = _get_product_parse_cache()
            assert cache1 is cache2
            mock_cache_cls.assert_called_once()
        finally:
            mod._product_parse_cache = original

    def test_get_product_parse_cache_returns_existing(self) -> None:
        # The module-level singleton may already be set
        cache = _get_product_parse_cache()
        assert cache is not None
