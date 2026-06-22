# FHD/tests/test_persona/test_persona_butler_bridge.py
"""Persona-A → Butler 视图桥接测试（方案 B：保持 butler 契约字节级不变）。"""

from __future__ import annotations

from app.application.persona_butler_bridge import (
    persona_axes_to_four_axes,
    persona_to_butler_view,
)
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, RapportScore


def _profile(**axes_kw) -> PersonaProfile:
    base = PersonaProfile.create("7", "零售业")
    return PersonaProfile(
        user_id=base.user_id,
        identity=base.identity,
        axes=PersonaAxes(
            **{"warmth": 0.5, "detail": 0.5, "proactivity": 0.5, "structure": 0.5, **axes_kw}
        ),
        rapport=RapportScore(score=0.62, interaction_count=37),
    )


class TestPersonaButlerBridge:
    def test_four_axes_key_names_and_scaling(self):
        axes = persona_axes_to_four_axes(
            _profile(warmth=0.8, detail=0.2, proactivity=0.65, structure=0.4)
        )
        # 键名严格对齐 butler 契约（detail→verbosity, proactivity→proactiveness, structure→structuredness）
        assert set(axes.keys()) == {"warmth", "verbosity", "proactiveness", "structuredness"}
        assert axes["warmth"] == 80
        assert axes["verbosity"] == 20
        assert axes["proactiveness"] == 65
        assert axes["structuredness"] == 40

    def test_view_shape_matches_butler_contract(self):
        view = persona_to_butler_view(_profile(), user_id=7)
        # 与 ButlerProfileView / to_public_dict 字段集一致（前端零改动）
        assert set(view.keys()) == {
            "user_id",
            "identity_primary",
            "identity_composite",
            "four_axes",
            "mbti_type",
            "mbti_confidence",
            "interaction_count",
            "last_inferred_at",
        }
        assert view["user_id"] == 7
        assert view["identity_primary"] == "门店管家"
        assert view["mbti_confidence"] == 0.62
        assert view["interaction_count"] == 37
        assert isinstance(view["mbti_type"], str) and len(view["mbti_type"]) == 4

    def test_display_mbti_type_consistent_with_axes(self):
        # 高 warmth/detail/proactivity/structure → F/N/E/J
        hi = persona_to_butler_view(
            _profile(warmth=0.9, detail=0.9, proactivity=0.9, structure=0.9), user_id=1
        )
        assert hi["mbti_type"] == "ENFJ"
        # 低 → I/S/T/P
        lo = persona_to_butler_view(
            _profile(warmth=0.1, detail=0.1, proactivity=0.1, structure=0.1), user_id=1
        )
        assert lo["mbti_type"] == "ISTP"

    def test_axes_clamped_to_0_100(self):
        axes = persona_axes_to_four_axes(_profile(warmth=1.0, structure=0.0))
        assert axes["warmth"] == 100
        assert axes["structuredness"] == 0
