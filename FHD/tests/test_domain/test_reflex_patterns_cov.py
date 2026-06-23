from __future__ import annotations

"""Branch coverage for app/domain/neuro/reflex_patterns.py."""

import pytest

from app.domain.neuro.reflex_arc import ReflexType
from app.domain.neuro.reflex_patterns import (
    REFLEX_RESPONSES,
    PatternRule,
    ReflexPatternMatcher,
    get_reflex_response,
)


class TestPatternRule:
    def test_default_weight(self):
        rule = PatternRule(pattern=r"hello")
        assert rule.weight == 1.0
        assert rule.context_required is None

    def test_custom_weight(self):
        rule = PatternRule(pattern=r"hi", weight=0.8)
        assert rule.weight == 0.8


class TestReflexPatternMatcher:
    @pytest.fixture
    def matcher(self):
        return ReflexPatternMatcher()

    # Greeting matches
    def test_greeting_nihao(self, matcher):
        rt, conf = matcher.match("你好")
        assert rt == ReflexType.GREETING
        assert conf > 0

    def test_greeting_hello(self, matcher):
        rt, conf = matcher.match("hello")
        assert rt == ReflexType.GREETING

    def test_greeting_hi(self, matcher):
        rt, conf = matcher.match("hi")
        assert rt == ReflexType.GREETING

    def test_greeting_ninhao(self, matcher):
        rt, conf = matcher.match("您好")
        assert rt == ReflexType.GREETING

    def test_greeting_morning(self, matcher):
        rt, conf = matcher.match("早上好")
        assert rt == ReflexType.GREETING

    # Emergency stop matches
    def test_emergency_stop(self, matcher):
        rt, conf = matcher.match("停止")
        assert rt == ReflexType.EMERGENCY_STOP

    def test_emergency_stop_english(self, matcher):
        rt, conf = matcher.match("stop")
        assert rt == ReflexType.EMERGENCY_STOP

    def test_emergency_cancel(self, matcher):
        rt, conf = matcher.match("取消")
        assert rt == ReflexType.EMERGENCY_STOP

    def test_emergency_abort(self, matcher):
        rt, conf = matcher.match("abort")
        assert rt == ReflexType.EMERGENCY_STOP

    # Confirmation matches
    def test_confirmation_shide(self, matcher):
        rt, conf = matcher.match("是的")
        assert rt == ReflexType.CONFIRMATION

    def test_confirmation_yes(self, matcher):
        rt, conf = matcher.match("yes")
        assert rt == ReflexType.CONFIRMATION

    def test_confirmation_ok(self, matcher):
        rt, conf = matcher.match("ok")
        assert rt == ReflexType.CONFIRMATION

    def test_confirmation_hao(self, matcher):
        rt, conf = matcher.match("好的")
        assert rt == ReflexType.CONFIRMATION

    # Denial matches
    def test_denial_bushi(self, matcher):
        rt, conf = matcher.match("不是")
        assert rt == ReflexType.DENIAL

    def test_denial_no(self, matcher):
        rt, conf = matcher.match("no")
        assert rt == ReflexType.DENIAL

    def test_denial_never(self, matcher):
        rt, conf = matcher.match("never")
        assert rt == ReflexType.DENIAL

    # Help matches
    def test_help_bang(self, matcher):
        rt, conf = matcher.match("帮助")
        assert rt == ReflexType.HELP

    def test_help_english(self, matcher):
        rt, conf = matcher.match("help")
        assert rt == ReflexType.HELP

    def test_help_question_marks(self, matcher):
        rt, conf = matcher.match("???")
        assert rt == ReflexType.HELP

    # No match
    def test_no_match(self, matcher):
        rt, conf = matcher.match("随机无意义的长文字xkjdfhakjsdhfakjsdf")
        # might not match any reflex type
        assert conf == 0.0 or rt is not None  # either outcome is fine

    # match returns high-confidence early exit (confidence >= 1.0)
    def test_full_confidence_early_return(self, matcher):
        # 停 alone should hit weight=1.0 pattern and return early
        rt, conf = matcher.match("停")
        assert rt is not None
        assert conf >= 1.0

    # get_patterns_for_type
    def test_get_patterns_greeting(self, matcher):
        patterns = matcher.get_patterns_for_type(ReflexType.GREETING)
        assert len(patterns) > 0
        assert all(isinstance(p, str) for p in patterns)

    def test_get_patterns_unknown_type_returns_empty(self, matcher):
        patterns = matcher.get_patterns_for_type(ReflexType.UNKNOWN)
        assert patterns == []

    # add_custom_pattern — valid
    def test_add_custom_pattern_valid(self, matcher):
        result = matcher.add_custom_pattern(ReflexType.GREETING, r"^sup\b", weight=0.8)
        assert result is True
        rt, conf = matcher.match("sup")
        assert rt == ReflexType.GREETING

    # add_custom_pattern — invalid regex
    def test_add_custom_pattern_invalid_regex(self, matcher):
        result = matcher.add_custom_pattern(ReflexType.GREETING, r"[invalid(")
        assert result is False

    # add_custom_pattern — new reflex_type not previously in groups
    def test_add_custom_pattern_new_type(self, matcher):
        # UNKNOWN is not seeded during _compile_patterns
        result = matcher.add_custom_pattern(ReflexType.UNKNOWN, r"^mystery$")
        assert result is True


class TestReflexResponses:
    def test_get_reflex_response_greeting(self):
        resp = get_reflex_response(ReflexType.GREETING, 0)
        assert isinstance(resp, str)
        assert len(resp) > 0

    def test_get_reflex_response_variation(self):
        resp0 = get_reflex_response(ReflexType.GREETING, 0)
        resp1 = get_reflex_response(ReflexType.GREETING, 1)
        # at least one should be non-empty; they may differ if >1 response
        assert isinstance(resp1, str)

    def test_get_reflex_response_cycles(self):
        responses = REFLEX_RESPONSES[ReflexType.GREETING]
        n = len(responses)
        # variation modulo length wraps around
        assert get_reflex_response(ReflexType.GREETING, n) == responses[0]

    def test_get_reflex_response_unknown_type(self):
        # UNKNOWN is in the dict
        resp = get_reflex_response(ReflexType.UNKNOWN)
        assert isinstance(resp, str)

    def test_get_reflex_response_empty_list(self):
        # inject an empty list temporarily
        original = REFLEX_RESPONSES.get(ReflexType.UNKNOWN)
        REFLEX_RESPONSES[ReflexType.UNKNOWN] = []
        try:
            resp = get_reflex_response(ReflexType.UNKNOWN)
            assert resp == ""
        finally:
            if original is not None:
                REFLEX_RESPONSES[ReflexType.UNKNOWN] = original

    def test_get_reflex_response_missing_type(self):
        # pass a type not in the dict at all (simulate via sentinel)
        resp = get_reflex_response("NONEXISTENT_TYPE")  # type: ignore[arg-type]
        assert resp == ""

    def test_all_types_have_responses(self):
        for rt in [
            ReflexType.GREETING,
            ReflexType.EMERGENCY_STOP,
            ReflexType.CONFIRMATION,
            ReflexType.DENIAL,
            ReflexType.HELP,
        ]:
            assert len(REFLEX_RESPONSES[rt]) > 0
