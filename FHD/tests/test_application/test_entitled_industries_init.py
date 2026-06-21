"""已授权行业初始化与校验（维度 2）单元测试。"""

from __future__ import annotations

from app.application.entitled_industries_init import (
    init_entitled_industries_for_user,
    merge_entitled_industries,
    validate_industry_in_entitled,
)


class TestInit:
    def test_personal(self):
        assert init_entitled_industries_for_user("personal", "涂料") == ["通用"]

    def test_enterprise(self):
        assert init_entitled_industries_for_user("enterprise", "涂料") == ["通用", "涂料"]

    def test_enterprise_dedup_general(self):
        assert init_entitled_industries_for_user("enterprise", "通用") == ["通用"]

    def test_enterprise_empty_industry(self):
        assert init_entitled_industries_for_user("enterprise", "") == ["通用"]

    def test_admin(self):
        assert init_entitled_industries_for_user("admin", "x") == ["管理端"]

    def test_unknown_tier_defaults_general(self):
        assert init_entitled_industries_for_user("", "涂料") == ["通用"]


class TestMerge:
    def test_dedup_preserve_order(self):
        assert merge_entitled_industries(["通用"], ["涂料", "通用", "电商"]) == [
            "通用",
            "涂料",
            "电商",
        ]

    def test_strips_and_drops_empty(self):
        assert merge_entitled_industries([" 通用 ", ""], ["", "涂料"]) == ["通用", "涂料"]

    def test_none_inputs(self):
        assert merge_entitled_industries(None, None) == []


class TestValidate:
    def test_in_set(self):
        assert validate_industry_in_entitled("涂料", ["通用", "涂料"]) is True

    def test_not_in_set(self):
        assert validate_industry_in_entitled("考勤", ["通用", "涂料"]) is False

    def test_empty_industry_is_valid(self):
        # 空 industry_id 表示沿用默认，不校验
        assert validate_industry_in_entitled("", ["通用"]) is True
        assert validate_industry_in_entitled(None, []) is True

    def test_empty_entitled_rejects_nonempty(self):
        assert validate_industry_in_entitled("涂料", []) is False
        assert validate_industry_in_entitled("涂料", None) is False
