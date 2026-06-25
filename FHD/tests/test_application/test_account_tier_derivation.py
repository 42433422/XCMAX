"""账号等级派生（维度 4）单元测试。"""

from __future__ import annotations

import pytest

from app.application.account_tier_derivation import (
    VALID_ACCOUNT_TIERS,
    derive_account_tier,
    normalize_account_tier,
    resolve_account_tier_for_user,
    should_have_account_tier,
)


class TestDeriveAccountTier:
    @pytest.mark.parametrize(
        "budget,expected",
        [
            ("1–5 万", "normal"),  # 中文长连字符 U+2013
            ("5–10 万", "pro"),
            ("10–50 万", "max"),
            ("50–100 万", "ultra"),
            ("5-10万", "pro"),  # 短横变体
            ("10-50万", "max"),
            ("5 万以内", "normal"),  # 旧档位兼容
            ("5–20 万", "pro"),
            ("20–50 万", "max"),
            ("50 万以上", "ultra"),
            ("", "normal"),
            (None, "normal"),
            ("暂未确定", "normal"),
            ("随便写的", "normal"),
        ],
    )
    def test_derive(self, budget, expected):
        assert derive_account_tier(budget) == expected

    def test_all_outputs_valid(self):
        for b in ("1–5 万", "5–10 万", "10–50 万", "50–100 万", None):
            assert derive_account_tier(b) in VALID_ACCOUNT_TIERS


class TestShouldHaveAccountTier:
    def test_enterprise_only(self):
        assert should_have_account_tier("enterprise") is True
        assert should_have_account_tier("personal") is False
        assert should_have_account_tier("admin") is False
        assert should_have_account_tier("") is False
        assert should_have_account_tier(None) is False


class TestNormalizeAccountTier:
    def test_valid_and_invalid(self):
        assert normalize_account_tier("pro") == "pro"
        assert normalize_account_tier("ULTRA") == "ultra"
        assert normalize_account_tier(" max ") == "max"
        assert normalize_account_tier("garbage") is None
        assert normalize_account_tier("") is None
        assert normalize_account_tier(None) is None


class TestResolveAccountTierForUser:
    def test_non_enterprise_is_none(self):
        assert resolve_account_tier_for_user("personal", "pro") is None
        assert resolve_account_tier_for_user("admin", "max") is None

    def test_enterprise_defaults_and_values(self):
        assert resolve_account_tier_for_user("enterprise", None) == "normal"
        assert resolve_account_tier_for_user("enterprise", "max") == "max"
        # 非法值回退 normal
        assert resolve_account_tier_for_user("enterprise", "garbage") == "normal"
