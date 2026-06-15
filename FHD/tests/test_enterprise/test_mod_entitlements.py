"""mod_entitlements 测试 — 覆盖企业版 Mod 可见性、权益缓存、过滤等。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enterprise import mod_entitlements


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后重置全局缓存。"""
    mod_entitlements._cached_market_user_id = None
    mod_entitlements._cached_market_username = ""
    mod_entitlements._cached_entitled_client_mod_ids = None
    mod_entitlements._cached_account_kind = "enterprise"
    mod_entitlements._cached_market_is_admin = False
    yield
    mod_entitlements._cached_market_user_id = None
    mod_entitlements._cached_market_username = ""
    mod_entitlements._cached_entitled_client_mod_ids = None
    mod_entitlements._cached_account_kind = "enterprise"
    mod_entitlements._cached_market_is_admin = False


# ---------------------------------------------------------------------------
# is_client_mod_id
# ---------------------------------------------------------------------------


class TestIsClientModId:
    def test_known_client_mod(self):
        from app.mod_sdk.platform_shell import PROTECTED_CLIENT_MOD_IDS
        if PROTECTED_CLIENT_MOD_IDS:
            mid = next(iter(PROTECTED_CLIENT_MOD_IDS))
            assert mod_entitlements.is_client_mod_id(mid) is True

    def test_unknown_mod(self):
        assert mod_entitlements.is_client_mod_id("nonexistent-mod-id") is False

    def test_empty_string(self):
        assert mod_entitlements.is_client_mod_id("") is False

    def test_whitespace(self):
        assert mod_entitlements.is_client_mod_id("  ") is False


# ---------------------------------------------------------------------------
# host_mod_ids_for_enterprise
# ---------------------------------------------------------------------------


class TestHostModIdsForEnterprise:
    def test_returns_frozenset(self):
        result = mod_entitlements.host_mod_ids_for_enterprise()
        assert isinstance(result, frozenset)


# ---------------------------------------------------------------------------
# enterprise_mod_filter_active
# ---------------------------------------------------------------------------


class TestEnterpriseModFilterActive:
    def test_enterprise_sku(self, monkeypatch):
        with patch("app.enterprise.mod_entitlements.resolve_product_sku", return_value="enterprise"):
            assert mod_entitlements.enterprise_mod_filter_active() is True

    def test_personal_sku(self, monkeypatch):
        with patch("app.enterprise.mod_entitlements.resolve_product_sku", return_value="personal"):
            assert mod_entitlements.enterprise_mod_filter_active() is False


# ---------------------------------------------------------------------------
# get_cached_entitled_client_mod_ids
# ---------------------------------------------------------------------------


class TestGetCachedEntitledClientModIds:
    def test_non_enterprise_returns_none(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False):
            assert mod_entitlements.get_cached_entitled_client_mod_ids() is None

    def test_enterprise_returns_set(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True):
            mod_entitlements._cached_entitled_client_mod_ids = {"mod-a", "mod-b"}
            result = mod_entitlements.get_cached_entitled_client_mod_ids()
            assert result == {"mod-a", "mod-b"}

    def test_enterprise_no_cache_returns_empty_set(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True):
            mod_entitlements._cached_entitled_client_mod_ids = None
            result = mod_entitlements.get_cached_entitled_client_mod_ids()
            assert result == set()


# ---------------------------------------------------------------------------
# get_cached_market_identity
# ---------------------------------------------------------------------------


class TestGetCachedMarketIdentity:
    def test_default(self):
        uid, uname = mod_entitlements.get_cached_market_identity()
        assert uid is None
        assert uname == ""

    def test_after_set(self):
        mod_entitlements._cached_market_user_id = 42
        mod_entitlements._cached_market_username = "testuser"
        uid, uname = mod_entitlements.get_cached_market_identity()
        assert uid == 42
        assert uname == "testuser"


# ---------------------------------------------------------------------------
# clear_session_entitlements
# ---------------------------------------------------------------------------


class TestClearSessionEntitlements:
    def test_clears(self):
        mod_entitlements._cached_market_user_id = 1
        mod_entitlements._cached_market_username = "u"
        mod_entitlements._cached_entitled_client_mod_ids = {"a"}
        mod_entitlements._cached_account_kind = "admin"
        mod_entitlements._cached_market_is_admin = True
        mod_entitlements.clear_session_entitlements()
        assert mod_entitlements._cached_market_user_id is None
        assert mod_entitlements._cached_market_username == ""
        assert mod_entitlements._cached_entitled_client_mod_ids is None
        assert mod_entitlements._cached_account_kind == "enterprise"
        assert mod_entitlements._cached_market_is_admin is False


# ---------------------------------------------------------------------------
# set_session_entitlements
# ---------------------------------------------------------------------------


class TestSetSessionEntitlements:
    def test_set(self):
        mod_entitlements.set_session_entitlements(
            market_user_id=10,
            market_username="admin",
            entitled_client_mod_ids={"mod-x"},
            account_kind="admin",
            market_is_admin=True,
        )
        assert mod_entitlements._cached_market_user_id == 10
        assert mod_entitlements._cached_market_username == "admin"
        assert mod_entitlements._cached_entitled_client_mod_ids == {"mod-x"}
        assert mod_entitlements._cached_account_kind == "admin"
        assert mod_entitlements._cached_market_is_admin is True

    def test_empty_username_stripped(self):
        mod_entitlements.set_session_entitlements(
            market_user_id=None,
            market_username="  ",
            entitled_client_mod_ids=set(),
        )
        assert mod_entitlements._cached_market_username == ""

    def test_empty_account_kind_defaults(self):
        mod_entitlements.set_session_entitlements(
            market_user_id=None,
            market_username="u",
            entitled_client_mod_ids=set(),
            account_kind="",
        )
        assert mod_entitlements._cached_account_kind == "enterprise"


# ---------------------------------------------------------------------------
# is_admin_account_session
# ---------------------------------------------------------------------------


class TestIsAdminAccountSession:
    def test_admin_and_is_admin(self):
        mod_entitlements._cached_account_kind = "admin"
        mod_entitlements._cached_market_is_admin = True
        assert mod_entitlements.is_admin_account_session() is True

    def test_admin_not_is_admin(self):
        mod_entitlements._cached_account_kind = "admin"
        mod_entitlements._cached_market_is_admin = False
        assert mod_entitlements.is_admin_account_session() is False

    def test_enterprise_not_admin(self):
        mod_entitlements._cached_account_kind = "enterprise"
        mod_entitlements._cached_market_is_admin = True
        assert mod_entitlements.is_admin_account_session() is False


# ---------------------------------------------------------------------------
# is_mod_visible_for_enterprise
# ---------------------------------------------------------------------------


class TestIsModVisibleForEnterprise:
    def test_empty_mod_id(self):
        assert mod_entitlements.is_mod_visible_for_enterprise("") is False

    def test_non_enterprise_always_visible(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False):
            assert mod_entitlements.is_mod_visible_for_enterprise("any-mod") is True

    def test_non_client_mod_visible(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=False):
            assert mod_entitlements.is_mod_visible_for_enterprise("host-mod") is True

    def test_admin_sees_all(self):
        mod_entitlements._cached_account_kind = "admin"
        mod_entitlements._cached_market_is_admin = True
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True):
            assert mod_entitlements.is_mod_visible_for_enterprise("client-mod") is True

    def test_client_mod_in_entitled_set(self):
        mod_entitlements._cached_entitled_client_mod_ids = {"client-mod-a"}
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_admin_account_session", return_value=False), \
             patch("app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids", return_value={"client-mod-a"}):
            assert mod_entitlements.is_mod_visible_for_enterprise("client-mod-a") is True

    def test_client_mod_not_in_entitled_set(self):
        mod_entitlements._cached_entitled_client_mod_ids = set()
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_admin_account_session", return_value=False), \
             patch("app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids", return_value=set()):
            assert mod_entitlements.is_mod_visible_for_enterprise("client-mod-b") is False

    def test_client_mod_none_entitled_returns_false(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_admin_account_session", return_value=False), \
             patch("app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids", return_value=None):
            assert mod_entitlements.is_mod_visible_for_enterprise("client-mod-c") is False


# ---------------------------------------------------------------------------
# filter_mod_rows_for_enterprise
# ---------------------------------------------------------------------------


class TestFilterModRowsForEnterprise:
    def test_non_enterprise_passes_through(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False):
            rows = [{"id": "a"}, {"id": "b"}]
            assert mod_entitlements.filter_mod_rows_for_enterprise(rows) == rows

    def test_enterprise_filters(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", side_effect=lambda m: m == "visible"):
            rows = [{"id": "visible"}, {"id": "hidden"}]
            result = mod_entitlements.filter_mod_rows_for_enterprise(rows)
            assert len(result) == 1
            assert result[0]["id"] == "visible"


class TestFilterModIdListForEnterprise:
    def test_non_enterprise_passes_through(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False):
            ids = ["a", "b"]
            assert mod_entitlements.filter_mod_id_list_for_enterprise(ids) == ids

    def test_enterprise_filters(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", side_effect=lambda m: m == "visible"):
            ids = ["visible", "hidden"]
            result = mod_entitlements.filter_mod_id_list_for_enterprise(ids)
            assert result == ["visible"]


# ---------------------------------------------------------------------------
# _parse_mod_ids_from_market_payload
# ---------------------------------------------------------------------------


class TestParseModIdsFromMarketPayload:
    def test_non_dict_returns_empty(self):
        assert mod_entitlements._parse_mod_ids_from_market_payload("not a dict") == set()

    def test_mod_ids_list(self):
        with patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True):
            result = mod_entitlements._parse_mod_ids_from_market_payload({"mod_ids": ["a", "b"]})
            assert result == {"a", "b"}

    def test_data_list(self):
        result = mod_entitlements._parse_mod_ids_from_market_payload({"data": [{"id": "x"}, {"id": "y"}]})
        assert result == {"x", "y"}

    def test_data_mods_list(self):
        result = mod_entitlements._parse_mod_ids_from_market_payload({"data": {"mods": [{"id": "m1"}]}})
        assert result == {"m1"}

    def test_empty_mod_ids_falls_back(self):
        with patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True):
            result = mod_entitlements._parse_mod_ids_from_market_payload({"mod_ids": [], "data": [{"id": "z"}]})
            assert "z" in result

    def test_non_dict_rows_skipped(self):
        result = mod_entitlements._parse_mod_ids_from_market_payload({"data": ["not_a_dict"]})
        assert result == set()


# ---------------------------------------------------------------------------
# fetch_entitled_client_mod_ids_from_market
# ---------------------------------------------------------------------------


class TestFetchEntitledClientModIdsFromMarket:
    @pytest.mark.asyncio
    async def test_empty_token(self):
        result = await mod_entitlements.fetch_entitled_client_mod_ids_from_market("")
        assert result == set()

    @pytest.mark.asyncio
    async def test_proxy_error(self):
        with patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as mock_proxy:
            mock_proxy.return_value = {"__proxy_error__": True, "detail": "fail"}
            result = await mod_entitlements.fetch_entitled_client_mod_ids_from_market("tok")
            assert result == set()

    @pytest.mark.asyncio
    async def test_success_with_mod_ids(self):
        with patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as mock_proxy, \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True):
            mock_proxy.return_value = {"mod_ids": ["a", "b"]}
            result = await mod_entitlements.fetch_entitled_client_mod_ids_from_market("tok")
            assert "a" in result
            assert "b" in result


# ---------------------------------------------------------------------------
# refresh_session_entitlements_from_market
# ---------------------------------------------------------------------------


class TestRefreshSessionEntitlementsFromMarket:
    @pytest.mark.asyncio
    async def test_admin_with_impersonation(self):
        with patch("app.application.session_account_meta.load_session_account_meta", return_value={
                 "account_kind": "admin", "market_is_admin": True, "impersonating_market_user_id": 5
             }), \
             patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as mock_proxy, \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True), \
             patch("app.enterprise.mod_entitlements._augment_entitled_for_username", side_effect=lambda u, s: s):
            mock_proxy.return_value = {"mod_ids": ["mod-imp"]}
            result = await mod_entitlements.refresh_session_entitlements_from_market(
                market_token="tok", session_id="sid"
            )
            assert "mod-imp" in result

    @pytest.mark.asyncio
    async def test_admin_without_impersonation(self):
        with patch("app.application.session_account_meta.load_session_account_meta", return_value={
                 "account_kind": "admin", "market_is_admin": True
             }), \
             patch("app.enterprise.mod_entitlements._augment_entitled_for_username", side_effect=lambda u, s: s):
            result = await mod_entitlements.refresh_session_entitlements_from_market(
                market_token="tok", session_id="sid"
            )
            # admin without impersonation gets all PROTECTED_CLIENT_MOD_IDS
            assert isinstance(result, set)

    @pytest.mark.asyncio
    async def test_regular_user(self):
        with patch("app.application.session_account_meta.load_session_account_meta", return_value={
                 "account_kind": "enterprise"
             }), \
             patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as mock_proxy, \
             patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True), \
             patch("app.enterprise.mod_entitlements._augment_entitled_for_username", side_effect=lambda u, s: s):
            mock_proxy.return_value = {"mod_ids": ["mod-1"]}
            result = await mod_entitlements.refresh_session_entitlements_from_market(
                market_token="tok", session_id="sid"
            )
            assert "mod-1" in result


# ---------------------------------------------------------------------------
# persist / restore entitlements
# ---------------------------------------------------------------------------


class TestPersistEntitlementsToSessionRow:
    def test_empty_sid_noop(self):
        # Should not raise
        mod_entitlements.persist_entitlements_to_session_row("", set())

    def test_persist_calls_db(self):
        with patch("app.db.session.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
            mod_entitlements.persist_entitlements_to_session_row("sid-1", {"mod-a"})
            assert mock_db.commit.called


class TestRestoreEntitlementsFromSessionRow:
    def test_empty_sid(self):
        assert mod_entitlements.restore_entitlements_from_session_row("") is False

    def test_non_enterprise(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False):
            assert mod_entitlements.restore_entitlements_from_session_row("sid") is False

    def test_session_not_found(self):
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.db.session.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = None
            assert mod_entitlements.restore_entitlements_from_session_row("sid") is False
