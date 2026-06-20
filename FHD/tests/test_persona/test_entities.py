"""PersonaProfile 聚合根测试。"""

from __future__ import annotations

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)


class TestPersonaProfile:
    """PersonaProfile 聚合根测试。"""

    def test_create_with_defaults_returns_cold_start_profile(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        assert profile.user_id == "user-1"
        assert profile.identity.industry == "零售业"
        assert profile.identity.name == "门店管家"  # 行业映射默认身份
        assert profile.rapport.score == 0.3  # 冷启动
        assert profile.axes.warmth == 0.5  # 默认中值

    def test_create_with_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            PersonaProfile(user_id="", industry="零售业")

    def test_create_with_unknown_industry_uses_general(self):
        profile = PersonaProfile(user_id="user-1", industry="未知行业")
        assert profile.identity.name == "业务管家"
        assert profile.identity.business_domain == "general"

    def test_update_axes_returns_new_profile_with_updated_axes(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        new_axes = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        updated = profile.update_axes(new_axes)
        assert updated.axes.warmth == 0.8
        assert updated.rapport.score == profile.rapport.score  # rapport 不变

    def test_update_rapport_returns_new_profile_with_updated_rapport(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        new_rapport = RapportScore(score=0.7, interaction_count=250)
        updated = profile.update_rapport(new_rapport)
        assert updated.rapport.score == 0.7
        assert updated.axes.warmth == profile.axes.warmth  # axes 不变

    def test_drift_identity_returns_new_profile_with_new_identity(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        new_identity = PersonaIdentity(
            name="考勤管家",
            brief="熟悉考勤业务",
            business_domain="attendance",
            industry="零售业",
        )
        updated = profile.drift_identity(new_identity)
        assert updated.identity.name == "考勤管家"
        assert updated.identity.business_domain == "attendance"

    def test_to_dict_returns_all_fields(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        d = profile.to_dict()
        assert d["user_id"] == "user-1"
        assert "identity" in d
        assert "axes" in d
        assert "rapport" in d

    def test_from_dict_returns_profile(self):
        d = {
            "user_id": "user-1",
            "identity": {
                "name": "考勤管家",
                "brief": "熟悉考勤",
                "business_domain": "attendance",
                "industry": "服务业",
            },
            "axes": {"warmth": 0.7, "detail": 0.4, "proactivity": 0.6, "structure": 0.8},
            "rapport": {
                "score": 0.5,
                "interaction_count": 100,
                "business_depth": 0.4,
                "emotion_signal_count": 10,
            },
        }
        profile = PersonaProfile.from_dict(d)
        assert profile.user_id == "user-1"
        assert profile.identity.name == "考勤管家"
        assert profile.axes.warmth == 0.7
        assert profile.rapport.score == 0.5
