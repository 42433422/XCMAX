"""Persona 值对象测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)


class TestPersonaAxes:
    """四轴风格参数值对象测试。"""

    def test_create_with_defaults_returns_mid_values(self):
        axes = PersonaAxes()
        assert axes.warmth == 0.5
        assert axes.detail == 0.5
        assert axes.proactivity == 0.5
        assert axes.structure == 0.5

    def test_create_with_valid_values_returns_axes(self):
        axes = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        assert axes.warmth == 0.8
        assert axes.detail == 0.3
        assert axes.proactivity == 0.6
        assert axes.structure == 0.9

    def test_create_with_value_below_zero_raises(self):
        with pytest.raises(ValueError, match="warmth"):
            PersonaAxes(warmth=-0.1)

    def test_create_with_value_above_one_raises(self):
        with pytest.raises(ValueError, match="detail"):
            PersonaAxes(detail=1.1)

    def test_create_with_none_raises(self):
        with pytest.raises((TypeError, ValueError)):
            PersonaAxes(warmth=None)  # type: ignore[arg-type]

    def test_to_dict_returns_all_axes(self):
        axes = PersonaAxes(warmth=0.7, detail=0.4, proactivity=0.6, structure=0.8)
        d = axes.to_dict()
        assert d == {"warmth": 0.7, "detail": 0.4, "proactivity": 0.6, "structure": 0.8}

    def test_from_dict_returns_axes(self):
        d = {"warmth": 0.7, "detail": 0.4, "proactivity": 0.6, "structure": 0.8}
        axes = PersonaAxes.from_dict(d)
        assert axes.warmth == 0.7
        assert axes.structure == 0.8

    def test_clamp_returns_bounded_copy(self):
        axes = PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5)
        clamped = axes.clamp(warmth_offset=0.6)
        assert clamped.warmth == 1.0  # 0.5 + 0.6 = 1.1 → clamp to 1.0


class TestPersonaIdentity:
    """身份值对象测试。"""

    def test_create_returns_identity(self):
        identity = PersonaIdentity(
            name="考勤管家",
            brief="专业地服务用户，熟悉考勤业务",
            business_domain="attendance",
            industry="服务业",
        )
        assert identity.name == "考勤管家"
        assert identity.business_domain == "attendance"

    def test_create_with_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            PersonaIdentity(name="", brief="x", business_domain="y", industry="z")

    def test_to_dict_returns_all_fields(self):
        identity = PersonaIdentity(
            name="考勤管家",
            brief="专业地服务用户",
            business_domain="attendance",
            industry="服务业",
        )
        d = identity.to_dict()
        assert d["name"] == "考勤管家"
        assert d["business_domain"] == "attendance"


class TestRapportScore:
    """关系深度值对象测试。"""

    def test_create_with_defaults_returns_cold_start(self):
        rapport = RapportScore()
        assert rapport.score == 0.3  # 冷启动友好默认
        assert rapport.interaction_count == 0
        assert rapport.business_depth == 0.0
        assert rapport.emotion_signal_count == 0

    def test_create_with_valid_values_returns_rapport(self):
        rapport = RapportScore(
            score=0.7,
            interaction_count=250,
            business_depth=0.6,
            emotion_signal_count=30,
        )
        assert rapport.score == 0.7
        assert rapport.interaction_count == 250

    def test_create_with_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="score"):
            RapportScore(score=-0.1)

    def test_create_with_score_above_one_raises(self):
        with pytest.raises(ValueError, match="score"):
            RapportScore(score=1.5)

    def test_is_loyal_returns_true_when_score_high(self):
        assert RapportScore(score=0.8).is_loyal() is True

    def test_is_loyal_returns_false_when_score_low(self):
        assert RapportScore(score=0.3).is_loyal() is False

    def test_is_stranger_returns_true_when_score_low(self):
        assert RapportScore(score=0.2).is_stranger() is True

    def test_to_dict_returns_all_fields(self):
        rapport = RapportScore(score=0.5, interaction_count=100, business_depth=0.4, emotion_signal_count=10)
        d = rapport.to_dict()
        assert d["score"] == 0.5
        assert d["interaction_count"] == 100
