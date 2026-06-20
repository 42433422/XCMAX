"""三层融合器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.axes_fuser import AxesFuser


class TestAxesFuser:
    """三层融合器测试。"""

    @pytest.fixture
    def fuser(self):
        return AxesFuser()

    def test_fuse_only_l1_returns_l1_values(self, fuser):
        l1 = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        result = fuser.fuse(l1=l1, l2=None, l3=None, rapport=RapportScore(score=0.3))
        assert result.warmth == 0.8
        assert result.detail == 0.3

    def test_fuse_l1_and_l2_uses_equal_weights(self, fuser):
        l1 = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        l2 = PersonaAxes(warmth=0.4, detail=0.7, proactivity=0.2, structure=0.5)
        result = fuser.fuse(l1=l1, l2=l2, l3=None, rapport=RapportScore(score=0.3))
        # L1(0.5) + L2(0.5)
        assert abs(result.warmth - 0.6) < 0.01  # (0.8+0.4)/2
        assert abs(result.detail - 0.5) < 0.01  # (0.3+0.7)/2

    def test_fuse_all_three_uses_configured_weights(self, fuser):
        l1 = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        l2 = PersonaAxes(warmth=0.4, detail=0.7, proactivity=0.2, structure=0.5)
        l3 = PersonaAxes(warmth=0.6, detail=0.5, proactivity=0.4, structure=0.7)
        result = fuser.fuse(l1=l1, l2=l2, l3=l3, rapport=RapportScore(score=0.3))
        # L1(0.4) + L2(0.3) + L3(0.3)
        expected_warmth = 0.4 * 0.8 + 0.3 * 0.4 + 0.3 * 0.6
        assert abs(result.warmth - expected_warmth) < 0.01

    def test_soft_offset_applied_when_rapport_high(self, fuser):
        l1 = PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5)
        result = fuser.fuse(
            l1=l1, l2=None, l3=None, rapport=RapportScore(score=1.0)
        )
        # rapport=1.0 → warmth +0.2, proactivity +0.2, detail +0.1
        assert result.warmth == pytest.approx(0.7, abs=0.01)
        assert result.proactivity == pytest.approx(0.7, abs=0.01)
        assert result.detail == pytest.approx(0.6, abs=0.01)

    def test_soft_offset_not_applied_when_signal_strong(self, fuser):
        """用户信号强烈时（confidence > 0.7），rapport 偏移不生效。"""
        l1 = PersonaAxes(warmth=0.2, detail=0.5, proactivity=0.5, structure=0.5)
        result = fuser.fuse(
            l1=l1,
            l2=None,
            l3=None,
            rapport=RapportScore(score=1.0),
            signal_strength=0.8,  # 强信号
        )
        # warmth 锁定低位，不偏移
        assert result.warmth == pytest.approx(0.2, abs=0.01)

    def test_soft_offset_mid_rapport(self, fuser):
        l1 = PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5)
        result = fuser.fuse(
            l1=l1, l2=None, l3=None, rapport=RapportScore(score=0.5)
        )
        # rapport=0.5 → warmth +0.1, proactivity +0.1
        assert result.warmth == pytest.approx(0.6, abs=0.01)
        assert result.proactivity == pytest.approx(0.6, abs=0.01)
