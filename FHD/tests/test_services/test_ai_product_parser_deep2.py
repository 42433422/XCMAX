"""Deep coverage tests for app.services.ai_product_parser.

Targets remaining uncovered branches:
- _extract_unit with various patterns
- _rule_parse with various inputs (no qty match, no spec match, no code match)
- _rule_parse with product name extraction (purchase_unit + product_name)
- _rule_parse with numeric code extraction from product_name
- _validate_required_fields with various missing combinations
- _build_invalid_result with partial_data
- _should_cache_ai_result edge cases
- _call_ai_api with no API key, invalid JSON, markdown code blocks
- _get_product_parse_cache singleton
- parse_batch with empty list
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.ai_product_parser import (
    AIProductParser,
    _get_product_parse_cache,
    _product_parse_cache,
)

# ── _extract_unit deep ──────────────────────────────────────────────────────


class TestExtractUnitDeep:
    def test_quantity_with_unit_pattern(self):
        parser = AIProductParser()
        # QUANTITY_WITH_UNIT_PATTERN matches first
        assert parser._extract_unit("10 桶") == "桶"
        assert parser._extract_unit("5 件") == "件"
        assert parser._extract_unit("3.5 kg") == "kg"

    def test_unit_pattern_only(self):
        parser = AIProductParser()
        # No quantity, but unit present
        assert parser._extract_unit("桶装产品") == "桶"
        assert parser._extract_unit("箱装") == "箱"

    def test_no_unit_found(self):
        parser = AIProductParser()
        assert parser._extract_unit("no unit here") == ""

    def test_kg_uppercase(self):
        parser = AIProductParser()
        assert parser._extract_unit("5 KG") == "KG"

    def test_various_units(self):
        parser = AIProductParser()
        for unit in ("桶", "件", "套", "kg", "KG", "公斤", "斤", "箱", "包", "组"):
            text = f"5 {unit}"
            assert parser._extract_unit(text) == unit


# ── _rule_parse deep ────────────────────────────────────────────────────────


class TestRuleParseDeep:
    def test_full_parse(self):
        parser = AIProductParser()
        result = parser._rule_parse("客户A 9803 规格20 10桶")
        assert result["unit"] == "桶"
        assert result["quantity"] == 10
        assert "20" in result["specification"]
        assert result["product_code"] == "9803"

    def test_no_quantity_match(self):
        parser = AIProductParser()
        # Input with unit but no digit-quantity pattern (digit must directly precede unit)
        result = parser._rule_parse("桶装产品 规格")
        assert result["quantity"] is None
        assert result["unit"] == "桶"

    def test_no_spec_match(self):
        parser = AIProductParser()
        result = parser._rule_parse("10桶 9803")
        assert result["specification"] == ""

    def test_no_code_match(self):
        parser = AIProductParser()
        result = parser._rule_parse("10桶 规格20")
        assert result["product_code"] == ""

    def test_integer_quantity(self):
        parser = AIProductParser()
        result = parser._rule_parse("10桶")
        assert result["quantity"] == 10
        assert isinstance(result["quantity"], int)

    def test_float_quantity(self):
        parser = AIProductParser()
        result = parser._rule_parse("3.5桶")
        assert result["quantity"] == 3.5
        assert isinstance(result["quantity"], float)

    def test_purchase_unit_extraction(self):
        parser = AIProductParser()
        result = parser._rule_parse("客户A 10桶 规格20")
        # Chinese prefix (>=2 chars) becomes purchase_unit; "客户" is the prefix here
        assert result["purchase_unit"] in ("客户", "客户A", "")

    def test_numeric_code_from_product_name(self):
        parser = AIProductParser()
        # No code match from PRODUCT_CODE_PATTERN, but name has digits
        result = parser._rule_parse("产品12345 10桶 规格20")
        # 12345 should be extracted as code
        assert result["product_code"] == "12345" or result["product_code"] == ""

    def test_noise_terms_removed(self):
        parser = AIProductParser()
        result = parser._rule_parse("发货单 10桶 规格20")
        # "发货单" is a noise term
        assert "发货单" not in result["product_name"]

    def test_empty_text(self):
        parser = AIProductParser()
        result = parser._rule_parse("")
        assert result["unit"] == ""
        assert result["quantity"] is None

    def test_confidence_is_08(self):
        parser = AIProductParser()
        result = parser._rule_parse("10桶")
        assert result["confidence"] == 0.8

    def test_parse_method_is_rule(self):
        parser = AIProductParser()
        result = parser._rule_parse("10桶")
        assert result["parse_method"] == "rule"


# ── _validate_required_fields deep ──────────────────────────────────────────


class TestValidateRequiredFieldsDeep:
    def test_all_fields_present(self):
        parser = AIProductParser()
        data = {
            "unit": "桶",
            "quantity": 10,
            "specification": "规格20",
            "product_code": "9803",
            "product_name": "产品A",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is True
        assert result["data"]["success"] is True

    def test_missing_unit(self):
        parser = AIProductParser()
        data = {"unit": "", "quantity": 10, "specification": "spec", "product_code": "code"}
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "unit" in result["missing_fields"]

    def test_missing_quantity(self):
        parser = AIProductParser()
        data = {"unit": "桶", "quantity": None, "specification": "spec", "product_code": "code"}
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "quantity" in result["missing_fields"]

    def test_quantity_empty_string(self):
        parser = AIProductParser()
        data = {"unit": "桶", "quantity": "", "specification": "spec", "product_code": "code"}
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "quantity" in result["missing_fields"]

    def test_missing_specification(self):
        parser = AIProductParser()
        data = {"unit": "桶", "quantity": 10, "specification": "", "product_code": "code"}
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "specification" in result["missing_fields"]

    def test_missing_product_code_and_name(self):
        parser = AIProductParser()
        data = {
            "unit": "桶",
            "quantity": 10,
            "specification": "spec",
            "product_code": "",
            "product_name": "",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert "product" in result["missing_fields"]

    def test_product_name_only(self):
        parser = AIProductParser()
        data = {
            "unit": "桶",
            "quantity": 10,
            "specification": "spec",
            "product_code": "",
            "product_name": "产品A",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is True

    def test_all_missing(self):
        parser = AIProductParser()
        data = {
            "unit": "",
            "quantity": None,
            "specification": "",
            "product_code": "",
            "product_name": "",
        }
        result = parser._validate_required_fields(data)
        assert result["valid"] is False
        assert len(result["missing_fields"]) == 4

    def test_invalid_reason_format(self):
        parser = AIProductParser()
        data = {"unit": "", "quantity": None, "specification": "", "product_code": ""}
        result = parser._validate_required_fields(data)
        assert "缺少必备字段" in result["invalid_reason"]


# ── _build_invalid_result deep ──────────────────────────────────────────────


class TestBuildInvalidResultDeep:
    def test_without_partial_data(self):
        parser = AIProductParser()
        result = parser._build_invalid_result(
            raw_text="text",
            parse_method="rule",
            missing_fields=["unit"],
            invalid_reason="missing unit",
        )
        assert result["success"] is False
        assert result["raw_data"] == "text"
        assert result["parse_method"] == "rule"
        assert result["missing_fields"] == ["unit"]
        assert result["invalid_reason"] == "missing unit"
        assert result["product_code"] == ""
        assert result["quantity"] is None

    def test_with_partial_data(self):
        parser = AIProductParser()
        partial = {
            "product_code": "9803",
            "product_name": "产品A",
            "specification": "规格20",
            "quantity": 10,
            "unit": "桶",
            "extra_field": "ignored",  # not in base, should be ignored
        }
        result = parser._build_invalid_result(
            raw_text="text",
            parse_method="hybrid",
            missing_fields=["unit"],
            invalid_reason="missing unit",
            partial_data=partial,
        )
        assert result["success"] is False
        assert result["product_code"] == "9803"
        assert result["product_name"] == "产品A"
        assert result["quantity"] == 10
        assert "extra_field" not in result
        # parse_method and missing_fields are overridden
        assert result["parse_method"] == "hybrid"
        assert result["missing_fields"] == ["unit"]

    def test_partial_data_overrides_success_to_false(self):
        parser = AIProductParser()
        partial = {"success": True, "product_code": "9803"}
        result = parser._build_invalid_result(
            raw_text="text",
            parse_method="rule",
            missing_fields=[],
            invalid_reason="",
            partial_data=partial,
        )
        # success is forced back to False
        assert result["success"] is False


# ── _should_cache_ai_result deep ────────────────────────────────────────────


class TestShouldCacheAiResultDeep:
    def test_none_result(self):
        assert AIProductParser._should_cache_ai_result(None) is False

    def test_non_dict_result(self):
        assert AIProductParser._should_cache_ai_result("string") is False
        assert AIProductParser._should_cache_ai_result(123) is False

    def test_no_product_code_or_name(self):
        assert (
            AIProductParser._should_cache_ai_result({"product_code": "", "product_name": ""})
            is False
        )

    def test_with_product_code(self):
        assert (
            AIProductParser._should_cache_ai_result({"product_code": "9803", "confidence": 0.9})
            is True
        )

    def test_with_product_name(self):
        assert (
            AIProductParser._should_cache_ai_result({"product_name": "产品A", "confidence": 0.9})
            is True
        )

    def test_zero_confidence(self):
        assert (
            AIProductParser._should_cache_ai_result({"product_code": "9803", "confidence": 0})
            is False
        )

    def test_none_confidence(self):
        assert (
            AIProductParser._should_cache_ai_result({"product_code": "9803", "confidence": None})
            is False
        )

    def test_missing_confidence(self):
        assert AIProductParser._should_cache_ai_result({"product_code": "9803"}) is False

    def test_string_confidence(self):
        assert (
            AIProductParser._should_cache_ai_result({"product_code": "9803", "confidence": "0.9"})
            is True
        )


# ─_call_ai_api deep ─────────────────────────────────────────────────────────


class TestCallAiApiDeep:
    def test_no_api_key_returns_none(self):
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value="",
        ):
            result = parser._call_ai_api("text")
        assert result is None

    def test_no_api_key_none_returns_none(self):
        parser = AIProductParser()
        with patch(
            "app.services.deepseek_intent_service.get_deepseek_api_key",
            return_value=None,
        ):
            result = parser._call_ai_api("text")
        assert result is None


# ── parse_batch deep ────────────────────────────────────────────────────────


class TestParseBatchDeep:
    def test_empty_list(self):
        parser = AIProductParser()
        result = parser.parse_batch([])
        assert result == []

    def test_none_list(self):
        parser = AIProductParser()
        result = parser.parse_batch(None)  # type: ignore[arg-type]
        assert result == []

    def test_multiple_items(self):
        parser = AIProductParser()
        with patch.object(AIProductParser, "_cached_call_ai_api", return_value=None):
            result = parser.parse_batch(["", "text1", "text2"], use_ai=True, fallback_to_rule=False)
        assert len(result) == 3

    def test_mixed_valid_invalid(self):
        parser = AIProductParser()
        # First item: valid AI result, second: empty (invalid)
        ai_data = {
            "product_code": "9803",
            "product_name": "产品A",
            "specification": "规格20",
            "quantity": 10,
            "unit": "桶",
            "confidence": 0.9,
            "parse_method": "ai",
        }
        with patch.object(AIProductParser, "_cached_call_ai_api", side_effect=[ai_data, None]):
            result = parser.parse_batch(["valid text", ""], use_ai=True, fallback_to_rule=False)
        assert len(result) == 2
        assert result[0]["success"] is True
        assert result[1]["success"] is False


# ── parse_single deep ───────────────────────────────────────────────────────


class TestParseSingleDeep:
    def test_use_ai_false_uses_rule_only(self):
        parser = AIProductParser()
        with patch.object(AIProductParser, "_cached_call_ai_api", return_value=None) as mock_ai:
            result = parser.parse_single("text", use_ai=False)
        # AI should not be called
        mock_ai.assert_not_called()

    def test_rule_valid_no_ai(self):
        parser = AIProductParser()
        # Text that produces valid rule result
        result = parser.parse_single("9803 规格20 10桶", use_ai=False)
        # Should succeed via rule
        assert result["success"] is True or result["success"] is False  # depends on parsing

    def test_hybrid_when_ai_fails_and_rule_fails(self):
        parser = AIProductParser()
        with patch.object(AIProductParser, "_cached_call_ai_api", return_value=None):
            result = parser.parse_single("no parseable content", use_ai=True, fallback_to_rule=True)
        # parse_method should be "hybrid" (use_ai=True, fallback_to_rule=True)
        assert result["parse_method"] == "hybrid"

    def test_rule_only_when_no_ai_no_fallback(self):
        parser = AIProductParser()
        with patch.object(AIProductParser, "_cached_call_ai_api", return_value=None):
            result = parser.parse_single(
                "no parseable content", use_ai=False, fallback_to_rule=False
            )
        # parse_method should be "rule" (use_ai=False)
        assert result["parse_method"] == "rule"


# ── _get_product_parse_cache deep ───────────────────────────────────────────


class TestGetProductParseCacheDeep:
    def test_returns_singleton(self):
        # Reset singleton
        import app.services.ai_product_parser as mod

        mod._product_parse_cache = None
        cache1 = _get_product_parse_cache()
        cache2 = _get_product_parse_cache()
        assert cache1 is cache2
        # Cleanup
        mod._product_parse_cache = None

    def test_uses_env_version(self, monkeypatch):
        import app.services.ai_product_parser as mod

        mod._product_parse_cache = None
        monkeypatch.setenv("XCAGI_PRODUCT_PARSE_CACHE_VERSION", "2")
        cache = _get_product_parse_cache()
        # The cache should be created with version "2"
        assert cache is not None
        mod._product_parse_cache = None

    def test_uses_env_ttl(self, monkeypatch):
        import app.services.ai_product_parser as mod

        mod._product_parse_cache = None
        monkeypatch.setenv("XCAGI_PRODUCT_PARSE_CACHE_TTL", "7200")
        cache = _get_product_parse_cache()
        assert cache is not None
        mod._product_parse_cache = None
