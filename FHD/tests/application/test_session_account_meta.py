"""app/application/session_account_meta 纯函数单测。"""

from __future__ import annotations

from types import SimpleNamespace

from app.application.session_account_meta import (
    company_brand_from_user_blob,
    extract_market_user_blob,
    normalize_account_kind,
    session_row_to_meta_dict,
    validate_account_kind_for_market,
)


class TestNormalizeAccountKind:
    def test_valid_values(self):
        assert normalize_account_kind("personal") == "personal"
        assert normalize_account_kind("ADMIN") == "admin"

    def test_invalid_defaults_enterprise(self):
        assert normalize_account_kind("bogus") == "enterprise"
        assert normalize_account_kind(None) == "enterprise"


class TestExtractMarketUserBlob:
    def test_empty(self):
        assert extract_market_user_blob(None) == {}
        assert extract_market_user_blob({}) == {}

    def test_nested_user(self):
        blob = extract_market_user_blob({"raw": {"user": {"id": 1}}})
        assert blob == {"id": 1}

    def test_data_user(self):
        blob = extract_market_user_blob({"raw": {"data": {"user": {"name": "a"}}}})
        assert blob == {"name": "a"}

    def test_data_as_blob(self):
        blob = extract_market_user_blob({"raw": {"data": {"company": "X"}}})
        assert blob == {"company": "X"}


class TestCompanyBrand:
    def test_prefers_company(self):
        assert company_brand_from_user_blob({"company": "甲公司", "username": "u"}) == "甲公司"

    def test_display_name_fallback(self):
        assert company_brand_from_user_blob({"display_name": "展示名"}) == "展示名"

    def test_username_fallback(self):
        assert company_brand_from_user_blob({"username": "user1"}) == "user1"


class TestValidateAccountKind:
    def test_admin_requires_market_admin(self):
        assert validate_account_kind_for_market("admin", is_enterprise=True, is_market_admin=False)
        assert (
            validate_account_kind_for_market("admin", is_enterprise=True, is_market_admin=True)
            is None
        )

    def test_enterprise_rejects_admin_login(self):
        msg = validate_account_kind_for_market(
            "enterprise", is_enterprise=True, is_market_admin=True
        )
        assert msg and "管理员" in msg

    def test_enterprise_requires_enterprise_flag(self):
        msg = validate_account_kind_for_market(
            "enterprise", is_enterprise=False, is_market_admin=False
        )
        assert msg and "企业" in msg

    def test_personal_same_enterprise_gate(self):
        msg = validate_account_kind_for_market("personal", is_enterprise=False, is_market_admin=False)
        assert msg


class TestSessionRowToMeta:
    def test_defaults(self):
        row = SimpleNamespace(
            account_kind=None,
            company_brand="",
            market_user_id=9,
            market_is_admin=False,
            market_is_enterprise=True,
            impersonating_market_user_id=None,
            impersonating_username="",
            tenant_id=3,
        )
        meta = session_row_to_meta_dict(row)
        assert meta["account_kind"] == "enterprise"
        assert meta["market_user_id"] == 9
        assert meta["tenant_id"] == 3
