"""DeepSeek 意图识别服务 — 全面单元测试。

覆盖纯逻辑（缓存键/响应解析/槽位归一化/中文数字/降级）、async 识别（缓存命中、
LLM 成功、错误降级）、混合识别（规则优先/打招呼/DeepSeek 高低置信度/异常降级）、
规则槽位提取（给/帮/发货单 前缀、数量、规格、产品型号）。

铁律4：仅 mock 外部边界（LLM HTTP `chat_completion_openai_format`、
`resolve_purchase_unit` 的持久化查询）；内部纯函数真实调用。无网络/PG/Redis。
铁律5：消息使用唯一串避免模块级缓存跨用例污染，结果可复现。
"""

from __future__ import annotations

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


class TestDeepSeekIntentRecognizer:
    """DeepSeek 意图识别器测试（保留原有 smoke 用例）。"""

    @pytest.fixture
    def recognizer(self):
        return DeepSeekIntentRecognizer(api_key="test-key", confidence_threshold=0.5)

    def test_recognizer_init(self, recognizer):
        assert recognizer.api_key == "test-key"
        assert recognizer.confidence_threshold == 0.5

    def test_recognizer_has_required_methods(self, recognizer):
        assert hasattr(recognizer, "recognize")
        assert callable(getattr(recognizer, "recognize", None))


# --------------------------------------------------------------------------- #
# 模块级纯函数
# --------------------------------------------------------------------------- #
class TestModuleHelpers:
    def test_make_intent_cache_key_deterministic(self):
        k1 = ds._make_intent_cache_key("查产品")
        k2 = ds._make_intent_cache_key("查产品")
        assert k1 == k2 and len(k1) == 64  # sha256 hexdigest

    def test_make_intent_cache_key_normalizes_case_and_space(self):
        assert ds._make_intent_cache_key("  Hello ") == ds._make_intent_cache_key("hello")

    def test_make_intent_cache_key_distinct_for_distinct_input(self):
        assert ds._make_intent_cache_key("查产品") != ds._make_intent_cache_key("查客户")

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("一", 1),
            ("二", 2),
            ("两", 2),
            ("十", 10),
            ("8", 8),
            ("", 0),
            ("abc", 0),
            ("x9y", 9),  # 无中文 → int 失败 → 正则兜底取数字
        ],
    )
    def test_cn_to_number(self, text, expected):
        assert cn_to_number(text) == expected

    def test_get_deepseek_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
        assert get_deepseek_api_key() == "env-secret"

    def test_get_deepseek_api_key_missing_returns_empty(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch("app.utils.path_utils.get_resource_path", return_value="/no/such/config.py"):
            assert get_deepseek_api_key() == ""

    def test_get_deepseek_recognizer_singleton(self):
        reset_deepseek_intent_services()
        a = get_deepseek_intent_recognizer()
        b = get_deepseek_intent_recognizer()
        assert a is b
        reset_deepseek_intent_services()
        c = get_deepseek_intent_recognizer()
        assert c is not a

    def test_get_hybrid_singleton_and_reset_flag(self):
        reset_deepseek_intent_services()
        h1 = get_hybrid_intent_with_deepseek(use_deepseek=False)
        h2 = get_hybrid_intent_with_deepseek(use_deepseek=False)
        assert h1 is h2
        h3 = get_hybrid_intent_with_deepseek(use_deepseek=False, reset=True)
        assert h3 is not h1
        reset_deepseek_intent_services()


# --------------------------------------------------------------------------- #
# _get_api_key
# --------------------------------------------------------------------------- #
class TestGetApiKey:
    def test_prefers_explicit_api_key(self):
        r = DeepSeekIntentRecognizer(api_key="explicit")
        assert r._get_api_key() == "explicit"

    def test_reads_env_when_no_explicit_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        r = DeepSeekIntentRecognizer(api_key=None)
        assert r._get_api_key() == "from-env"

    def test_empty_when_no_key_anywhere(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch("app.utils.path_utils.get_resource_path", return_value="/no/such/cfg.py"):
            r = DeepSeekIntentRecognizer(api_key=None)
            assert r._get_api_key() == ""


# --------------------------------------------------------------------------- #
# _parse_response
# --------------------------------------------------------------------------- #
class TestParseResponse:
    @pytest.fixture
    def recognizer(self):
        return DeepSeekIntentRecognizer(api_key="k")

    def test_valid_json(self, recognizer):
        content = '{"intent": "products", "confidence": 0.9, "slots": {}, "reasoning": "r"}'
        out = recognizer._parse_response(content, "查产品")
        assert out["intent"] == "products"
        assert out["confidence"] == 0.9
        assert out["source"] == "deepseek"

    def test_confidence_clamped_to_one(self, recognizer):
        content = '{"intent": "products", "confidence": 2.5, "slots": {}, "reasoning": ""}'
        out = recognizer._parse_response(content, "查产品")
        assert out["confidence"] == 1.0

    def test_negation_intent_allowed(self, recognizer):
        content = '{"intent": "negation", "confidence": 0.7, "slots": {}, "reasoning": ""}'
        out = recognizer._parse_response(content, "不要")
        assert out["intent"] == "negation"

    def test_code_fence_then_regex_fallback(self, recognizer):
        content = '```json\n{"intent": "greet", "confidence": 0.8, "slots": {}, "reasoning": ""}\n```'
        out = recognizer._parse_response(content, "你好")
        assert out["intent"] == "greet"
        assert out["source"] == "deepseek"

    def test_invalid_intent_falls_back(self, recognizer):
        content = '{"intent": "NOT_REAL", "confidence": 0.9, "slots": {}, "reasoning": ""}'
        out = recognizer._parse_response(content, "随便")
        assert out["intent"] is None
        assert out["confidence"] == 0.0

    def test_non_json_falls_back(self, recognizer):
        out = recognizer._parse_response("这不是 JSON", "随便")
        assert out["intent"] is None
        assert out["raw_response"] == "这不是 JSON"


# --------------------------------------------------------------------------- #
# _normalize_slots / _fallback_result
# --------------------------------------------------------------------------- #
class TestNormalizeSlots:
    @pytest.fixture
    def recognizer(self):
        return DeepSeekIntentRecognizer(api_key="k")

    def test_quantity_tins_arabic_with_tin(self, recognizer):
        out = recognizer._normalize_slots({"quantity_tins": "3桶"}, "")
        assert out["quantity_tins"] == 3

    def test_quantity_tins_chinese_in_message(self, recognizer):
        out = recognizer._normalize_slots({"quantity_tins": "三桶"}, "")
        assert out["quantity_tins"] == 3

    def test_quantity_tins_digit_only_value(self, recognizer):
        out = recognizer._normalize_slots({"quantity_tins": "5"}, "")
        assert out["quantity_tins"] == 5

    def test_tin_spec_from_message_guige(self, recognizer):
        out = recognizer._normalize_slots({"tin_spec": "x"}, "规格 28 的产品")
        assert out["tin_spec"] == 28.0

    def test_tin_spec_from_value(self, recognizer):
        out = recognizer._normalize_slots({"tin_spec": "20"}, "")
        assert out["tin_spec"] == 20.0

    def test_tin_spec_non_numeric_kept_as_value(self, recognizer):
        out = recognizer._normalize_slots({"tin_spec": "abc"}, "")
        assert out["tin_spec"] == "abc"

    def test_unit_name_from_gei_pattern(self, recognizer):
        out = recognizer._normalize_slots({"unit_name": "X"}, "给七彩乐园,发货")
        assert out["unit_name"] == "七彩乐园"

    def test_unit_name_no_match_keeps_value(self, recognizer):
        out = recognizer._normalize_slots({"unit_name": "默认单位"}, "xyz")
        assert out["unit_name"] == "默认单位"

    def test_empty_value_skipped(self, recognizer):
        out = recognizer._normalize_slots({"quantity_tins": ""}, "")
        assert "quantity_tins" not in out

    def test_contact_person_passthrough(self, recognizer):
        out = recognizer._normalize_slots({"contact_person": "向总"}, "")
        assert out["contact_person"] == "向总"

    def test_other_key_passthrough(self, recognizer):
        out = recognizer._normalize_slots({"keyword": "雨衣"}, "")
        assert out["keyword"] == "雨衣"

    def test_fallback_result_shape(self, recognizer):
        out = recognizer._fallback_result("msg", "raw text")
        assert out["intent"] is None
        assert out["confidence"] == 0.0
        assert out["source"] == "deepseek"
        assert out["raw_response"] == "raw text"


# --------------------------------------------------------------------------- #
# recognize (async)
# --------------------------------------------------------------------------- #
class TestRecognizeAsync:
    @pytest.fixture
    def recognizer(self):
        return DeepSeekIntentRecognizer(api_key="k", confidence_threshold=0.5, max_retries=1)

    async def test_recognize_cache_hit(self, recognizer):
        msg = "CACHE_HIT_UNIQUE_MESSAGE_001"
        key = ds._make_intent_cache_key(msg)
        ds._intent_recognition_cache.set(key, {"intent": "products", "source": "cached", "slots": {}})
        out = await recognizer.recognize(msg)
        assert out["source"] == "cached"
        assert out["intent"] == "products"

    async def test_recognize_success_with_mocked_llm(self, recognizer):
        msg = "RECOGNIZE_SUCCESS_UNIQUE_002 查产品"
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"intent": "products", "confidence": 0.95, "slots": {}, "reasoning": "ok"}'
                    }
                }
            ]
        }
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=payload),
        ) as mock_llm:
            out = await recognizer.recognize(msg)
        assert out["intent"] == "products"
        assert out["source"] == "deepseek"
        mock_llm.assert_awaited_once()

    async def test_recognize_passes_context_history(self, recognizer):
        msg = "RECOGNIZE_CONTEXT_UNIQUE_003"
        payload = {
            "choices": [
                {"message": {"content": '{"intent": "greet", "confidence": 0.8, "slots": {}}'}}
            ]
        }
        ctx = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好"}]
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=payload),
        ) as mock_llm:
            out = await recognizer.recognize(msg, context=ctx)
        assert out["intent"] == "greet"
        sent_user_msg = mock_llm.await_args.args[0][1]["content"]
        assert "对话历史" in sent_user_msg

    async def test_recognize_falls_back_on_recoverable_error(self, recognizer):
        msg = "RECOGNIZE_ERROR_UNIQUE_004"
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            out = await recognizer.recognize(msg)
        assert out["intent"] is None
        assert out["source"] == "deepseek"


# --------------------------------------------------------------------------- #
# HybridIntentWithDeepSeek.recognize (async)
# --------------------------------------------------------------------------- #
class TestHybridRecognize:
    def test_init_without_deepseek(self):
        h = HybridIntentWithDeepSeek(use_deepseek=False)
        assert h.deepseek_recognizer is None

    def test_init_with_deepseek_creates_recognizer(self):
        h = HybridIntentWithDeepSeek(use_deepseek=True)
        assert isinstance(h.deepseek_recognizer, DeepSeekIntentRecognizer)

    async def test_greeting_returns_rule_directly(self):
        h = HybridIntentWithDeepSeek(use_deepseek=True)
        rule = {"primary_intent": "greet", "is_greeting": True, "tool_key": "greet"}
        with patch("app.services.intent_service.recognize_intents", return_value=dict(rule)):
            out = await h.recognize("你好")
        assert out["intent_source"] == "rule"
        assert out["final_intent"] == "greet"
        assert out["sources_used"] == ["rule"]

    async def test_primary_intent_hit_skips_deepseek(self):
        h = HybridIntentWithDeepSeek(use_deepseek=True)
        rule = {"primary_intent": "products", "tool_key": "products"}
        # deepseek_recognizer 不应被调用
        h.deepseek_recognizer = MagicMock()
        h.deepseek_recognizer.recognize = AsyncMock(side_effect=AssertionError("不应调用"))
        with patch(
            "app.services.intent_service.recognize_intents", return_value=dict(rule)
        ), patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            out = await h.recognize("查产品")
        assert out["intent_source"] == "rule"
        assert out["final_intent"] == "products"

    async def test_unk_without_deepseek_returns_rule(self):
        h = HybridIntentWithDeepSeek(use_deepseek=False)
        rule = {"primary_intent": "unk"}
        with patch(
            "app.services.intent_service.recognize_intents", return_value=dict(rule)
        ), patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            out = await h.recognize("不明确的消息")
        assert out["intent_source"] == "rule"

    async def test_unk_with_deepseek_high_confidence(self):
        h = HybridIntentWithDeepSeek(use_deepseek=True, confidence_threshold=0.5)
        rule = {"primary_intent": "unk"}
        h.deepseek_recognizer = MagicMock()
        h.deepseek_recognizer.recognize = AsyncMock(
            return_value={"intent": "products", "confidence": 0.9, "slots": {"keyword": "雨衣"}}
        )
        with patch("app.services.intent_service.recognize_intents", return_value=dict(rule)):
            out = await h.recognize("帮我找点东西")
        assert out["final_intent"] == "products"
        assert out["intent_source"] == "deepseek"
        assert "deepseek" in out["sources_used"]

    async def test_unk_with_deepseek_low_confidence(self):
        h = HybridIntentWithDeepSeek(use_deepseek=True, confidence_threshold=0.8)
        rule = {"primary_intent": "unk"}
        h.deepseek_recognizer = MagicMock()
        h.deepseek_recognizer.recognize = AsyncMock(
            return_value={"intent": "products", "confidence": 0.3, "slots": {}}
        )
        with patch("app.services.intent_service.recognize_intents", return_value=dict(rule)):
            out = await h.recognize("模糊消息")
        assert out["intent_source"] == "deepseek_low_confidence"

    async def test_deepseek_error_falls_back_to_rule(self):
        h = HybridIntentWithDeepSeek(use_deepseek=True)
        rule = {"primary_intent": "unk"}
        h.deepseek_recognizer = MagicMock()
        h.deepseek_recognizer.recognize = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(
            "app.services.intent_service.recognize_intents", return_value=dict(rule)
        ), patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            out = await h.recognize("触发异常")
        assert out["intent_source"] == "rule"


# --------------------------------------------------------------------------- #
# _extract_slots_from_rule
# --------------------------------------------------------------------------- #
class TestExtractSlotsFromRule:
    @pytest.fixture
    def hybrid(self):
        return HybridIntentWithDeepSeek(use_deepseek=False)

    @pytest.fixture(autouse=True)
    def _no_db_resolver(self):
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=None,
        ):
            yield

    def test_gei_prefix_extracts_unit(self, hybrid):
        slots = hybrid._extract_slots_from_rule("给七彩乐园,发货", {})
        assert slots.get("unit_name") == "七彩乐园"

    def test_gei_prefix_rejects_invalid_unit(self, hybrid):
        slots = hybrid._extract_slots_from_rule("给 我 发货单", {})
        assert "unit_name" not in slots

    def test_bang_prefix_extracts_unit(self, hybrid):
        slots = hybrid._extract_slots_from_rule("帮我打七彩乐园的货", {})
        assert slots.get("unit_name") == "七彩乐园"

    def test_shipment_prefix_extracts_unit(self, hybrid):
        slots = hybrid._extract_slots_from_rule("发货单海底捞", {})
        assert slots.get("unit_name") == "海底捞"

    def test_quantity_arabic(self, hybrid):
        slots = hybrid._extract_slots_from_rule("来3桶", {})
        assert slots.get("quantity_tins") == 3

    def test_quantity_chinese(self, hybrid):
        slots = hybrid._extract_slots_from_rule("要五桶", {})
        assert slots.get("quantity_tins") == 5

    def test_spec_extraction(self, hybrid):
        slots = hybrid._extract_slots_from_rule("规格28", {})
        assert slots.get("tin_spec") == 28.0

    def test_single_product_model(self, hybrid):
        slots = hybrid._extract_slots_from_rule("型号9803", {})
        assert slots.get("product_model") == "9803"

    def test_multiple_product_models(self, hybrid):
        slots = hybrid._extract_slots_from_rule("9803 和 8500", {})
        assert "products" in slots
        assert len(slots["products"]) == 2

    def test_unit_name_replaced_when_resolver_hits(self, hybrid):
        resolved = MagicMock()
        resolved.unit_name = "七彩乐园有限公司"
        # 覆盖 autouse 的 None 桩：命中购买单位解析 → unit_name 被规范化替换
        with patch(
            "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
            return_value=resolved,
        ):
            slots = hybrid._extract_slots_from_rule("给七彩乐园,发货", {})
        assert slots["unit_name"] == "七彩乐园有限公司"


# --------------------------------------------------------------------------- #
# recognize_sync
# --------------------------------------------------------------------------- #
class TestRecognizeSync:
    def test_recognize_sync_greeting_via_rule(self):
        h = HybridIntentWithDeepSeek(use_deepseek=False)
        rule = {"primary_intent": "greet", "is_greeting": True}
        with patch("app.services.intent_service.recognize_intents", return_value=dict(rule)):
            out = h.recognize_sync("你好")
        assert out.get("final_intent") == "greet" or out.get("primary_intent") == "greet"
