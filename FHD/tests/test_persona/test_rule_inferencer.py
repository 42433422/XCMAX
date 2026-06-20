"""L1 规则推断器测试。"""
from __future__ import annotations

import pytest

from app.services.persona.rule_inferencer import RuleInferencer, RuleInferResult


class TestRuleInferencer:
    """L1 规则推断器测试。"""

    @pytest.fixture
    def inferencer(self):
        return RuleInferencer()

    def test_short_message_returns_low_detail(self, inferencer):
        result = inferencer.infer("查下", [])
        assert result.axes.detail < 0.4

    def test_long_message_returns_high_detail(self, inferencer):
        result = inferencer.infer("详细说说这个订单的物流信息，包括每个节点的时间和地点", [])
        assert result.axes.detail > 0.6

    def test_message_with_emoji_returns_high_warmth(self, inferencer):
        result = inferencer.infer("你好呀😊 帮我查下订单", [])
        assert result.axes.warmth > 0.6

    def test_message_with_modal_particles_returns_high_warmth(self, inferencer):
        result = inferencer.infer("帮我查下订单呢", [])
        assert result.axes.warmth > 0.5

    def test_imperative_sentence_returns_low_warmth(self, inferencer):
        result = inferencer.infer("查下订单", [])
        assert result.axes.warmth < 0.5

    def test_explicit_brief_request_returns_low_detail(self, inferencer):
        result = inferencer.infer("简单点说，长话短说", [])
        assert result.axes.detail < 0.4

    def test_explicit_detailed_request_returns_high_detail(self, inferencer):
        result = inferencer.infer("展开讲讲，详细说说", [])
        assert result.axes.detail > 0.6

    def test_returns_confidence(self, inferencer):
        result = inferencer.infer("你好呀😊", [])
        assert 0.0 <= result.confidence <= 1.0

    def test_empty_message_returns_neutral(self, inferencer):
        result = inferencer.infer("", [])
        assert result.axes.warmth == 0.5
        assert result.axes.detail == 0.5

    def test_none_message_returns_neutral(self, inferencer):
        result = inferencer.infer(None, [])  # type: ignore[arg-type]
        assert result.axes.warmth == 0.5
