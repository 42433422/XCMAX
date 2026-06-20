"""测试 butler_identity_catalog — 原子身份枚举 + MBTI 映射 + 四轴派生。"""

from __future__ import annotations

import pytest

from app.application.butler_identity_catalog import (
    ATOMIC_IDENTITIES,
    DEFAULT_MBTI_EI,
    DEFAULT_MBTI_JP,
    DEFAULT_MBTI_SN,
    DEFAULT_MBTI_TF,
    MBTI_TO_IDENTITIES,
    clamp_mbti,
    derive_four_axes,
    derive_mbti_type,
    get_identity_affinities,
    pick_primary_identity,
)


class TestDeriveMbtiType:
    """测试 MBTI 4 维 → 16 型派生。"""

    def test_high_scores_produce_ENFP(self):
        """jp>=50 → P。"""
        assert derive_mbti_type(80, 70, 75, 65) == "ENFP"

    def test_j_type_requires_jp_below_50(self):
        """jp<50 → J。"""
        assert derive_mbti_type(80, 70, 75, 40) == "ENFJ"

    def test_low_scores_produce_ISTJ(self):
        """jp<50 → J。"""
        assert derive_mbti_type(30, 20, 25, 15) == "ISTJ"

    def test_p_type_requires_jp_at_least_50(self):
        """jp>=50 → P。"""
        assert derive_mbti_type(30, 20, 25, 60) == "ISTP"

    def test_boundary_50_produces_P(self):
        """50 分阈值：>=50 取 P。"""
        assert derive_mbti_type(50, 50, 50, 50) == "ENFP"

    def test_boundary_49_produces_J(self):
        assert derive_mbti_type(49, 49, 49, 49) == "ISTJ"

    def test_all_16_types_derivable(self):
        """确保 16 型都能派生。"""
        types = set()
        for ei in (30, 70):
            for sn in (30, 70):
                for tf in (30, 70):
                    for jp in (30, 70):
                        types.add(derive_mbti_type(ei, sn, tf, jp))
        assert len(types) == 16


class TestDeriveFourAxes:
    """测试 MBTI → 四轴派生。"""

    def test_returns_all_four_axes(self):
        axes = derive_four_axes(65, 60, 70, 60)
        assert set(axes.keys()) == {"warmth", "verbosity", "proactiveness", "structuredness"}

    def test_all_axes_in_0_100_range(self):
        for ei in (0, 50, 100):
            for sn in (0, 50, 100):
                for tf in (0, 50, 100):
                    for jp in (0, 50, 100):
                        axes = derive_four_axes(ei, sn, tf, jp)
                        for value in axes.values():
                            assert 0 <= value <= 100

    def test_high_tf_high_ei_produces_high_warmth(self):
        axes = derive_four_axes(ei=100, sn=50, tf=100, jp=50)
        assert axes["warmth"] == 100

    def test_low_tf_low_ei_produces_low_warmth(self):
        axes = derive_four_axes(ei=0, sn=50, tf=0, jp=50)
        assert axes["warmth"] == 0

    def test_high_ei_low_jp_produces_high_proactiveness(self):
        """主动度 = 0.7*ei + 0.3*(100-jp)，E 高 + J 高 → 主动度高。"""
        axes = derive_four_axes(ei=100, sn=50, tf=50, jp=0)
        assert axes["proactiveness"] == 100

    def test_low_jp_low_sn_produces_high_structuredness(self):
        """结构度 = 0.7*(100-jp) + 0.3*(100-sn)，J 高 + S 高 → 结构度高。"""
        axes = derive_four_axes(ei=50, sn=0, tf=50, jp=0)
        assert axes["structuredness"] == 100


class TestGetIdentityAffinities:
    """测试 MBTI 型 → 身份亲和度。"""

    def test_returns_all_atomic_identities(self):
        affinities = get_identity_affinities("ENFJ")
        assert set(affinities.keys()) == set(ATOMIC_IDENTITIES)

    def test_top_affinity_is_first_in_mbti_mapping(self):
        affinities = get_identity_affinities("ESTJ")
        top = max(affinities, key=affinities.get)
        assert top == "考勤管家"
        assert affinities["考勤管家"] == 0.9

    def test_unknown_mbti_falls_back_to_default(self):
        affinities = get_identity_affinities("XXXX")
        # 未知型应回退到默认身份列表
        assert "忠诚伙伴" in affinities
        assert affinities["忠诚伙伴"] == 0.9

    def test_all_affinities_between_0_and_1(self):
        for mbti_type in MBTI_TO_IDENTITIES:
            affinities = get_identity_affinities(mbti_type)
            for value in affinities.values():
                assert 0.0 <= value <= 1.0


class TestPickPrimaryIdentity:
    """测试主身份选择。"""

    def test_without_mod_hints_picks_highest_affinity(self):
        identity = pick_primary_identity("ESTJ")
        assert identity == "考勤管家"

    def test_with_mod_hints_overrides_affinity(self):
        """MOD 提示含「发货」时优先选发货管家。"""
        identity = pick_primary_identity("ESTJ", mod_hints=["发货"])
        assert identity == "发货管家"

    def test_mod_hint_partial_match(self):
        identity = pick_primary_identity("ENFJ", mod_hints=["考勤"])
        assert identity == "考勤管家"

    def test_empty_mod_hints_falls_back_to_affinity(self):
        identity = pick_primary_identity("ENFJ", mod_hints=[])
        assert identity == "忠诚伙伴"

    def test_none_mod_hints_falls_back_to_affinity(self):
        identity = pick_primary_identity("ENFJ", mod_hints=None)
        assert identity == "忠诚伙伴"


class TestClampMbti:
    """测试 MBTI 分数钳制。"""

    def test_normal_value_unchanged(self):
        assert clamp_mbti(50) == 50

    def test_negative_clamped_to_0(self):
        assert clamp_mbti(-10) == 0

    def test_over_100_clamped_to_100(self):
        assert clamp_mbti(150) == 100

    def test_zero_unchanged(self):
        assert clamp_mbti(0) == 0

    def test_100_unchanged(self):
        assert clamp_mbti(100) == 100


class TestDefaults:
    """测试默认值。"""

    def test_default_mbti_is_ENFJ(self):
        """新用户默认 ENFJ（管家型）。"""
        assert derive_mbti_type(DEFAULT_MBTI_EI, DEFAULT_MBTI_SN, DEFAULT_MBTI_TF, DEFAULT_MBTI_JP) == "ENFJ"

    def test_default_axes_are_balanced(self):
        """默认四轴应在中等偏上范围。"""
        axes = derive_four_axes(DEFAULT_MBTI_EI, DEFAULT_MBTI_SN, DEFAULT_MBTI_TF, DEFAULT_MBTI_JP)
        for value in axes.values():
            assert 40 <= value <= 90
