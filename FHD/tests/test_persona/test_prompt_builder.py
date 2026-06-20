"""Prompt 生成器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)
from app.services.persona.identity_resolver import IdentityResolver
from app.services.persona.prompt_builder import PersonaPromptBuilder


class TestPersonaPromptBuilder:
    """Prompt 生成器测试。"""

    @pytest.fixture
    def builder(self):
        return PersonaPromptBuilder(IdentityResolver())

    def test_build_returns_string(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_build_contains_identity_name(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="")
        assert "门店管家" in prompt

    def test_build_contains_safety_section(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="")
        assert "不确定" in prompt or "诚实" in prompt

    def test_build_contains_context_when_provided(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="当前意图：查询订单")
        assert "查询订单" in prompt

    def test_build_high_warmth_adds_warm_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.8, detail=0.5, proactivity=0.5, structure=0.5))
        prompt = builder.build(profile, context_prompt="")
        assert "口语化" in prompt or "寒暄" in prompt

    def test_build_low_warmth_adds_concise_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.2, detail=0.5, proactivity=0.5, structure=0.5))
        prompt = builder.build(profile, context_prompt="")
        assert "就事论事" in prompt

    def test_build_high_structure_adds_list_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.8))
        prompt = builder.build(profile, context_prompt="")
        assert "编号" in prompt or "列表" in prompt

    def test_build_high_proactivity_adds_proactive_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.8, structure=0.5))
        prompt = builder.build(profile, context_prompt="")
        assert "主动" in prompt

    def test_build_length_under_600_chars(self, builder):
        """prompt 总长度控制（含上下文）。"""
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="当前意图：查询订单\n工具：order_query\n最近操作：查产品")
        # 允许一定冗余，但不应过长
        assert len(prompt) < 600

    def test_build_loyal_rapport_adds_loyal_brief(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_rapport(RapportScore(score=0.9, interaction_count=500))
        prompt = builder.build(profile, context_prompt="")
        assert "忠诚" in prompt or "老朋友" in prompt
