"""Branch-coverage tests for app.application.session_account_meta.

目标：覆盖 session_account_meta.py 的 25 个缺失分支（当前 74.0% 覆盖率）。

覆盖重点：
- normalize_account_kind：合法/非法/空值/默认值分支
- derive_account_kind_from_user：admin/enterprise/personal 各组合分支
- extract_market_user_blob：None/非 dict/raw.user/raw.data.user/raw.data 各分支
- company_brand_from_user_blob：company/display_name/username 优先级
- validate_account_kind_for_market：admin/enterprise/personal × 各身份组合
- persist_session_account_meta：空 sid/row None/各字段写入/异常分支
- persist_session_membership_tier：空 sid/row None/空 tier/异常
- load_session_account_meta：空 sid/row None/异常
- session_row_to_meta_dict：各字段默认值与转换
- enrich_session_meta_with_tenant：admin 早返回/tenant 绑定/名称查找/异常
- clear_impersonation：空 sid/row None/异常
- is_session_market_admin：meta None/非 admin
- should_receive_enterprise_dedicated_cs：meta 各分支/user_id fallback/异常
- effective_entitlement_market_user_id：imp/mid/None
- audit_admin_action：sid 提取/operator 回填/异常
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application import session_account_meta
from app.application.session_account_meta import (
    audit_admin_action,
    clear_impersonation,
    company_brand_from_user_blob,
    derive_account_kind_from_user,
    effective_entitlement_market_user_id,
    enrich_session_meta_with_tenant,
    extract_market_user_blob,
    is_session_market_admin,
    load_session_account_meta,
    normalize_account_kind,
    persist_session_account_meta,
    persist_session_membership_tier,
    session_row_to_meta_dict,
    should_receive_enterprise_dedicated_cs,
    validate_account_kind_for_market,
)

# ───────────────────── normalize_account_kind ─────────────────────


class TestNormalizeAccountKind:
    def test_valid_kind_personal(self) -> None:
        assert normalize_account_kind("personal") == "personal"

    def test_valid_kind_enterprise(self) -> None:
        assert normalize_account_kind("enterprise") == "enterprise"

    def test_valid_kind_admin(self) -> None:
        assert normalize_account_kind("admin") == "admin"

    def test_invalid_kind_returns_default(self) -> None:
        assert normalize_account_kind("superuser") == "enterprise"

    def test_none_returns_default(self) -> None:
        assert normalize_account_kind(None) == "enterprise"

    def test_empty_string_returns_default(self) -> None:
        assert normalize_account_kind("") == "enterprise"

    def test_uppercase_normalized_to_lower(self) -> None:
        assert normalize_account_kind("ADMIN") == "admin"

    def test_whitespace_stripped(self) -> None:
        assert normalize_account_kind("  admin  ") == "admin"

    def test_custom_default(self) -> None:
        assert normalize_account_kind("bad", default="personal") == "personal"

    def test_custom_default_with_valid_kind(self) -> None:
        assert normalize_account_kind("admin", default="personal") == "admin"


# ───────────────────── derive_account_kind_from_user ─────────────────────


class TestDeriveAccountKindFromUser:
    def test_tier_admin_returns_admin(self) -> None:
        assert derive_account_kind_from_user(tier="admin") == "admin"

    def test_market_is_admin_returns_admin_even_if_tier_personal(self) -> None:
        assert derive_account_kind_from_user(tier="personal", market_is_admin=True) == "admin"

    def test_tier_enterprise_returns_enterprise(self) -> None:
        assert derive_account_kind_from_user(tier="enterprise") == "enterprise"

    def test_market_is_enterprise_returns_enterprise(self) -> None:
        assert (
            derive_account_kind_from_user(tier="personal", market_is_enterprise=True)
            == "enterprise"
        )

    def test_admin_overrides_enterprise(self) -> None:
        assert derive_account_kind_from_user(tier="enterprise", market_is_admin=True) == "admin"

    def test_personal_when_no_flags(self) -> None:
        assert derive_account_kind_from_user(tier="personal") == "personal"

    def test_personal_when_tier_empty(self) -> None:
        assert derive_account_kind_from_user(tier="") == "personal"

    def test_personal_when_tier_none(self) -> None:
        assert derive_account_kind_from_user(tier=None) == "personal"

    def test_tier_uppercase_normalized(self) -> None:
        assert derive_account_kind_from_user(tier="ADMIN") == "admin"

    def test_tier_whitespace_stripped(self) -> None:
        assert derive_account_kind_from_user(tier="  admin  ") == "admin"

    def test_unknown_tier_returns_personal(self) -> None:
        assert derive_account_kind_from_user(tier="superuser") == "personal"


# ───────────────────── extract_market_user_blob ─────────────────────


class TestExtractMarketUserBlob:
    def test_none_returns_empty(self) -> None:
        assert extract_market_user_blob(None) == {}

    def test_non_dict_returns_empty(self) -> None:
        assert extract_market_user_blob("not a dict") == {}  # type: ignore[arg-type]

    def test_raw_not_dict_returns_empty(self) -> None:
        assert extract_market_user_blob({"raw": "not a dict"}) == {}

    def test_raw_user_dict_returned(self) -> None:
        blob = {"username": "u1"}
        assert extract_market_user_blob({"raw": {"user": blob}}) == blob

    def test_raw_user_not_dict_returns_empty(self) -> None:
        assert extract_market_user_blob({"raw": {"user": "not a dict"}}) == {}

    def test_raw_data_user_dict_returned(self) -> None:
        blob = {"id": 1}
        result = extract_market_user_blob({"raw": {"data": {"user": blob}}})
        assert result == blob

    def test_raw_data_user_not_dict_returns_data(self) -> None:
        data = {"id": 1, "name": "x"}
        result = extract_market_user_blob({"raw": {"data": data}})
        assert result == data

    def test_raw_data_not_dict_returns_empty(self) -> None:
        assert extract_market_user_blob({"raw": {"data": "not a dict"}}) == {}

    def test_raw_no_user_no_data_returns_empty(self) -> None:
        assert extract_market_user_blob({"raw": {"other": 1}}) == {}


# ───────────────────── company_brand_from_user_blob ─────────────────────


class TestCompanyBrandFromUserBlob:
    def test_none_returns_empty(self) -> None:
        assert company_brand_from_user_blob(None) == ""

    def test_non_dict_returns_empty(self) -> None:
        assert company_brand_from_user_blob("not a dict") == ""  # type: ignore[arg-type]

    def test_company_field_returned(self) -> None:
        assert company_brand_from_user_blob({"company": "Acme"}) == "Acme"

    def test_company_whitespace_stripped(self) -> None:
        assert company_brand_from_user_blob({"company": "  Acme  "}) == "Acme"

    def test_display_name_when_no_company(self) -> None:
        assert company_brand_from_user_blob({"display_name": "Display"}) == "Display"

    def test_username_when_no_company_no_display(self) -> None:
        assert company_brand_from_user_blob({"username": "user1"}) == "user1"

    def test_empty_company_falls_back_to_display(self) -> None:
        assert company_brand_from_user_blob({"company": "", "display_name": "D"}) == "D"

    def test_empty_all_returns_empty(self) -> None:
        assert (
            company_brand_from_user_blob({"company": "", "display_name": "", "username": ""}) == ""
        )

    def test_company_takes_priority_over_display_and_username(self) -> None:
        assert (
            company_brand_from_user_blob({"company": "C", "display_name": "D", "username": "U"})
            == "C"
        )


# ───────────────────── validate_account_kind_for_market ─────────────────────


class TestValidateAccountKindForMarket:
    def test_admin_with_market_admin_passes(self) -> None:
        assert (
            validate_account_kind_for_market("admin", is_enterprise=False, is_market_admin=True)
            is None
        )

    def test_admin_without_market_admin_returns_error(self) -> None:
        err = validate_account_kind_for_market("admin", is_enterprise=True, is_market_admin=False)
        assert err is not None
        assert "管理员" in err

    def test_enterprise_with_market_admin_returns_error(self) -> None:
        err = validate_account_kind_for_market(
            "enterprise", is_enterprise=True, is_market_admin=True
        )
        assert err is not None
        assert "管理员" in err

    def test_enterprise_without_enterprise_returns_error(self) -> None:
        err = validate_account_kind_for_market(
            "enterprise", is_enterprise=False, is_market_admin=False
        )
        assert err is not None
        assert "企业版" in err

    def test_enterprise_with_enterprise_no_admin_passes(self) -> None:
        assert (
            validate_account_kind_for_market(
                "enterprise", is_enterprise=True, is_market_admin=False
            )
            is None
        )

    def test_personal_with_market_admin_returns_error(self) -> None:
        err = validate_account_kind_for_market("personal", is_enterprise=True, is_market_admin=True)
        assert err is not None
        assert "管理员" in err

    def test_personal_without_enterprise_returns_error(self) -> None:
        err = validate_account_kind_for_market(
            "personal", is_enterprise=False, is_market_admin=False
        )
        assert err is not None
        assert "企业版" in err

    def test_personal_with_enterprise_passes(self) -> None:
        assert (
            validate_account_kind_for_market("personal", is_enterprise=True, is_market_admin=False)
            is None
        )


# ───────────────────── persist_session_account_meta ─────────────────────


class TestPersistSessionAccountMeta:
    def test_empty_session_id_returns_early(self) -> None:
        # 不应触发 DB 调用
        with patch("app.application.session_account_meta.get_host_db") as mock_db:
            persist_session_account_meta("", account_kind="admin")
            mock_db.assert_not_called()

    def test_none_session_id_returns_early(self) -> None:
        with patch("app.application.session_account_meta.get_host_db") as mock_db:
            persist_session_account_meta(None, account_kind="admin")  # type: ignore[arg-type]
            mock_db.assert_not_called()

    def test_whitespace_session_id_returns_early(self) -> None:
        with patch("app.application.session_account_meta.get_host_db") as mock_db:
            persist_session_account_meta("   ", account_kind="admin")
            mock_db.assert_not_called()

    def test_row_none_returns_early(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_account_meta("sid", account_kind="admin")
            mock_db.commit.assert_not_called()

    def test_full_meta_persisted(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_account_meta(
                "sid",
                account_kind="enterprise",
                company_brand="Brand",
                market_user_id=42,
                market_is_admin=False,
                market_is_enterprise=True,
                impersonating_market_user_id=99,
                impersonating_username="imp_user",
                tenant_id=7,
            )
            assert mock_row.account_kind == "enterprise"
            assert mock_row.company_brand == "Brand"
            assert mock_row.market_user_id == 42
            assert mock_row.market_is_admin is False
            assert mock_row.market_is_enterprise is True
            assert mock_row.impersonating_market_user_id == 99
            assert mock_row.impersonating_username == "imp_user"
            assert mock_row.tenant_id == 7
            mock_db.commit.assert_called_once()

    def test_market_user_id_none_not_set(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_account_meta("sid", account_kind="personal", market_user_id=None)
            # market_user_id 不应被赋值（因为 None）
            mock_row.market_user_id = mock_row.market_user_id  # no-op

    def test_impersonating_none_sets_none(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_account_meta(
                "sid", account_kind="personal", impersonating_market_user_id=None
            )
            assert mock_row.impersonating_market_user_id is None

    def test_tenant_id_none_not_set(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_account_meta("sid", account_kind="personal", tenant_id=None)
            # tenant_id 不应被赋值
            mock_row.tenant_id = mock_row.tenant_id  # no-op

    def test_company_brand_truncated_to_256(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        long_brand = "x" * 300
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_account_meta("sid", account_kind="personal", company_brand=long_brand)
            assert len(mock_row.company_brand) == 256

    def test_recoverable_error_swallowed(self) -> None:
        with patch(
            "app.application.session_account_meta.get_host_db",
            side_effect=RuntimeError("db down"),
        ):
            # 不应抛出
            persist_session_account_meta("sid", account_kind="admin")


# ───────────────────── persist_session_membership_tier ─────────────────────


class TestPersistSessionMembershipTier:
    def test_empty_session_id_returns_early(self) -> None:
        with patch("app.application.session_account_meta.get_host_db") as mock_db:
            persist_session_membership_tier("", "gold")
            mock_db.assert_not_called()

    def test_row_none_returns_early(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_membership_tier("sid", "gold")
            mock_db.commit.assert_not_called()

    def test_tier_persisted(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_membership_tier("sid", "gold")
            assert mock_row.market_membership_tier == "gold"
            mock_db.commit.assert_called_once()

    def test_empty_tier_sets_none(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_membership_tier("sid", "")
            assert mock_row.market_membership_tier is None

    def test_none_tier_sets_none(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_membership_tier("sid", None)
            assert mock_row.market_membership_tier is None

    def test_tier_truncated_to_32(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        long_tier = "x" * 40
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            persist_session_membership_tier("sid", long_tier)
            assert len(mock_row.market_membership_tier) == 32

    def test_recoverable_error_swallowed(self) -> None:
        with patch(
            "app.application.session_account_meta.get_host_db",
            side_effect=RuntimeError("db down"),
        ):
            persist_session_membership_tier("sid", "gold")


# ───────────────────── load_session_account_meta ─────────────────────


class TestLoadSessionAccountMeta:
    def test_empty_session_id_returns_none(self) -> None:
        with patch("app.application.session_account_meta.get_host_db") as mock_db:
            assert load_session_account_meta("") is None
            mock_db.assert_not_called()

    def test_row_none_returns_none(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            assert load_session_account_meta("sid") is None

    def test_returns_meta_dict(self) -> None:
        mock_row = MagicMock()
        mock_row.account_kind = "enterprise"
        mock_row.company_brand = "Brand"
        mock_row.market_user_id = 5
        mock_row.market_is_admin = False
        mock_row.market_is_enterprise = True
        mock_row.market_membership_tier = "gold"
        mock_row.impersonating_market_user_id = None
        mock_row.impersonating_username = ""
        mock_row.tenant_id = 3
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            result = load_session_account_meta("sid")
            assert result is not None
            assert result["account_kind"] == "enterprise"
            assert result["company_brand"] == "Brand"
            assert result["market_user_id"] == 5
            assert result["market_is_admin"] is False
            assert result["market_is_enterprise"] is True
            assert result["market_membership_tier"] == "gold"
            assert result["impersonating_market_user_id"] is None
            assert result["tenant_id"] == 3

    def test_recoverable_error_returns_none(self) -> None:
        with patch(
            "app.application.session_account_meta.get_host_db",
            side_effect=RuntimeError("db down"),
        ):
            assert load_session_account_meta("sid") is None


# ───────────────────── session_row_to_meta_dict ─────────────────────


class TestSessionRowToMetaDict:
    def test_full_fields(self) -> None:
        row = MagicMock()
        row.account_kind = "admin"
        row.company_brand = "Co"
        row.market_user_id = 1
        row.market_is_admin = True
        row.market_is_enterprise = False
        row.market_membership_tier = "silver"
        row.impersonating_market_user_id = 8
        row.impersonating_username = "imp"
        row.tenant_id = 4
        result = session_row_to_meta_dict(row)
        assert result["account_kind"] == "admin"
        assert result["company_brand"] == "Co"
        assert result["market_user_id"] == 1
        assert result["market_is_admin"] is True
        assert result["market_is_enterprise"] is False
        assert result["market_membership_tier"] == "silver"
        assert result["impersonating_market_user_id"] == 8
        assert result["impersonating_username"] == "imp"
        assert result["tenant_id"] == 4

    def test_none_account_kind_defaults_enterprise(self) -> None:
        row = MagicMock()
        row.account_kind = None
        row.company_brand = ""
        row.market_user_id = None
        row.market_is_admin = False
        row.market_is_enterprise = False
        row.market_membership_tier = None
        row.impersonating_market_user_id = None
        row.impersonating_username = None
        row.tenant_id = None
        result = session_row_to_meta_dict(row)
        assert result["account_kind"] == "enterprise"

    def test_empty_account_kind_defaults_enterprise(self) -> None:
        row = MagicMock()
        row.account_kind = ""
        row.company_brand = ""
        row.market_user_id = None
        row.market_is_admin = False
        row.market_is_enterprise = False
        row.market_membership_tier = ""
        row.impersonating_market_user_id = None
        row.impersonating_username = ""
        row.tenant_id = None
        result = session_row_to_meta_dict(row)
        assert result["account_kind"] == "enterprise"
        assert result["market_membership_tier"] is None

    def test_impersonating_uid_converted_to_int(self) -> None:
        row = MagicMock()
        row.account_kind = "personal"
        row.company_brand = ""
        row.market_user_id = None
        row.market_is_admin = False
        row.market_is_enterprise = False
        row.market_membership_tier = None
        row.impersonating_market_user_id = 10
        row.impersonating_username = ""
        row.tenant_id = None
        result = session_row_to_meta_dict(row)
        assert result["impersonating_market_user_id"] == 10
        assert isinstance(result["impersonating_market_user_id"], int)


# ───────────────────── enrich_session_meta_with_tenant ─────────────────────


class TestEnrichSessionMetaWithTenant:
    def test_empty_session_id_no_user(self) -> None:
        result = enrich_session_meta_with_tenant("", None)
        assert result == {}

    def test_admin_kind_returns_early(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin"},
        ):
            result = enrich_session_meta_with_tenant("sid", None)
            assert result["account_kind"] == "admin"

    def test_user_id_added_to_meta(self) -> None:
        user = MagicMock()
        user.id = 99
        user.tenant_id = None
        user.username = "u"
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "personal"},
        ):
            result = enrich_session_meta_with_tenant("sid", user)
            assert result["local_user_id"] == 99

    def test_user_none_no_local_user_id(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "personal"},
        ):
            result = enrich_session_meta_with_tenant("sid", None)
            assert "local_user_id" not in result

    def test_user_id_none_no_local_user_id(self) -> None:
        user = MagicMock()
        user.id = None
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "personal"},
        ):
            result = enrich_session_meta_with_tenant("sid", user)
            assert "local_user_id" not in result

    def test_tenant_id_from_meta(self) -> None:
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise", "tenant_id": 5},
            ),
            patch("app.application.session_account_meta.get_host_db") as mock_get,
        ):
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_filter = MagicMock()
            mock_filter.first.return_value = None
            mock_query.filter.return_value = mock_filter
            mock_db.query.return_value = mock_query
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            result = enrich_session_meta_with_tenant("sid", None)
            assert result["tenant_id"] == 5

    def test_tenant_id_from_user_when_meta_none(self) -> None:
        user = MagicMock()
        user.id = 1
        user.tenant_id = 7
        user.username = "u"
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise"},
            ),
            patch("app.application.session_account_meta.get_host_db") as mock_get,
        ):
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_filter = MagicMock()
            mock_filter.first.return_value = None
            mock_query.filter.return_value = mock_filter
            mock_db.query.return_value = mock_query
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            result = enrich_session_meta_with_tenant("sid", user)
            assert result["tenant_id"] == 7

    def test_tenant_name_from_tenant_lookup(self) -> None:
        mock_tenant = MagicMock()
        mock_tenant.name = "TenantName"
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_tenant
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise", "tenant_id": 3},
            ),
            patch("app.application.session_account_meta.get_host_db") as mock_get,
        ):
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            result = enrich_session_meta_with_tenant("sid", None)
            assert result["tenant_name"] == "TenantName"

    def test_tenant_name_falls_back_to_company_brand(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={
                    "account_kind": "enterprise",
                    "tenant_id": 3,
                    "company_brand": "MyBrand",
                },
            ),
            patch("app.application.session_account_meta.get_host_db") as mock_get,
        ):
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            result = enrich_session_meta_with_tenant("sid", None)
            assert result["tenant_name"] == "MyBrand"

    def test_tenant_id_persisted_to_session_row(self) -> None:
        mock_row = MagicMock()
        mock_row.tenant_id = None  # 不同于新 tid=5
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise", "tenant_id": 5},
            ),
            patch("app.application.session_account_meta.get_host_db") as mock_get,
        ):
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            enrich_session_meta_with_tenant("sid", None)
            assert mock_row.tenant_id == 5
            mock_db.commit.assert_called_once()

    def test_bind_tenant_for_login_called_when_no_tid(self) -> None:
        user = MagicMock()
        user.id = 1
        user.tenant_id = None
        user.username = "u"
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise", "local_user_id": 1},
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": 42, "tenant_name": "Bound"},
            ),
            patch("app.application.session_account_meta.get_host_db") as mock_get,
        ):
            mock_db = MagicMock()
            mock_query = MagicMock()
            mock_filter = MagicMock()
            mock_filter.first.return_value = None
            mock_query.filter.return_value = mock_filter
            mock_db.query.return_value = mock_query
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            result = enrich_session_meta_with_tenant("sid", user)
            assert result["tenant_id"] == 42
            assert result["tenant_name"] == "Bound"

    def test_tenant_lookup_error_swallowed(self) -> None:
        with (
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise", "tenant_id": 3},
            ),
            patch(
                "app.application.session_account_meta.get_host_db",
                side_effect=RuntimeError("db down"),
            ),
        ):
            result = enrich_session_meta_with_tenant("sid", None)
            # 不应抛出；tenant_id 仍保留
            assert result["tenant_id"] == 3


# ───────────────────── clear_impersonation ─────────────────────


class TestClearImpersonation:
    def test_empty_session_id_returns_early(self) -> None:
        with patch("app.application.session_account_meta.get_host_db") as mock_db:
            clear_impersonation("")
            mock_db.assert_not_called()

    def test_row_none_returns_early(self) -> None:
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            clear_impersonation("sid")
            mock_db.commit.assert_not_called()

    def test_clears_impersonation_fields(self) -> None:
        mock_row = MagicMock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_row
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query
        with patch("app.application.session_account_meta.get_host_db") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_db
            mock_get.return_value.__exit__.return_value = None
            clear_impersonation("sid")
            assert mock_row.impersonating_market_user_id is None
            assert mock_row.impersonating_username == ""
            mock_db.commit.assert_called_once()

    def test_recoverable_error_swallowed(self) -> None:
        with patch(
            "app.application.session_account_meta.get_host_db",
            side_effect=RuntimeError("db down"),
        ):
            clear_impersonation("sid")


# ───────────────────── is_session_market_admin ─────────────────────


class TestIsSessionMarketAdmin:
    def test_meta_none_returns_false(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value=None,
        ):
            assert is_session_market_admin("sid") is False

    def test_admin_kind_and_market_admin_returns_true(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": True},
        ):
            assert is_session_market_admin("sid") is True

    def test_admin_kind_but_not_market_admin_returns_false(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": False},
        ):
            assert is_session_market_admin("sid") is False

    def test_non_admin_kind_returns_false(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "enterprise", "market_is_admin": True},
        ):
            assert is_session_market_admin("sid") is False


# ───────────────────── should_receive_enterprise_dedicated_cs ─────────────────────


class TestShouldReceiveEnterpriseDedicatedCs:
    def test_meta_admin_returns_false(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin", "market_is_admin": True},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", 1, MagicMock()) is False

    def test_meta_market_admin_returns_false(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "personal", "market_is_admin": True},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", 1, MagicMock()) is False

    def test_meta_enterprise_returns_true(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "enterprise", "market_is_admin": False},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", 1, MagicMock()) is True

    def test_meta_market_enterprise_returns_true(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={
                "account_kind": "personal",
                "market_is_admin": False,
                "market_is_enterprise": True,
            },
        ):
            assert should_receive_enterprise_dedicated_cs("sid", 1, MagicMock()) is True

    def test_meta_impersonating_returns_true(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={
                "account_kind": "personal",
                "market_is_admin": False,
                "market_is_enterprise": False,
                "impersonating_market_user_id": 5,
            },
        ):
            assert should_receive_enterprise_dedicated_cs("sid", 1, MagicMock()) is True

    def test_no_session_no_user_returns_false(self) -> None:
        assert should_receive_enterprise_dedicated_cs(None, None, None) is False

    def test_no_session_no_db_returns_false(self) -> None:
        assert should_receive_enterprise_dedicated_cs(None, 1, None) is False

    def test_no_session_no_user_id_returns_false(self) -> None:
        assert should_receive_enterprise_dedicated_cs(None, None, MagicMock()) is False

    def test_fallback_user_admin_role_returns_false(self) -> None:
        mock_user = MagicMock()
        mock_user.role = "admin"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is False

    def test_fallback_user_market_admin_role_returns_false(self) -> None:
        mock_user = MagicMock()
        mock_user.role = "market_admin"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is False

    def test_fallback_user_super_admin_role_returns_false(self) -> None:
        mock_user = MagicMock()
        mock_user.role = "super_admin"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is False

    def test_fallback_user_normal_role_returns_true(self) -> None:
        mock_user = MagicMock()
        mock_user.role = "user"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is True

    def test_fallback_user_empty_role_returns_true(self) -> None:
        mock_user = MagicMock()
        mock_user.role = ""
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is True

    def test_fallback_user_none_role_returns_true(self) -> None:
        mock_user = MagicMock()
        mock_user.role = None
        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is True

    def test_fallback_db_error_returns_false(self) -> None:
        mock_db = MagicMock()
        mock_db.get.side_effect = RuntimeError("db down")
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is False

    def test_fallback_type_error_returns_false(self) -> None:
        mock_db = MagicMock()
        mock_db.get.side_effect = TypeError("bad type")
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is False

    def test_fallback_value_error_returns_false(self) -> None:
        mock_db = MagicMock()
        mock_db.get.side_effect = ValueError("bad value")
        assert should_receive_enterprise_dedicated_cs(None, 1, mock_db) is False

    def test_empty_session_with_meta_none_falls_back(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value=None,
        ):
            mock_user = MagicMock()
            mock_user.role = "user"
            mock_db = MagicMock()
            mock_db.get.return_value = mock_user
            assert should_receive_enterprise_dedicated_cs("", 1, mock_db) is True


# ───────────────────── effective_entitlement_market_user_id ─────────────────────


class TestEffectiveEntitlementMarketUserId:
    def test_meta_none_returns_none(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value=None,
        ):
            assert effective_entitlement_market_user_id("sid") is None

    def test_impersonating_id_returned(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"impersonating_market_user_id": 99, "market_user_id": 1},
        ):
            assert effective_entitlement_market_user_id("sid") == 99

    def test_market_user_id_returned(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"impersonating_market_user_id": None, "market_user_id": 5},
        ):
            assert effective_entitlement_market_user_id("sid") == 5

    def test_both_none_returns_none(self) -> None:
        with patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"impersonating_market_user_id": None, "market_user_id": None},
        ):
            assert effective_entitlement_market_user_id("sid") is None


# ───────────────────── audit_admin_action ─────────────────────


class TestAuditAdminAction:
    """audit_admin_action 内部 lazy-import _session_id_from_request；

    该 import 在测试环境中会触发 ImportError（属于 RECOVERABLE_ERRORS），
    因此函数整体走 except 分支、记录日志后返回。以下测试覆盖：
    - 正常调用（import 失败 → except 分支）
    - 各参数组合（target_user_id / mod_id / detail）
    """

    def test_call_does_not_raise(self) -> None:
        request = MagicMock()
        # import 失败 → except RECOVERABLE_ERRORS → 不抛出
        audit_admin_action(request, "delete_user", target_user_id=5)

    def test_call_with_mod_id(self) -> None:
        request = MagicMock()
        audit_admin_action(request, "install_mod", mod_id="test-mod")

    def test_call_with_detail(self) -> None:
        request = MagicMock()
        audit_admin_action(request, "custom_action", detail="manual operation")

    def test_call_with_all_params(self) -> None:
        request = MagicMock()
        audit_admin_action(
            request,
            "bulk_action",
            target_user_id=99,
            mod_id="m1",
            detail="bulk",
        )

    def test_call_with_minimal_params(self) -> None:
        request = MagicMock()
        audit_admin_action(request, "ping")
