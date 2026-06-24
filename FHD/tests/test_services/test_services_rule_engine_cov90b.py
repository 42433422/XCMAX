from __future__ import annotations

"""Real-behavior coverage tests for app/services/rule_engine.py.

Targets the uncovered RuleEngine class methods (reload, _match_patterns named/anonymous
groups, match_intents empty + sort/priority, match_hint_intents empty + loop, and the
whole check_special_intent branch matrix). All external config/cache deps are mocked so
the tests are deterministic, offline and fast.

The RuleEngine.__init__ calls get_intent_config(); we patch that at the rule_engine import
site so construction is controlled, then drive each method by assigning engine._config
directly to a tailored dict.
"""

from unittest.mock import MagicMock, patch

import pytest

import app.services.rule_engine as re_mod
from app.services.rule_engine import (
    RuleEngine,
    _make_cache_key,
    get_rule_engine,
    reload_rule_engine,
)


def _make_engine(config: dict | None = None) -> RuleEngine:
    """Construct a RuleEngine with a controlled config (no real file IO)."""
    with patch.object(re_mod, "get_intent_config", return_value=(config or {})):
        engine = RuleEngine()
    engine._config = config or {}
    return engine


# ---------------------------------------------------------------------------
# _make_cache_key (line 27)
# ---------------------------------------------------------------------------


class TestMakeCacheKey:
    def test_key_is_deterministic_md5_hex(self):
        key = _make_cache_key("Hello World", "intent_a")
        # md5 hex digest is 32 chars
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)

    def test_key_normalizes_case_and_whitespace(self):
        # message is lowercased + stripped before hashing -> these collide
        a = _make_cache_key("  Hello  ", "x")
        b = _make_cache_key("hello", "x")
        assert a == b

    def test_key_varies_by_intent_id(self):
        assert _make_cache_key("hi", "a") != _make_cache_key("hi", "b")


# ---------------------------------------------------------------------------
# __init__ + reload (lines 33-34, 38-39)
# ---------------------------------------------------------------------------


class TestInitAndReload:
    def test_init_loads_config(self):
        cfg = {"tool_intents": [{"id": "x"}]}
        with patch.object(re_mod, "get_intent_config", return_value=cfg) as gic:
            engine = RuleEngine()
        gic.assert_called_once()
        assert engine._config is cfg

    def test_reload_replaces_config_and_clears_cache(self):
        engine = _make_engine({"old": True})
        new_cfg = {"tool_intents": [], "new": True}
        with (
            patch.object(re_mod, "reload_intent_config", return_value=new_cfg) as ric,
            patch.object(re_mod, "_match_cache") as cache,
        ):
            engine.reload()
        ric.assert_called_once()
        cache.clear.assert_called_once()
        assert engine._config is new_cfg


# ---------------------------------------------------------------------------
# _normalize + _match_keywords (helpers used by other paths)
# ---------------------------------------------------------------------------


class TestNormalizeAndKeywords:
    def test_normalize_strips(self):
        engine = _make_engine()
        assert engine._normalize("  hi  ") == "hi"

    def test_normalize_none_returns_empty(self):
        engine = _make_engine()
        assert engine._normalize(None) == ""  # type: ignore[arg-type]

    def test_match_keywords_case_insensitive_hit(self):
        engine = _make_engine()
        assert engine._match_keywords("Buy ORDER now", ["order"]) is True

    def test_match_keywords_direct_substring_hit(self):
        engine = _make_engine()
        # Chinese keyword present verbatim
        assert engine._match_keywords("我要发货单", ["发货单"]) is True

    def test_match_keywords_no_hit(self):
        engine = _make_engine()
        assert engine._match_keywords("nothing here", ["xyz"]) is False


# ---------------------------------------------------------------------------
# _match_patterns (lines 53-59, esp. 58 named vs anonymous groups)
# ---------------------------------------------------------------------------


class TestMatchPatterns:
    def test_named_groups_returned(self):
        engine = _make_engine()
        result = engine._match_patterns("qty 42 here", [r"qty (?P<n>\d+)"])
        assert result == {"n": "42"}

    def test_anonymous_match_returns_full_match(self):
        engine = _make_engine()
        # pattern matches but has no named groups -> {"match": <group0>}
        result = engine._match_patterns("abc123", [r"\d+"])
        assert result == {"match": "123"}

    def test_first_pattern_wins(self):
        engine = _make_engine()
        result = engine._match_patterns("hello world", [r"world", r"hello"])
        assert result == {"match": "world"}

    def test_no_pattern_matches_returns_none(self):
        engine = _make_engine()
        assert engine._match_patterns("plain text", [r"\d{5}"]) is None


# ---------------------------------------------------------------------------
# match_tool_intent (lines 70-79)
# ---------------------------------------------------------------------------


class TestMatchToolIntent:
    def test_keyword_only_no_patterns(self):
        engine = _make_engine()
        matched, captured = engine.match_tool_intent(
            "查产品列表", {"keywords": ["产品"], "patterns": []}
        )
        assert matched is True
        assert captured is None

    def test_keyword_and_patterns_returns_captured(self):
        engine = _make_engine()
        matched, captured = engine.match_tool_intent(
            "产品编号9803",
            {"keywords": ["产品"], "patterns": [r"(?P<code>\d{4})"]},
        )
        assert matched is True
        assert captured == {"code": "9803"}

    def test_keyword_with_patterns_but_no_pattern_match(self):
        engine = _make_engine()
        matched, captured = engine.match_tool_intent(
            "查产品", {"keywords": ["产品"], "patterns": [r"\d{4}"]}
        )
        assert matched is True
        assert captured is None

    def test_no_keyword_match_returns_false(self):
        engine = _make_engine()
        matched, captured = engine.match_tool_intent(
            "天气如何", {"keywords": ["产品"], "patterns": [r"\d+"]}
        )
        assert matched is False
        assert captured is None


# ---------------------------------------------------------------------------
# match_intents (lines 88-110, esp. 90 empty + 109 priority sort)
# ---------------------------------------------------------------------------


class TestMatchIntents:
    def test_empty_message_returns_empty_list(self):
        engine = _make_engine({"tool_intents": [{"id": "x", "keywords": ["x"]}]})
        assert engine.match_intents("   ") == []

    def test_empty_message_none_input(self):
        engine = _make_engine({"tool_intents": [{"id": "x", "keywords": ["x"]}]})
        assert engine.match_intents(None) == []  # type: ignore[arg-type]

    def test_single_match_default_fields(self):
        cfg = {
            "tool_intents": [
                {"id": "products", "keywords": ["产品"]},
            ]
        }
        engine = _make_engine(cfg)
        result = engine.match_intents("查产品")
        assert len(result) == 1
        m = result[0]
        assert m["id"] == "products"
        # tool_key defaults to id when not provided
        assert m["tool_key"] == "products"
        assert m["priority"] == 0
        assert m["block_if_negated"] is False
        assert m["keywords"] == ["产品"]
        assert m["captured"] is None

    def test_explicit_fields_preserved(self):
        cfg = {
            "tool_intents": [
                {
                    "id": "ship",
                    "tool_key": "shipment_generate",
                    "priority": 5,
                    "block_if_negated": True,
                    "keywords": ["发货单"],
                    "patterns": [r"(?P<n>\d+)桶"],
                },
            ]
        }
        engine = _make_engine(cfg)
        result = engine.match_intents("发货单3桶")
        assert len(result) == 1
        m = result[0]
        assert m["tool_key"] == "shipment_generate"
        assert m["priority"] == 5
        assert m["block_if_negated"] is True
        assert m["captured"] == {"n": "3"}

    def test_multiple_matches_sorted_by_priority_desc(self):
        cfg = {
            "tool_intents": [
                {"id": "low", "keywords": ["共有"], "priority": 1},
                {"id": "high", "keywords": ["共有"], "priority": 9},
                {"id": "mid", "keywords": ["共有"], "priority": 5},
            ]
        }
        engine = _make_engine(cfg)
        result = engine.match_intents("共有关键词")
        ids = [m["id"] for m in result]
        assert ids == ["high", "mid", "low"]

    def test_no_tool_intents_key_returns_empty(self):
        engine = _make_engine({})  # no "tool_intents"
        assert engine.match_intents("anything") == []

    def test_non_matching_intent_excluded(self):
        cfg = {
            "tool_intents": [
                {"id": "products", "keywords": ["产品"]},
                {"id": "other", "keywords": ["天气"]},
            ]
        }
        engine = _make_engine(cfg)
        result = engine.match_intents("查产品")
        assert [m["id"] for m in result] == ["products"]


# ---------------------------------------------------------------------------
# match_hint_intents (lines 114-126, esp. 116 empty + 121-124 loop)
# ---------------------------------------------------------------------------


class TestMatchHintIntents:
    def test_empty_message_returns_empty(self):
        engine = _make_engine({"hint_intents": [{"id": "h", "keywords": ["h"]}]})
        assert engine.match_hint_intents("") == []

    def test_matching_hint_collected(self):
        cfg = {
            "hint_intents": [
                {"id": "template_query", "keywords": ["模板"]},
                {"id": "upload_file", "keywords": ["上传"]},
            ]
        }
        engine = _make_engine(cfg)
        assert engine.match_hint_intents("查询模板") == ["template_query"]

    def test_multiple_hints_collected_in_order(self):
        cfg = {
            "hint_intents": [
                {"id": "a", "keywords": ["模板"]},
                {"id": "b", "keywords": ["上传"]},
            ]
        }
        engine = _make_engine(cfg)
        assert engine.match_hint_intents("上传模板文件") == ["a", "b"]

    def test_no_hint_intents_key_returns_empty(self):
        engine = _make_engine({})
        assert engine.match_hint_intents("anything") == []

    def test_non_matching_hint_excluded(self):
        cfg = {"hint_intents": [{"id": "h", "keywords": ["模板"]}]}
        engine = _make_engine(cfg)
        assert engine.match_hint_intents("查产品") == []


# ---------------------------------------------------------------------------
# check_special_intent (lines 130-180)
# ---------------------------------------------------------------------------


class TestCheckSpecialIntent:
    def test_empty_message_returns_empty_dict(self):
        engine = _make_engine({"negation": {}})
        assert engine.check_special_intent("   ") == {}

    def test_negation_via_phrase(self):
        cfg = {"negation": {"phrases": ["不要"], "prefixes": []}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("我不要这个")
        assert result["is_negation"] is True

    def test_negation_via_prefix_startswith(self):
        cfg = {"negation": {"phrases": [], "prefixes": ["别"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("别开单了")
        assert result["is_negation"] is True

    def test_negation_via_prefix_after_space(self):
        # " " + prefix in msg_lower path (line 151)
        cfg = {"negation": {"phrases": [], "prefixes": ["no"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("yes no thanks")
        assert result["is_negation"] is True

    def test_negation_via_prefix_after_chinese_comma(self):
        # "，" + prefix in msg_lower path (line 151)
        cfg = {"negation": {"phrases": [], "prefixes": ["别"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("好的，别开单")
        assert result["is_negation"] is True

    def test_no_negation_when_prefix_only_inside_word(self):
        # prefix exists but not at start, not after space/comma -> not negation
        cfg = {"negation": {"phrases": [], "prefixes": ["xno"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("fooxnobar")
        assert result["is_negation"] is False

    def test_phrase_short_circuits_prefix_scan(self):
        # phrase matches -> is_negation True, prefix loop skipped (line 146 guard)
        cfg = {"negation": {"phrases": ["不要"], "prefixes": ["别"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("我不要")
        assert result["is_negation"] is True

    def test_greeting_detected(self):
        cfg = {"negation": {}, "greeting": {"patterns": ["你好"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("你好啊")
        assert result["is_greeting"] is True
        assert result["is_negation"] is False

    def test_greeting_case_insensitive(self):
        cfg = {"negation": {}, "greeting": {"patterns": ["hello"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("HELLO there")
        assert result["is_greeting"] is True

    def test_goodbye_detected(self):
        cfg = {"negation": {}, "goodbye": {"patterns": ["拜拜"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("好的拜拜")
        assert result["is_goodbye"] is True

    def test_help_detected(self):
        cfg = {"negation": {}, "help": {"patterns": ["帮助"]}}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("需要帮助")
        assert result["is_help"] is True

    def test_confirmation_exact_match(self):
        cfg = {"negation": {}, "confirmation_keywords": ["确定"]}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("确定")
        assert result["is_confirmation"] is True

    def test_confirmation_startswith(self):
        cfg = {"negation": {}, "confirmation_keywords": ["好的"]}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("好的就这样")
        assert result["is_confirmation"] is True

    def test_confirmation_not_matched_when_keyword_mid_string(self):
        # keyword appears but not as exact match nor prefix -> False
        cfg = {"negation": {}, "confirmation_keywords": ["确定"]}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("请你确定一下")
        assert result["is_confirmation"] is False

    def test_negation_intent_keyword_exact(self):
        cfg = {"negation": {}, "negation_keywords": ["取消"]}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("取消")
        assert result["is_negation_intent"] is True

    def test_negation_intent_keyword_startswith(self):
        cfg = {"negation": {}, "negation_keywords": ["算了"]}
        engine = _make_engine(cfg)
        result = engine.check_special_intent("算了吧")
        assert result["is_negation_intent"] is True

    def test_all_flags_present_in_result(self):
        engine = _make_engine({"negation": {}})
        result = engine.check_special_intent("中性消息")
        # plain message hits none of the special configs
        assert result == {
            "is_negation": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_confirmation": False,
            "is_negation_intent": False,
        }

    def test_empty_config_sections_default_to_false(self):
        # No negation/greeting/goodbye/help/confirmation/negation keys at all
        engine = _make_engine({})
        result = engine.check_special_intent("hi")
        assert all(v is False for v in result.values())
        assert set(result.keys()) == {
            "is_negation",
            "is_greeting",
            "is_goodbye",
            "is_help",
            "is_confirmation",
            "is_negation_intent",
        }


# ---------------------------------------------------------------------------
# Singleton helpers get_rule_engine / reload_rule_engine (lines 186-198)
# ---------------------------------------------------------------------------


class TestSingletonHelpers:
    def test_get_rule_engine_returns_singleton(self):
        with patch.object(re_mod, "get_intent_config", return_value={}):
            re_mod._rule_engine = None
            try:
                e1 = get_rule_engine()
                e2 = get_rule_engine()
                assert e1 is e2
                assert isinstance(e1, RuleEngine)
            finally:
                re_mod._rule_engine = None

    def test_reload_rule_engine_creates_new_instance(self):
        with patch.object(re_mod, "get_intent_config", return_value={}):
            re_mod._rule_engine = None
            try:
                first = get_rule_engine()
                replaced = reload_rule_engine()
                assert replaced is not first
                # subsequent get returns the replaced instance
                assert get_rule_engine() is replaced
            finally:
                re_mod._rule_engine = None
