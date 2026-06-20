"""身份解析器测试。"""

from __future__ import annotations

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaIdentity, RapportScore
from app.services.persona.identity_resolver import IdentityResolver


class TestIdentityResolver:
    """身份解析器测试。"""

    @pytest.fixture
    def resolver(self):
        return IdentityResolver()

    def test_resolve_brief_stranger_returns_professional_brief(self, resolver):
        identity = PersonaIdentity(
            name="考勤管家", brief="", business_domain="attendance", industry="服务业"
        )
        brief = resolver.resolve_brief(identity, RapportScore(score=0.2))
        assert "attendance" in brief

    def test_resolve_brief_familiar_returns_familiar_brief(self, resolver):
        identity = PersonaIdentity(
            name="考勤管家", brief="", business_domain="attendance", industry="服务业"
        )
        brief = resolver.resolve_brief(identity, RapportScore(score=0.5))
        assert "熟悉" in brief

    def test_resolve_brief_loyal_returns_loyal_brief(self, resolver):
        identity = PersonaIdentity(
            name="考勤管家", brief="", business_domain="attendance", industry="服务业"
        )
        brief = resolver.resolve_brief(identity, RapportScore(score=0.9))
        assert "忠诚" in brief or "老朋友" in brief

    def test_should_drift_returns_false_when_below_threshold(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        # 只有 10 轮考勤操作，未达 50 轮阈值
        profile = profile.increment_domain("attendance")
        for _ in range(10):
            profile = profile.increment_domain("attendance")
        assert resolver.should_drift(profile) is False

    def test_should_drift_returns_true_when_above_threshold(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        # 60 轮考勤操作，超过 50 轮阈值
        for _ in range(60):
            profile = profile.increment_domain("attendance")
        assert resolver.should_drift(profile) is True

    def test_drift_target_returns_new_domain_identity(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        for _ in range(60):
            profile = profile.increment_domain("attendance")
        target = resolver.drift_target(profile)
        assert target.business_domain == "attendance"
        assert "考勤" in target.name

    def test_drift_target_returns_none_when_no_drift_needed(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.increment_domain("retail")
        assert resolver.drift_target(profile) is None
