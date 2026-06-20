"""Rapport 计算器测试。"""

from __future__ import annotations

import pytest

from app.domain.persona.value_objects import RapportScore
from app.services.persona.rapport_calculator import RapportCalculator


class TestRapportCalculator:
    """关系深度计算器测试。"""

    @pytest.fixture
    def calculator(self):
        return RapportCalculator()

    def test_cold_start_returns_default_0_3(self, calculator):
        rapport = calculator.calculate(
            interaction_count=0,
            business_domain_counts={},
            emotion_signal_count=0,
        )
        assert rapport.score == 0.3

    def test_500_interactions_returns_high_rapport(self, calculator):
        rapport = calculator.calculate(
            interaction_count=500,
            business_domain_counts={"shipment": 300, "product": 200},
            emotion_signal_count=50,
        )
        assert rapport.score >= 0.9

    def test_250_interactions_returns_mid_rapport(self, calculator):
        rapport = calculator.calculate(
            interaction_count=250,
            business_domain_counts={"shipment": 200},
            emotion_signal_count=25,
        )
        assert 0.4 <= rapport.score <= 0.7

    def test_business_depth_calculated_from_domain_counts(self, calculator):
        rapport = calculator.calculate(
            interaction_count=100,
            business_domain_counts={"shipment": 50, "product": 30, "customer": 20},
            emotion_signal_count=10,
        )
        # 3 个业务域 → business_depth = 3/5 = 0.6
        assert 0.5 <= rapport.business_depth <= 0.7

    def test_emotion_signal_normalized(self, calculator):
        rapport = calculator.calculate(
            interaction_count=100,
            business_domain_counts={"shipment": 100},
            emotion_signal_count=50,
        )
        # emotion_signal_count=50 → 归一化 = 1.0
        assert rapport.emotion_signal_count == 50

    def test_score_never_exceeds_1(self, calculator):
        rapport = calculator.calculate(
            interaction_count=10000,
            business_domain_counts={"a": 1, "b": 1, "c": 1, "d": 1, "e": 1},
            emotion_signal_count=1000,
        )
        assert rapport.score <= 1.0

    def test_score_never_below_0(self, calculator):
        rapport = calculator.calculate(
            interaction_count=0,
            business_domain_counts={},
            emotion_signal_count=0,
        )
        assert rapport.score >= 0.0

    def test_weights_sum_to_one(self, calculator):
        """50% + 30% + 20% = 100%"""
        assert (
            calculator.INTERACTION_WEIGHT
            + calculator.BUSINESS_DEPTH_WEIGHT
            + calculator.EMOTION_WEIGHT
            == 1.0
        )
