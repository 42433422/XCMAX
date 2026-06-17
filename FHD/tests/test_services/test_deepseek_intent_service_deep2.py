"""Deep tests for ``app.services.deepseek_intent_service`` covering remaining uncovered branches."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.deepseek_intent_service as ds
from app.services.deepseek_intent_service import (
    DeepSeekIntentRecognizer,
    HybridIntentWithDeepSeek,
    cn_to_number,
    get_deepseek_api_key,
    get_deepseek_intent_recognizer,
    get_hybrid_intent_with_deepseek,
    reset_deepseek_intent_services,
)

# ── _get_api_key deep ────────────────────────────────────────────────────────


class TestGetApiKeyDeep:
    def test_api_key_from_instance_attr(self) -> None:
        r = DeepSeekIntentRecognizer(api_key="instance-key")
        assert r._get_api_key() == "instance-key"

    def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        r = DeepSeekIntentRecognizer(api_key=None)
        assert r._get_api_key() == "env-key"

    def test_api_key_no_env_no_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch(
            "app.utils.path_utils.get_resource_path",
            return_value=None,
        ):
            r = DeepSeekIntentRecognizer(api_key=None)
            assert r._get_api_key() == ""

    def test_api_key_config_file_not_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=False),
        ):
            r = DeepSeekIntentRecognizer(api_key=None)
            assert r._get_api_key() == ""

    def test_api_key_config_spec_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=True),
            patch("importlib.util.spec_from_file_location", return_value=None),
        ):
            r = DeepSeekIntentRecognizer(api_key=None)
            assert r._get_api_key() == ""

    def test_api_key_config_loader_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        mock_spec = MagicMock()
        mock_spec.loader = None
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=True),
            patch("importlib.util.spec_from_file_location", return_value=mock_spec),
        ):
            r = DeepSeekIntentRecognizer(api_key=None)
            assert r._get_api_key() == ""

    def test_api_key_config_empty_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        mock_module = MagicMock()
        mock_module.DEEPSEEK_API_KEY = ""
        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=True),
            patch("importlib.util.spec_from_file_location", return_value=mock_spec),
            patch("importlib.util.module_from_spec", return_value=mock_module),
            patch.object(mock_spec.loader, "exec_module"),
        ):
            r = DeepSeekIntentRecognizer(api_key=None)
            assert r._get_api_key() == ""


# ─_parse_response deep ──────────────────────────────────────────────────────


class TestParseResponseDeep:
    @pytest.fixture
    def recognizer(self) -> DeepSeekIntentRecognizer:
        return DeepSeekIntentRecognizer(api_key="k")

    def test_code_fence_with_brace(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '```\n{"intent": "greet", "confidence": 0.8, "slots": {}}\n```'
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] == "greet"
        assert out["confidence"] == 0.8

    def test_plain_json_valid_intent(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '{"intent": "products", "confidence": 0.9, "slots": {}}'
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] == "products"

    def test_plain_json_invalid_intent(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '{"intent": "INVALID", "confidence": 0.9, "slots": {}}'
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] is None

    def test_negation_intent_valid(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '{"intent": "negation", "confidence": 0.9, "slots": {}}'
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] == "negation"

    def test_confidence_capped_at_1(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '{"intent": "greet", "confidence": 1.5, "slots": {}}'
        out = recognizer._parse_response(content, "msg")
        assert out["confidence"] == 1.0

    def test_confidence_default_05(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '{"intent": "greet", "slots": {}}'
        out = recognizer._parse_response(content, "msg")
        assert out["confidence"] == 0.5

    def test_reasoning_extracted(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = '{"intent": "greet", "confidence": 0.8, "slots": {}, "reasoning": "user said hi"}'
        out = recognizer._parse_response(content, "msg")
        assert out["reasoning"] == "user said hi"

    def test_json_decode_error_falls_to_regex(self, recognizer: DeepSeekIntentRecognizer) -> None:
        # Invalid JSON that also has no JSON-like substring
        content = "not json at all"
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] is None
        assert out["raw_response"] == "not json at all"

    def test_regex_fallback_no_match(self, recognizer: DeepSeekIntentRecognizer) -> None:
        content = "text without any braces"
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] is None

    def test_code_fence_multiple_lines_before_brace(
        self, recognizer: DeepSeekIntentRecognizer
    ) -> None:
        content = '```\nline1\nline2\n{"intent": "greet", "confidence": 0.8, "slots": {}}\n```'
        out = recognizer._parse_response(content, "msg")
        assert out["intent"] == "greet"


# ── _normalize_slots deep ────────────────────────────────────────────────────


class TestNormalizeSlotsDeep:
    @pytest.fixture
    def recognizer(self) -> DeepSeekIntentRecognizer:
        return DeepSeekIntentRecognizer(api_key="k")

    def test_quantity_tins_digit_in_value(self, recognizer: DeepSeekIntentRecognizer) -> None:
        out = recognizer._normalize_slots({"quantity_tins": "5"}, "")
        assert out["quantity_tins"] == 5

    def test_quantity_tins_chinese_number_in_value(
        self, recognizer: DeepSeekIntentRecognizer
    ) -> None:
        out = recognizer._normalize_slots({"quantity_tins": "三桶"}, "")
        assert out["quantity_tins"] == 3

    def test_quantity_tins_no_digit_falls_to_value(
        self, recognizer: DeepSeekIntentRecognizer
    ) -> None:
        out = recognizer._normalize_slots({"quantity_tins": "abc"}, "no digit here")
        # No digit in value or message, falls to keeping the value
        assert out["quantity_tins"] == "abc"

    def test_tin_spec_digit_in_value(self, recognizer: DeepSeekIntentRecognizer) -> None:
        out = recognizer._normalize_slots({"tin_spec": "28"}, "")
        assert out["tin_spec"] == 28.0

    def test_tin_spec_no_digit_keeps_value(self, recognizer: DeepSeekIntentRecognizer) -> None:
        out = recognizer._normalize_slots({"tin_spec": "abc"}, "")
        assert out["tin_spec"] == "abc"

    def test_unit_name_pattern_1_give_prefix(self, recognizer: DeepSeekIntentRecognizer) -> None:
        # Pattern: 给\s*([^\s，,。]+)
        out = recognizer._normalize_slots({"unit_name": "x"}, "给客户A")
        assert out["unit_name"] == "客户A"

    def test_unit_name_no_match_keeps_value(self, recognizer: DeepSeekIntentRecognizer) -> None:
        out = recognizer._normalize_slots({"unit_name": "custom"}, "no pattern")
        assert out["unit_name"] == "custom"

    def test_empty_value_skipped(self, recognizer: DeepSeekIntentRecognizer) -> None:
        out = recognizer._normalize_slots({"key": ""}, "")
        assert "key" not in out

    def test_whitespace_value_skipped(self, recognizer: DeepSeekIntentRecognizer) -> None:
        # "   " is truthy so `if not value:` doesn't skip it.
        # After strip(), value becomes "" but the key is still added (for non-special keys).
        out = recognizer._normalize_slots({"key": "   "}, "")
        # For unknown keys, the stripped (empty) value is kept
        assert out.get("key") == ""

    def test_none_value_skipped(self, recognizer: DeepSeekIntentRecognizer) -> None:
        out = recognizer._normalize_slots({"key": None}, "")  # type: ignore[dict-item]
        assert "key" not in out


# ── _cn_to_number deep ───────────────────────────────────────────────────────


class TestCnToNumberDeep:
    @pytest.fixture
    def recognizer(self) -> DeepSeekIntentRecognizer:
        return DeepSeekIntentRecognizer(api_key="k")

    def test_single_digit(self, recognizer: DeepSeekIntentRecognizer) -> None:
        assert recognizer._cn_to_number("五") == 5

    def test_multi_digit(self, recognizer: DeepSeekIntentRecognizer) -> None:
        assert recognizer._cn_to_number("一二三") == 123

    def test_arabic_digit(self, recognizer: DeepSeekIntentRecognizer) -> None:
        assert recognizer._cn_to_number("8") == 8

    def test_empty_returns_0(self, recognizer: DeepSeekIntentRecognizer) -> None:
        assert recognizer._cn_to_number("") == 0

    def test_no_cn_no_digit_returns_0(self, recognizer: DeepSeekIntentRecognizer) -> None:
        assert recognizer._cn_to_number("abc") == 0

    def test_mixed_cn_and_digit(self, recognizer: DeepSeekIntentRecognizer) -> None:
        # "x9y" → int("9") = 9 via the except branch
        assert recognizer._cn_to_number("x9y") == 9


# ── recognize async deep ─────────────────────────────────────────────────────


class TestRecognizeAsyncDeep:
    @pytest.fixture
    def recognizer(self) -> DeepSeekIntentRecognizer:
        return DeepSeekIntentRecognizer(api_key="k", max_retries=2)

    async def test_recognize_cache_hit(
        self, recognizer: DeepSeekIntentRecognizer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = "RECOGNIZE_CACHE_HIT_UNIQUE_DEEP_001"
        cached_result = {"intent": "greet", "confidence": 0.9, "slots": {"k": "v"}}
        mock_cache = MagicMock()
        mock_cache.get.return_value = cached_result
        monkeypatch.setattr(ds, "_intent_recognition_cache", mock_cache)
        out = await recognizer.recognize(msg)
        assert out == cached_result
        mock_cache.get.assert_called_once()

    async def test_recognize_success_caches_result(
        self, recognizer: DeepSeekIntentRecognizer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = "RECOGNIZE_SUCCESS_CACHE_UNIQUE_DEEP_002"
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        monkeypatch.setattr(ds, "_intent_recognition_cache", mock_cache)
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": '{"intent": "greet", "confidence": 0.8, "slots": {}}'
                            }
                        }
                    ]
                }
            ),
        ):
            out = await recognizer.recognize(msg)
        assert out["intent"] == "greet"
        mock_cache.set.assert_called_once()

    async def test_recognize_with_context(
        self, recognizer: DeepSeekIntentRecognizer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = "RECOGNIZE_WITH_CONTEXT_UNIQUE_DEEP_003"
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        monkeypatch.setattr(ds, "_intent_recognition_cache", mock_cache)
        context = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": '{"intent": "greet", "confidence": 0.8, "slots": {}}'
                            }
                        }
                    ]
                }
            ),
        ) as mock_llm:
            out = await recognizer.recognize(msg, context)
        assert out["intent"] == "greet"
        # Verify context was included in the user message
        # call_args[0] is the positional args tuple: ([messages],)
        # messages[1] is the user message dict
        call_args = mock_llm.call_args
        messages = call_args[0][0]
        assert "对话历史" in messages[1]["content"]

    async def test_recognize_all_fail_caches_fallback(
        self, recognizer: DeepSeekIntentRecognizer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = "RECOGNIZE_ALL_FAIL_CACHE_UNIQUE_DEEP_004"
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        monkeypatch.setattr(ds, "_intent_recognition_cache", mock_cache)
        with (
            patch(
                "app.infrastructure.llm.invoke.chat_completion_openai_format",
                new=AsyncMock(side_effect=RuntimeError("always fail")),
            ),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            out = await recognizer.recognize(msg)
        assert out["intent"] is None
        # Fallback should be cached
        mock_cache.set.assert_called_once()


# ── _fallback_result deep ────────────────────────────────────────────────────


class TestFallbackResultDeep:
    def test_fallback_with_raw_response(self) -> None:
        r = DeepSeekIntentRecognizer(api_key="k")
        out = r._fallback_result("msg", "raw text")
        assert out["intent"] is None
        assert out["confidence"] == 0.0
        assert out["slots"] == {}
        assert out["source"] == "deepseek"
        assert out["raw_response"] == "raw text"

    def test_fallback_without_raw_response(self) -> None:
        r = DeepSeekIntentRecognizer(api_key="k")
        out = r._fallback_result("msg")
        assert out["raw_response"] == ""


# ── HybridIntentWithDeepSeek deep ────────────────────────────────────────────


class TestHybridRecognizeDeep:
    async def test_greeting_returns_rule_directly(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=True)
        rule = {"primary_intent": "greet", "is_greeting": True, "tool_key": "greet"}
        with (
            patch("app.services.intent_service.recognize_intents", return_value=dict(rule)),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            out = await h.recognize("你好")
        assert out["intent_source"] == "rule"
        assert out["final_intent"] == "greet"

    async def test_rule_primary_intent_not_unk_returns_rule(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=True)
        rule = {"primary_intent": "products", "tool_key": "products"}
        with (
            patch("app.services.intent_service.recognize_intents", return_value=dict(rule)),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            out = await h.recognize("查看产品")
        assert out["intent_source"] == "rule"
        assert out["final_intent"] == "products"

    async def test_deepseek_high_confidence_used(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=True, confidence_threshold=0.5)
        rule = {"primary_intent": "unk"}
        with (
            patch("app.services.intent_service.recognize_intents", return_value=dict(rule)),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
            patch.object(
                h.deepseek_recognizer,
                "recognize",
                new=AsyncMock(
                    return_value={"intent": "order", "confidence": 0.9, "slots": {"k": "v"}}
                ),
            ),
        ):
            out = await h.recognize("msg")
        assert out["intent_source"] == "deepseek"
        assert out["final_intent"] == "order"

    async def test_deepseek_low_confidence_used(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=True, confidence_threshold=0.8)
        rule = {"primary_intent": "unk"}
        with (
            patch("app.services.intent_service.recognize_intents", return_value=dict(rule)),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
            patch.object(
                h.deepseek_recognizer,
                "recognize",
                new=AsyncMock(
                    return_value={"intent": "order", "confidence": 0.3, "slots": {"k": "v"}}
                ),
            ),
        ):
            out = await h.recognize("msg")
        assert out["intent_source"] == "deepseek_low_confidence"

    async def test_deepseek_error_falls_to_rule(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=True, confidence_threshold=0.5)
        rule = {"primary_intent": "unk"}
        with (
            patch("app.services.intent_service.recognize_intents", return_value=dict(rule)),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
            patch.object(
                h.deepseek_recognizer,
                "recognize",
                new=AsyncMock(side_effect=RuntimeError("ds fail")),
            ),
        ):
            out = await h.recognize("msg")
        assert out["intent_source"] == "rule"


# ─_extract_slots_from_rule deep ─────────────────────────────────────────────


class TestExtractSlotsFromRuleDeep:
    @pytest.fixture
    def hybrid(self) -> HybridIntentWithDeepSeek:
        return HybridIntentWithDeepSeek(use_deepseek=False)

    @pytest.fixture(autouse=True)
    def _no_db_resolver(self):
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            yield

    def test_fahuo_prefix_extracts_unit(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("发货单海底捞", {})
        assert slots.get("unit_name") == "海底捞"

    def test_quantity_chinese_number(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("三桶", {})
        assert slots.get("quantity_tins") == 3

    def test_quantity_arabic_number(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("5桶", {})
        assert slots.get("quantity_tins") == 5

    def test_spec_extracted(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("规格28", {})
        assert slots.get("tin_spec") == 28.0

    def test_product_model_single(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("9803", {})
        assert slots.get("product_model") == "9803"

    def test_product_model_multiple(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("9803 9804", {})
        assert "products" in slots
        assert len(slots["products"]) == 2

    def test_product_model_with_spec(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("9803规格28", {})
        assert slots.get("product_model") == "9803"
        assert slots.get("tin_spec") == 28.0

    def test_no_slots_extracted_from_simple_msg(self, hybrid: HybridIntentWithDeepSeek) -> None:
        slots = hybrid._extract_slots_from_rule("hello", {})
        assert "unit_name" not in slots
        assert "quantity_tins" not in slots


# ── recognize_sync deep ──────────────────────────────────────────────────────


class TestRecognizeSyncDeep:
    def test_recognize_sync_success(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=False)
        rule = {"primary_intent": "greet", "is_greeting": True}
        with (
            patch("app.services.intent_service.recognize_intents", return_value=dict(rule)),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            out = h.recognize_sync("你好")
        assert out.get("final_intent") == "greet" or out.get("primary_intent") == "greet"

    def test_recognize_sync_recoverable_error(self) -> None:
        h = HybridIntentWithDeepSeek(use_deepseek=False)
        with (
            patch.object(h, "recognize", new=AsyncMock(side_effect=RuntimeError("sync fail"))),
            patch(
                "app.services.intent_service.recognize_intents",
                return_value={"primary_intent": "fallback"},
            ),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            out = h.recognize_sync("msg")
        assert out["primary_intent"] == "fallback"


# ── cn_to_number module-level deep ───────────────────────────────────────────


class TestCnToNumberModuleDeep:
    def test_all_single_digits(self) -> None:
        assert cn_to_number("零") == 0
        assert cn_to_number("〇") == 0
        assert cn_to_number("一") == 1
        assert cn_to_number("二") == 2
        assert cn_to_number("两") == 2
        assert cn_to_number("三") == 3
        assert cn_to_number("四") == 4
        assert cn_to_number("五") == 5
        assert cn_to_number("六") == 6
        assert cn_to_number("七") == 7
        assert cn_to_number("八") == 8
        assert cn_to_number("九") == 9
        assert cn_to_number("十") == 10

    def test_multi_digit(self) -> None:
        assert cn_to_number("一二三") == 123

    def test_arabic(self) -> None:
        assert cn_to_number("8") == 8

    def test_empty(self) -> None:
        assert cn_to_number("") == 0

    def test_no_match(self) -> None:
        assert cn_to_number("abc") == 0

    def test_mixed(self) -> None:
        assert cn_to_number("x9y") == 9


# ── get_deepseek_api_key deep ────────────────────────────────────────────────


class TestGetDeepseekApiKeyDeep:
    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        assert get_deepseek_api_key() == "env-key"

    def test_no_env_no_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch(
            "app.utils.path_utils.get_resource_path",
            return_value=None,
        ):
            assert get_deepseek_api_key() == ""

    def test_config_path_not_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=False),
        ):
            assert get_deepseek_api_key() == ""

    def test_config_spec_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=True),
            patch("importlib.util.spec_from_file_location", return_value=None),
        ):
            assert get_deepseek_api_key() == ""

    def test_config_loader_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        mock_spec = MagicMock()
        mock_spec.loader = None
        with (
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/fake/config.py",
            ),
            patch("os.path.exists", return_value=True),
            patch("importlib.util.spec_from_file_location", return_value=mock_spec),
        ):
            assert get_deepseek_api_key() == ""


# ── Singleton accessors deep ─────────────────────────────────────────────────


class TestSingletonsDeep:
    def test_get_deepseek_recognizer_returns_singleton(self) -> None:
        reset_deepseek_intent_services()
        r1 = get_deepseek_intent_recognizer()
        r2 = get_deepseek_intent_recognizer()
        assert r1 is r2
        reset_deepseek_intent_services()

    def test_get_hybrid_returns_singleton(self) -> None:
        reset_deepseek_intent_services()
        h1 = get_hybrid_intent_with_deepseek(use_deepseek=False)
        h2 = get_hybrid_intent_with_deepseek(use_deepseek=False)
        assert h1 is h2
        reset_deepseek_intent_services()

    def test_get_hybrid_reset_creates_new(self) -> None:
        reset_deepseek_intent_services()
        h1 = get_hybrid_intent_with_deepseek(use_deepseek=False)
        h2 = get_hybrid_intent_with_deepseek(use_deepseek=False, reset=True)
        assert h1 is not h2
        reset_deepseek_intent_services()
