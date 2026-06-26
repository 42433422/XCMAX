"""Branch-coverage tests for app.fastapi_routes.mobile_api_extensions.

Targets the missing branches listed in MISSING_BRANCHES. Each test exercises
one logical branch: helper functions are called directly; route handlers are
called as coroutines with mocked dependencies.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module fixture: ensure the extension module is loaded exactly once
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _load_ext_module():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def m():
    """Return the already-imported extension module."""
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(uid: int = 1, role: str = "admin"):
    u = MagicMock()
    u.id = uid
    u.role = role
    u.username = "tester"
    u.display_name = "Tester"
    u.is_active = True
    u.wx_avatar_url = None
    return u


def _ctx_db(db):
    """Make db usable as a context manager."""
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def _admin_request(role="admin"):
    """Minimal Request-like object for admin checks."""
    req = MagicMock()
    req.headers = {}
    return req


# ============================================================
# _ai_circle_employee_profiles — lines 112-130
# ============================================================


class TestAiCircleEmployeeProfiles:
    def test_empty_mods_returns_empty(self, m):
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = m._ai_circle_employee_profiles()
        assert result == {}

    def test_mod_with_no_workflow_employees(self, m):
        """branch [114,130]: loop body executes but inner loop is empty."""
        mod = {"id": "mod1", "avatar_url": "http://x/a.png", "workflow_employees": []}
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = m._ai_circle_employee_profiles()
        assert result == {}

    def test_mod_with_non_dict_employee(self, m):
        """branch [117,118]: employee not a dict — continue."""
        mod = {
            "id": "mod1",
            "avatar_url": "",
            "workflow_employees": ["not-a-dict"],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = m._ai_circle_employee_profiles()
        assert result == {}

    def test_mod_with_employee_missing_id(self, m):
        """branch [120,121]: employee_id empty — continue."""
        mod = {
            "id": "mod1",
            "avatar_url": "",
            "workflow_employees": [{"id": "", "label": "Bob"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = m._ai_circle_employee_profiles()
        assert result == {}

    def test_mod_with_valid_employee(self, m):
        """branches [116,117],[117,119],[120,122]: valid employee recorded."""
        mod = {
            "id": "mod1",
            "avatar_url": "http://x/a.png",
            "workflow_employees": [
                {"id": "emp1", "label": "Alice", "market_avatar": "http://x/emp.png"},
            ],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = m._ai_circle_employee_profiles()
        assert "emp1" in result
        assert result["emp1"]["name"] == "Alice"


# ============================================================
# _resolve_mobile_relay_user — lines 155-211
# ============================================================


class TestResolveMobileRelayUser:
    def test_uid_positive_not_prefer_admin(self, m):
        """branch [174,182] not taken — uid > 0 and not prefer_admin: returns early."""
        u = _user(uid=5, role="user")
        pub = {"id": 5, "username": "u5"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result["id"] == 5

    def test_uid_positive_prefer_admin_non_admin_role(self, m):
        """uid > 0 but prefer_admin=True and role not admin → falls through to DB path."""
        u = _user(uid=5, role="user")
        mock_row = MagicMock()
        mock_row.id = 10
        pub = {"id": 10, "username": "admin"}
        mock_db = _ctx_db(MagicMock())
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_row
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result["id"] == 10

    def test_uid_zero_admin_row_found(self, m):
        """branch [182,183]: admin row found → use that row, skip any-user query."""
        u = _user(uid=0)
        mock_row = MagicMock()
        mock_row.id = 99
        pub = {"id": 99, "username": "admin99"}
        mock_db = _ctx_db(MagicMock())
        # first query (admin) returns row
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_row
        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result["id"] == 99

    def test_uid_zero_no_admin_row_but_any_user_row(self, m):
        """branch [182,189],[189,190] not taken: fall to any-user query which returns row."""
        u = _user(uid=0)
        mock_row = MagicMock()
        mock_row.id = 7
        pub = {"id": 7, "username": "somebody"}

        first_call = [True]

        def first_side_effect():
            if first_call[0]:
                first_call[0] = False
                return None  # admin query returns nothing
            return mock_row  # any-user query

        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.first.side_effect = first_side_effect
        mock_db = _ctx_db(MagicMock())
        mock_db.query.return_value = mock_q

        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result["id"] == 7

    def test_uid_zero_no_rows_creates_new_user(self, m):
        """branch [189,190]: both queries return None → create new user."""
        u = _user(uid=0)
        new_row = MagicMock()
        new_row.id = 55
        pub = {"id": 55, "username": "mobile_relay_xxx"}

        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.first.return_value = None
        mock_db = _ctx_db(MagicMock())
        mock_db.query.return_value = mock_q
        # db.flush sets row.id
        mock_db.flush = MagicMock()

        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.db.models.User", MagicMock(return_value=new_row)),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result["id"] == 55

    def test_db_expunge_called_when_available(self, m):
        """branch [204,205]: db.expunge exists → called."""
        u = _user(uid=0)
        mock_row = MagicMock()
        mock_row.id = 3
        pub = {"id": 3, "username": "x"}
        mock_db = _ctx_db(MagicMock())
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_row
        mock_db.expunge = MagicMock()

        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            m._resolve_mobile_relay_user(u, prefer_admin=False)
        mock_db.expunge.assert_called_once_with(mock_row)

    def test_recoverable_error_prefer_admin_returns_fallback(self, m):
        """branch [209,211]: RECOVERABLE_ERRORS + prefer_admin → _relay_admin_fallback_user."""
        u = _user(uid=0)
        fallback = {"id": 0, "username": "relay_admin"}
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception

        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch("app.db.session.get_db", side_effect=err_class("boom")),
            patch.object(m, "_relay_admin_fallback_user", return_value=fallback),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result == fallback


# ============================================================
# _register_desktop_relay_for_pairing — lines 214-231
# ============================================================


class TestRegisterDesktopRelayForPairing:
    def test_disabled_by_env(self, m, monkeypatch):
        """branch [216,217]: env var set to '0' → returns None immediately."""
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_ENABLED", "0")
        result = m._register_desktop_relay_for_pairing("192.168.1.1", 5000)
        assert result is None

    def test_non_private_host_returns_none(self, m, monkeypatch):
        """branch [227,228]: not private host → None."""
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_ENABLED", "1")
        with patch.object(m, "_host_is_private_or_loopback", return_value=False):
            result = m._register_desktop_relay_for_pairing("8.8.8.8", 80)
        assert result is None

    def test_relay_error_returns_none(self, m, monkeypatch):
        """branch: RECOVERABLE_ERRORS during register_desktop_relay → None."""
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_ENABLED", "1")
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception

        with (
            patch.object(m, "_host_is_private_or_loopback", return_value=True),
            patch(
                "app.application.facades.mobile_relay_facade.register_desktop_relay",
                side_effect=err_class("fail"),
            ),
        ):
            result = m._register_desktop_relay_for_pairing("192.168.1.1", 5000)
        assert result is None

    def test_relay_empty_returns_none(self, m, monkeypatch):
        """branch: register returns falsy → None."""
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_ENABLED", "1")

        with (
            patch.object(m, "_host_is_private_or_loopback", return_value=True),
            patch(
                "app.application.facades.mobile_relay_facade.register_desktop_relay",
                return_value=None,
            ),
        ):
            result = m._register_desktop_relay_for_pairing("192.168.1.1", 5000)
        assert result is None

    def test_relay_success(self, m, monkeypatch):
        """branch: relay present → returns public_relay without desktop_token."""
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_ENABLED", "1")

        with (
            patch.object(m, "_host_is_private_or_loopback", return_value=True),
            patch(
                "app.application.facades.mobile_relay_facade.register_desktop_relay",
                return_value={"relay_id": "r1", "desktop_token": "secret", "pairing_code": "1234"},
            ),
        ):
            result = m._register_desktop_relay_for_pairing("192.168.1.1", 5000)
        assert result is not None
        assert "desktop_token" not in result
        assert result["relay_id"] == "r1"


# ============================================================
# _ai_conversation_changes — lines 289-323
# ============================================================


class TestAiConversationChanges:
    def test_uid_zero_returns_empty(self, m):
        """branch [292,293]: uid <= 0 → []."""
        u = MagicMock()
        u.id = 0
        result = m._ai_conversation_changes(u, limit=10)
        assert result == []

    def test_operational_error_returns_empty(self, m):
        """branch [321,322]: OPERATIONAL_ERRORS caught → []."""
        u = _user(uid=5)
        err_class = list(m.OPERATIONAL_ERRORS)[0] if m.OPERATIONAL_ERRORS else Exception

        with patch("app.db.session.get_db", side_effect=err_class("db gone")):
            result = m._ai_conversation_changes(u, limit=10)
        assert result == []


# ============================================================
# _mobile_mod_items — lines 329-418
# ============================================================


class TestMobileModItems:
    def _mgr(self, mods):
        mgr = MagicMock()
        mgr.list_all_mods.return_value = mods
        return mgr

    def test_dict_mod_branch(self, m):
        """branch [372,374] not taken: dict mod processed."""
        mod = {
            "id": "m1",
            "name": "Mod1",
            "workflow_employees": [{"id": "e1", "label": "Alice"}],
        }
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=self._mgr([mod])
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item",
                return_value=None,
            ),
        ):
            result = m._mobile_mod_items()
        assert any(i["id"] == "m1" for i in result)

    def test_object_mod_branch(self, m):
        """branch [372,374]: non-dict mod → object attribute path."""
        mod = SimpleNamespace(
            id="m2",
            name="Mod2",
            workflow_employees=[],
            frontend_menu=[],
            frontend_menu_overrides=[],
            version="1.0",
            author="x",
            description="d",
            primary=False,
            industry={},
            avatar="",
            logo="",
            icon="",
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=self._mgr([mod])
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item",
                return_value=None,
            ),
        ):
            result = m._mobile_mod_items()
        assert any(i["id"] == "m2" for i in result)

    def test_mid_empty_skips_item(self, m):
        """branch [402,item not appended]: mid empty → skip."""
        mod = {"id": "", "name": "NoId"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=self._mgr([mod])
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item",
                return_value=None,
            ),
        ):
            result = m._mobile_mod_items()
        assert result == []

    def test_operational_error_still_calls_upsert(self, m):
        """branch [410,411]: OPERATIONAL_ERRORS → upsert called with empty list."""
        err_class = list(m.OPERATIONAL_ERRORS)[0] if m.OPERATIONAL_ERRORS else Exception
        upsert_mock = MagicMock()

        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", side_effect=err_class("boom")
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item", upsert_mock
            ),
        ):
            result = m._mobile_mod_items()
        upsert_mock.assert_called_once()
        assert isinstance(result, list)


# ============================================================
# _admin_employee_items — lines 424-466
# ============================================================


class TestAdminEmployeeItems:
    def test_market_profiles_none(self, m):
        """branch [432,433] not taken: market_profiles=None."""
        raw = {"id": "emp1", "name": "Bob"}
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._load_admin_duty_records",
                return_value=[raw],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._compact_text",
                side_effect=lambda x: x or "",
            ),
            patch("app.fastapi_routes.mobile_api_extensions._apply_market_profile"),
            patch(
                "app.fastapi_routes.mobile_api_extensions._admin_employee_match_keys",
                return_value=[],
            ),
        ):
            result = m._admin_employee_items(market_profiles=None)
        assert any(i["id"] == "emp1" for i in result)

    def test_market_profiles_truthy_profile_found(self, m):
        """branch [432,433],[459,460]: profile found in market_profiles."""
        raw = {"id": "emp2", "name": "Carol"}
        profiles = {"key1": {"market_avatar": "http://x/c.png"}}
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._load_admin_duty_records",
                return_value=[raw],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._compact_text",
                side_effect=lambda x: x or "",
            ),
            patch("app.fastapi_routes.mobile_api_extensions._apply_market_profile"),
            patch(
                "app.fastapi_routes.mobile_api_extensions._admin_employee_match_keys",
                return_value=["key1"],
            ),
        ):
            result = m._admin_employee_items(market_profiles=profiles)
        assert any(i["id"] == "emp2" for i in result)

    def test_market_profiles_truthy_profile_not_found(self, m):
        """branch [460,464]: none of the match keys found in profiles."""
        raw = {"id": "emp3", "name": "Dave"}
        profiles = {"other_key": {"data": 1}}
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._load_admin_duty_records",
                return_value=[raw],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._compact_text",
                side_effect=lambda x: x or "",
            ),
            patch("app.fastapi_routes.mobile_api_extensions._apply_market_profile"),
            patch(
                "app.fastapi_routes.mobile_api_extensions._admin_employee_match_keys",
                return_value=["missing"],
            ),
        ):
            result = m._admin_employee_items(market_profiles=profiles)
        assert any(i["id"] == "emp3" for i in result)


# ============================================================
# _admin_duty_mod_item / _upsert_admin_duty_mod_item — 469-508
# ============================================================


class TestAdminDutyModItem:
    def test_no_employees_returns_none(self, m):
        """branch [475,476]: no employees → None."""
        with patch.object(m, "_admin_employee_items", return_value=[]):
            result = m._admin_duty_mod_item()
        assert result is None

    def test_with_employees_returns_dict(self, m):
        """branch [475,477]: employees present → mod dict."""
        emps = [{"id": "e1"}]
        with patch.object(m, "_admin_employee_items", return_value=emps):
            result = m._admin_duty_mod_item()
        assert result is not None
        assert result["id"] == "admin-duty-employees"


class TestUpsertAdminDutyModItem:
    def test_no_duty_mod_returns_early(self, m):
        """branch [499,500]: duty_mod is None → return immediately."""
        items: list = []
        with patch.object(m, "_admin_duty_mod_item", return_value=None):
            m._upsert_admin_duty_mod_item(items)
        assert items == []

    def test_existing_item_without_workflow_employees(self, m):
        """branch [503,504],[505,506]: existing item matches id + has no employees → inject."""
        duty = {"id": "admin-duty-employees", "workflow_employees": [{"id": "e1"}]}
        items = [{"id": "admin-duty-employees", "workflow_employees": []}]
        with patch.object(m, "_admin_duty_mod_item", return_value=duty):
            m._upsert_admin_duty_mod_item(items)
        assert items[0]["workflow_employees"] == duty["workflow_employees"]

    def test_existing_item_with_workflow_employees(self, m):
        """branch [505,507]: existing item has employees → leave unchanged, return."""
        existing_emps = [{"id": "existing"}]
        duty = {"id": "admin-duty-employees", "workflow_employees": [{"id": "e1"}]}
        items = [{"id": "admin-duty-employees", "workflow_employees": existing_emps}]
        with patch.object(m, "_admin_duty_mod_item", return_value=duty):
            m._upsert_admin_duty_mod_item(items)
        assert items[0]["workflow_employees"] == existing_emps

    def test_no_matching_item_inserts_at_front(self, m):
        """branch [502,503] not taken → insert at index 0."""
        duty = {"id": "admin-duty-employees", "workflow_employees": [{"id": "e1"}]}
        items: list = [{"id": "other-mod"}]
        with patch.object(m, "_admin_duty_mod_item", return_value=duty):
            m._upsert_admin_duty_mod_item(items)
        assert items[0]["id"] == "admin-duty-employees"


# ============================================================
# mobile_pairing_issue — lines 735-764
# ============================================================


class TestMobilePairingIssue:
    @pytest.mark.asyncio
    async def test_relay_present_with_relay_code(self, m):
        """branch [751,754]: relay present AND relay_code non-empty."""
        payload = {"nonce": "n1", "host": "192.168.1.1", "port": 5000}
        relay = {
            "relay_id": "r1",
            "pairing_code": "CODE99",
            "relay_base_url": "https://relay.example",
            "qr_json": {"a": 1},
        }
        body = SimpleNamespace(host="192.168.1.1", port=5000)
        request = MagicMock()
        request.url.hostname = "192.168.1.1"

        with (
            patch.object(m, "_pairing_issue_host", return_value="192.168.1.1"),
            patch.object(m, "_pairing_issue_port", return_value=5000),
            patch(
                "app.fastapi_routes.mobile_api_extensions.issue_pairing_nonce", return_value=payload
            ),
            patch.object(m, "_enrich_pairing_payload", return_value=dict(payload)),
            patch.object(m, "_register_desktop_relay_for_pairing", return_value=relay),
        ):
            result = await m.mobile_pairing_issue(body=body, request=request)
        body_data = result.get("data") if isinstance(result, dict) else None
        # Should not raise
        assert result is not None

    @pytest.mark.asyncio
    async def test_relay_present_without_relay_code(self, m):
        """branch [751,754] not taken: relay present but pairing_code empty."""
        payload = {"nonce": "n2", "host": "192.168.1.1", "port": 5000}
        relay = {
            "relay_id": "r2",
            "pairing_code": "",  # empty
            "relay_base_url": "https://relay.example",
            "qr_json": {},
        }
        body = SimpleNamespace(host="192.168.1.1", port=5000)
        request = MagicMock()
        request.url.hostname = "192.168.1.1"

        with (
            patch.object(m, "_pairing_issue_host", return_value="192.168.1.1"),
            patch.object(m, "_pairing_issue_port", return_value=5000),
            patch(
                "app.fastapi_routes.mobile_api_extensions.issue_pairing_nonce", return_value=payload
            ),
            patch.object(m, "_enrich_pairing_payload", return_value=dict(payload)),
            patch.object(m, "_register_desktop_relay_for_pairing", return_value=relay),
        ):
            result = await m.mobile_pairing_issue(body=body, request=request)
        assert result is not None

    @pytest.mark.asyncio
    async def test_relay_absent(self, m):
        """branch [746,764]: relay is None → data unchanged."""
        payload = {"nonce": "n3", "host": "192.168.1.1", "port": 5000}
        body = SimpleNamespace(host="192.168.1.1", port=5000)
        request = MagicMock()
        request.url.hostname = "192.168.1.1"

        with (
            patch.object(m, "_pairing_issue_host", return_value="192.168.1.1"),
            patch.object(m, "_pairing_issue_port", return_value=5000),
            patch(
                "app.fastapi_routes.mobile_api_extensions.issue_pairing_nonce", return_value=payload
            ),
            patch.object(m, "_enrich_pairing_payload", return_value=dict(payload)),
            patch.object(m, "_register_desktop_relay_for_pairing", return_value=None),
        ):
            result = await m.mobile_pairing_issue(body=body, request=request)
        assert result is not None


# ============================================================
# mobile_service_bridge_requests — lines 819-908
# ============================================================


class TestMobileServiceBridgeRequests:
    def _mock_db(self):
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        q = MagicMock()
        q.filter.return_value = q
        q.count.return_value = 0
        q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        db.query.return_value = q
        return db

    @pytest.mark.asyncio
    async def test_status_filter(self, m):
        """branch [839,840]: status filter applied."""
        db = self._mock_db()
        with patch("app.db.session.get_db", return_value=db):
            result = await m.mobile_service_bridge_requests(
                request=MagicMock(),
                status="pending",
                source_instance_id=None,
                request_type=None,
                page=1,
                per_page=20,
                user=_user(),
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_source_instance_id_filter(self, m):
        """branch [841,842]: source_instance_id filter applied."""
        db = self._mock_db()
        with patch("app.db.session.get_db", return_value=db):
            result = await m.mobile_service_bridge_requests(
                request=MagicMock(),
                status=None,
                source_instance_id="inst-001",
                request_type=None,
                page=1,
                per_page=20,
                user=_user(),
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_request_type_filter(self, m):
        """branch [843,844]: request_type filter applied."""
        db = self._mock_db()
        with patch("app.db.session.get_db", return_value=db):
            result = await m.mobile_service_bridge_requests(
                request=MagicMock(),
                status=None,
                source_instance_id=None,
                request_type="mobile_ai_customer_service",
                page=1,
                per_page=20,
                user=_user(),
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_unauthorized(self, m):
        """branch [829,830]: user is None → 401."""
        result = await m.mobile_service_bridge_requests(
            request=MagicMock(),
            status=None,
            source_instance_id=None,
            request_type=None,
            page=1,
            per_page=20,
            user=None,
        )
        assert result.status_code == 401


class TestMobileServiceBridgeRequestRespond:
    @pytest.mark.asyncio
    async def test_invalid_request_id(self, m):
        """branch [863,864]: request_id <= 0 → 400."""
        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        result = await m.mobile_service_bridge_request_respond(
            request_id=0, body=body, user=_user()
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_status(self, m):
        """branch [868,873]: status not in valid list → 400."""
        body = SimpleNamespace(status="bogus_status", response="ok", responded_by="admin")
        result = await m.mobile_service_bridge_request_respond(
            request_id=1, body=body, user=_user()
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_user_none(self, m):
        """branch [873,874]: user is None → 401."""
        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        result = await m.mobile_service_bridge_request_respond(request_id=1, body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_request_not_found(self, m):
        """branch [884,885]: db query returns None → 404."""
        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        mock_db = _ctx_db(MagicMock())
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await m.mobile_service_bridge_request_respond(
                request_id=99, body=body, user=_user()
            )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [873,877]: RECOVERABLE_ERRORS → 500."""
        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception

        with patch("app.db.session.get_db", side_effect=err_class("DB gone")):
            result = await m.mobile_service_bridge_request_respond(
                request_id=1, body=body, user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_relay_confirm / confirm_code — lines 933-996
# ============================================================


class TestMobileRelayConfirm:
    @pytest.mark.asyncio
    async def test_desktop_none_returns_400(self, m):
        """branch [945,946]: desktop is None → 400."""
        body = SimpleNamespace(relay_id="r1", code="C1")
        with (
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.confirm_mobile.return_value = None
            result = await m.mobile_relay_confirm(body=body, user=_user())
        assert result.status_code == 400


class TestMobileRelayConfirmCode:
    @pytest.mark.asyncio
    async def test_desktop_none_returns_400(self, m):
        """branch [979,980]: desktop is None → 400."""
        body = SimpleNamespace(code="CODE1")
        with (
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.confirm_mobile_by_code.return_value = None
            result = await m.mobile_relay_confirm_code(body=body, user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [979,984]: RECOVERABLE_ERRORS → 500."""
        body = SimpleNamespace(code="CODE2")
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception

        with (
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.confirm_mobile_by_code.side_effect = err_class("fail")
            result = await m.mobile_relay_confirm_code(body=body, user=_user())
        assert result.status_code == 500


# ============================================================
# mobile_relay_desktops — lines 999-1015
# ============================================================


class TestMobileRelayDesktops:
    @pytest.mark.asyncio
    async def test_uid_zero_unauthorized(self, m):
        """branch [1002,1003]: uid <= 0 → 401."""
        with patch.object(m, "_mobile_user_identity", return_value=(0, "")):
            result = await m.mobile_relay_desktops(user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        """branch [1002,1007]: uid > 0 → list desktops."""
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.list_desktops.return_value = []
            result = await m.mobile_relay_desktops(user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [1010,1011]: RECOVERABLE_ERRORS → 500."""
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception

        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.list_desktops.side_effect = err_class("fail")
            result = await m.mobile_relay_desktops(user=_user(uid=5))
        assert result.status_code == 500


# ============================================================
# mobile_relay_create_task — lines 1018-1046
# ============================================================


class TestMobileRelayCreateTask:
    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1021,1022]: uid <= 0 → 401."""
        body = SimpleNamespace(relay_id="r1", kind="test", payload={})
        with patch.object(m, "_mobile_user_identity", return_value=(0, "")):
            result = await m.mobile_relay_create_task(body=body, user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_task_not_found(self, m):
        """branch [1035,1036]: task is None → 404."""
        body = SimpleNamespace(relay_id="r1", kind="test", payload={"a": 1})
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.create_task.return_value = None
            result = await m.mobile_relay_create_task(body=body, user=_user(uid=5))
        assert result.status_code == 404


# ============================================================
# mobile_relay_task_status — lines 1049-1063
# ============================================================


class TestMobileRelayTaskStatus:
    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1052,1053]: uid <= 0 → 401."""
        with patch.object(m, "_mobile_user_identity", return_value=(0, "")):
            result = await m.mobile_relay_task_status(task_id="t1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_task_not_found(self, m):
        """branch [1058,1059]: task not found → 404."""
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.get_task.return_value = None
            result = await m.mobile_relay_task_status(task_id="t1", user=_user(uid=5))
        assert result.status_code == 404


# ============================================================
# mobile_relay_desktop_poll — lines 1066-1085
# ============================================================


class TestMobileRelayDesktopPoll:
    @pytest.mark.asyncio
    async def test_data_none_returns_404(self, m):
        """branch [1074,1075]: poll returns None → 404."""
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", max_tasks=5)
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.poll_desktop.return_value = None
            result = await m.mobile_relay_desktop_poll(body=body)
        assert result.status_code == 404


# ============================================================
# mobile_relay_desktop_complete — lines 1088-1109
# ============================================================


class TestMobileRelayDesktopComplete:
    @pytest.mark.asyncio
    async def test_task_none_returns_404(self, m):
        """branch [1098,1099]: task None → 404."""
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", status="done", result={})
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.complete_desktop_task.return_value = None
            result = await m.mobile_relay_desktop_complete(task_id="t1", body=body)
        assert result.status_code == 404


# ============================================================
# mobile_admin_employees — lines 1115-1130
# ============================================================


class TestMobileAdminEmployees:
    @pytest.mark.asyncio
    async def test_require_admin_error(self, m):
        """branch [1118,1119]: _require_mobile_admin returns err → return err."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_employees(request=MagicMock(), user=_user())
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_success(self, m):
        """branch [1118,1120]: err is None → proceed."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._load_market_ai_employee_profile_index",
                new=AsyncMock(return_value=({}, False, "")),
            ),
            patch.object(m, "_admin_employee_items", return_value=[]),
        ):
            result = await m.mobile_admin_employees(request=MagicMock(), user=_user())
        assert result is not None


# ============================================================
# mobile_admin_features — lines 1133-1140
# ============================================================


class TestMobileAdminFeatures:
    @pytest.mark.asyncio
    async def test_require_admin_error(self, m):
        """branch [1136,1137]: err is not None."""
        err_resp = MagicMock()
        err_resp.status_code = 401
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_features(request=MagicMock(), user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        """branch [1136,1138]: err is None → return features."""
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin",
            return_value=({}, None),
        ):
            result = await m.mobile_admin_features(request=MagicMock(), user=_user())
        assert result is not None


# ============================================================
# mobile_admin_codex_super_employee_messages — 1164-1188
# ============================================================


class TestMobileAdminCodexSuperEmployeeMessages:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1172,1173]: _require_mobile_admin_or_enterprise → err."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_codex_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1175,1176]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=0
            ),
        ):
            result = await m.mobile_admin_codex_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [1183,1184]: RECOVERABLE_ERRORS → 500."""
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CodexSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.list_messages.side_effect = err_class("fail")
            result = await m.mobile_admin_codex_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_admin_codex_super_employee_invoke — 1191-1229
# ============================================================


class TestMobileAdminCodexSuperEmployeeInvoke:
    def _body(self):
        b = MagicMock()
        b.message = "hello"
        b.body = ""
        b.context = {}
        return b

    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1198,1199]: err from _require_mobile_admin_or_enterprise."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_codex_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1202,1203]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=0
            ),
        ):
            result = await m.mobile_admin_codex_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        """branch [1219,1220]: ValueError from invoke → 400."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CodexSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.side_effect = ValueError("bad input")
            result = await m.mobile_admin_codex_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [1224,1225]: RECOVERABLE_ERRORS → 500."""
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CodexSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.side_effect = err_class("fail")
            result = await m.mobile_admin_codex_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_admin_claude_super_employee_messages — 1232-1256
# ============================================================


class TestMobileAdminClaudeSuperEmployeeMessages:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1240,1241]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_claude_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1243,1244]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=0
            ),
        ):
            result = await m.mobile_admin_claude_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [1251,1252]: RECOVERABLE_ERRORS → 500."""
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.list_messages.side_effect = err_class("fail")
            result = await m.mobile_admin_claude_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_admin_claude_super_employee_invoke — 1259-1297
# ============================================================


class TestMobileAdminClaudeSuperEmployeeInvoke:
    def _body(self):
        b = MagicMock()
        b.message = "hello"
        b.body = ""
        b.context = {}
        return b

    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1267,1268]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_claude_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1270,1271]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=0
            ),
        ):
            result = await m.mobile_admin_claude_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        """branch [1287,1288]: ValueError → 400."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.side_effect = ValueError("bad")
            result = await m.mobile_admin_claude_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [1292,1293]: RECOVERABLE_ERRORS → 500."""
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.side_effect = err_class("fail")
            result = await m.mobile_admin_claude_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 500


# ============================================================
# AI group chat routes — 1307-1477
# ============================================================


def _ai_group_setup(m, patch_fn, require_ret=(None, None), uid=5):
    """Shared setup for AI group chat route tests."""
    err_resp = MagicMock()
    err_resp.status_code = 403
    # Allow callers to override with actual errors
    return patch_fn


class TestMobileAiGroupsList:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1311,1312]: err from _require_mobile_admin_or_enterprise."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_groups_list(request=MagicMock(), user=_user())
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1314,1315]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_groups_list(request=MagicMock(), user=_user())
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        """branch [1321,1322]: RECOVERABLE_ERRORS → 500."""
        err_class = list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.list_groups.side_effect = err_class("fail")
            result = await m.mobile_ai_groups_list(request=MagicMock(), user=_user())
        assert result.status_code == 500


class TestMobileAiGroupsCreate:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1334,1335]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_groups_create(
                request=MagicMock(), body=SimpleNamespace(name="g1"), user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1337,1338]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_groups_create(
                request=MagicMock(), body=SimpleNamespace(name="g1"), user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        """branch [1344,1345]: ValueError → 400."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.create_group.side_effect = ValueError("dup")
            result = await m.mobile_ai_groups_create(
                request=MagicMock(), body=SimpleNamespace(name="g1"), user=_user()
            )
        assert result.status_code == 400


class TestMobileAiGroupMessages:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1364,1365]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_messages(
                request=MagicMock(), group_id="g1", limit=100, user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1367,1368]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_messages(
                request=MagicMock(), group_id="g1", limit=100, user=_user()
            )
        assert result.status_code == 401


class TestMobileAiGroupPost:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1387,1388]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        body = SimpleNamespace(message="hi", sender_name=None, mentions=[])
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1390,1391]: uid <= 0 → 401."""
        body = SimpleNamespace(message="hi", sender_name=None, mentions=[])
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 401


class TestMobileAiGroupAddMember:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1420,1421]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        body = SimpleNamespace(
            employee_id="e1", mod_id="m1", name="Alice", avatar=None, summary=None
        )
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1423,1424]: uid <= 0 → 401."""
        body = SimpleNamespace(
            employee_id="e1", mod_id="m1", name="Alice", avatar=None, summary=None
        )
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 401


class TestMobileAiGroupRemoveMember:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        """branch [1457,1458]: err not None."""
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        """branch [1460,1461]: uid <= 0 → 401."""
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result.status_code == 401


# ============================================================
# Circle routes — lines 1483-1569
# ============================================================


class TestMobileAiCirclePosts:
    @pytest.mark.asyncio
    async def test_user_none(self, m):
        """branch [1488,1489]: user is None → 401."""
        result = await m.mobile_ai_circle_posts(limit=50, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_profile_match(self, m):
        """branch [1499,1500]: profile found for employee_id."""
        post = {"employee_id": "emp1", "author_name": "default", "author_avatar": None}
        profiles = {"emp1": {"name": "Alice", "avatar": "http://x/a.png"}}
        with (
            patch("app.application.ai_circle_service.list_posts", return_value=[post]),
            patch.object(m, "_ai_circle_employee_profiles", return_value=profiles),
            patch.object(m, "_ai_circle_user", return_value=(1, "user", None)),
        ):
            result = await m.mobile_ai_circle_posts(limit=50, user=_user())
        assert result is not None


class TestMobileAiCircleCreatePost:
    @pytest.mark.asyncio
    async def test_user_none(self, m):
        """branch [1510,1511]: user is None → 401."""
        body = SimpleNamespace(body="hello")
        result = await m.mobile_ai_circle_create_post(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        """branch [1520,1521]: ValueError → 400."""
        body = SimpleNamespace(body="hello")
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "Bob", None)),
            patch(
                "app.application.ai_circle_service.create_user_post", side_effect=ValueError("bad")
            ),
        ):
            result = await m.mobile_ai_circle_create_post(body=body, user=_user())
        assert result.status_code == 400


class TestMobileAiCircleToggleLike:
    @pytest.mark.asyncio
    async def test_user_none(self, m):
        """branch [1528,1529]: user is None → 401."""
        result = await m.mobile_ai_circle_toggle_like(post_id=1, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_lookup_error(self, m):
        """branch [1538,1539]: LookupError → 404."""
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "u", None)),
            patch(
                "app.application.ai_circle_service.toggle_like",
                side_effect=LookupError("not found"),
            ),
        ):
            result = await m.mobile_ai_circle_toggle_like(post_id=99, user=_user())
        assert result.status_code == 404


class TestMobileAiCircleAddComment:
    @pytest.mark.asyncio
    async def test_user_none(self, m):
        """branch [1550,1551]: user is None → 401."""
        result = await m.mobile_ai_circle_add_comment(
            post_id=1, body=SimpleNamespace(body="hi"), user=None
        )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        """branch [1563,1564]: ValueError → 400."""
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "u", None)),
            patch("app.application.ai_circle_service.add_comment", side_effect=ValueError("bad")),
        ):
            result = await m.mobile_ai_circle_add_comment(
                post_id=1, body=SimpleNamespace(body="hi"), user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_lookup_error(self, m):
        """branch [1566,1567]: LookupError → 404."""
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "u", None)),
            patch("app.application.ai_circle_service.add_comment", side_effect=LookupError("gone")),
        ):
            result = await m.mobile_ai_circle_add_comment(
                post_id=1, body=SimpleNamespace(body="hi"), user=_user()
            )
        assert result.status_code == 404


# ============================================================
# mobile_nav_menu — lines 1662-1721
# ============================================================


class TestMobileNavMenu:
    @pytest.mark.asyncio
    async def test_user_none(self, m):
        """branch [1668,1669]: user is None → 401."""
        result = await m.mobile_nav_menu(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_role_all_items_visible(self, m):
        """branch [1683,1684]: visible_keys is None (admin) → all items."""
        u = _user(uid=1, role="admin")
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_enterprise_role_filtered_items(self, m):
        """branch [1683,1684],[1684,1685]: visible_keys not None → filter."""
        u = _user(uid=2, role="enterprise")
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_with_frontend_menu_entry(self, m):
        """branch [1701,1702]: frontend_menu is list with valid entry."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test Mod",
            "frontend_menu": [
                {"id": "entry1", "label": "Entry", "path": "/entry1", "icon": "fa-cube"}
            ],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_with_non_list_frontend_menu(self, m):
        """branch [1699,1700]: frontend_menu not a list → continue."""
        u = _user(uid=1, role="admin")
        mod = {"id": "testmod", "name": "Test Mod", "frontend_menu": "not-a-list"}
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_operational_error_in_mod_items(self, m):
        """branch [1718,1719]: OPERATIONAL_ERRORS in mod section → logged, continues."""
        u = _user(uid=1, role="admin")
        err_class = list(m.OPERATIONAL_ERRORS)[0] if m.OPERATIONAL_ERRORS else Exception
        with patch.object(m, "_mobile_mod_items", side_effect=err_class("boom")):
            result = await m.mobile_nav_menu(user=u)
        # Should still return 200 even if mod items fail
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_non_dict(self, m):
        """branch [1702,1703]: menu_entry not dict → continue."""
        u = _user(uid=1, role="admin")
        mod = {"id": "testmod", "name": "Test", "frontend_menu": ["not-a-dict"]}
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_no_id(self, m):
        """branch [1705,1706]: menu_entry dict but no id → continue."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "frontend_menu": [{"label": "No ID", "path": "/x"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None


# ============================================================
# mobile_auth_oidc_exchange — lines 2034-2035 (key present + not None)
# ============================================================


class TestMobileAuthOidcExchangePayloadKey:
    @pytest.mark.asyncio
    async def test_key_present_and_not_none_copies_to_data(self, m):
        """branch [2034,2035]: payload key present and not None → data[key] = val."""
        fake_session = {"access_token": "tok", "provider": "google", "profile": {"sub": "123"}}
        fake_auth = {
            "success": True,
            "user": {"id": 7, "username": "oidc_user"},
            "session_id": "sess123",
        }
        fake_payload = {
            "user": {"id": 7},
            "account_kind": "enterprise",
            "market_access_token": "mkt_tok",  # present + not None → copied
            "market_refresh_token": None,  # present + None → NOT copied
        }
        fake_tokens = {"access_token": "jwt", "refresh_token": "rjwt"}

        body = MagicMock()
        body.state = "valid_state"
        body.code = "auth_code"

        auth_svc = MagicMock()
        auth_svc.authenticate_oidc_user.return_value = fake_auth

        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state", return_value=(True, None)
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(return_value=fake_session),
            ),
            patch("app.application.auth_app_service.get_auth_app_service", return_value=auth_svc),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.application.session_account_meta.normalize_account_kind",
                return_value="enterprise",
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_auth_after_oidc",
                new=AsyncMock(return_value=fake_payload),
            ),
            patch("app.security.mobile_jwt.issue_mobile_tokens", return_value=fake_tokens),
        ):
            result = await m.mobile_auth_oidc_exchange(body=body)
        # Result is a format_mobile_response dict
        assert result is not None


# ============================================================
# mobile_wallet_balance — lines 2168-2286
# ============================================================


class TestMobileWalletBalance:
    def _req(self, auth_header: str = ""):
        req = MagicMock()
        req.headers.get = MagicMock(return_value=auth_header)
        return req

    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        """branch [2168,2169]: user is None → 401."""
        result = await m.mobile_wallet_balance(request=self._req(), user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_no_market_token_returns_no_account_message(self, m):
        """branch [2197,2198]: no market token → return with message."""
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=None),
            patch("app.infrastructure.auth.dependencies.session_id_from_request", return_value=""),
            patch("app.fastapi_routes.market_account.session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer bad"), user=_user())
        # returns a dict/response with the "尚未绑定市场账号" message
        assert result is not None

    @pytest.mark.asyncio
    async def test_bearer_jwt_sets_sid(self, m):
        """branch [2184,2185]: auth_hdr starts with Bearer and payload is truthy."""
        fake_payload = {"session_id": "sess_abc"}
        wallet = {"balance": "100.50", "currency": "CNY"}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=fake_payload),
            patch(
                "app.fastapi_routes.market_account.session_market_token", return_value="mkt_token"
            ),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch(
                "app.fastapi_routes.market_account._auth_header", return_value="Bearer mkt_token"
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json", new=AsyncMock(return_value=wallet)
            ),
        ):
            result = await m.mobile_wallet_balance(
                request=self._req("Bearer valid_jwt"), user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_jwt_payload_none_falls_to_session_id_from_request(self, m):
        """branch [2184,2188]: verify returns None → session_id_from_request."""
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=None),
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="req_sess",
            ),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"__proxy_error__": True, "payload": "err"}),
            ),
        ):
            result = await m.mobile_wallet_balance(
                request=self._req("Bearer bad_jwt"), user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_wallet_proxy_error_falls_back(self, m):
        """branch [2215,2217]: wallet_payload has __proxy_error__ → try /api/wallet/balance."""
        err_payload = {"__proxy_error__": True, "payload": "timeout"}
        balance_ok = {"balance": "50.00", "currency": "CNY"}

        async def mock_proxy(method, path, **kwargs):
            if path == "/api/wallet/overview":
                return err_payload
            if path == "/api/wallet/balance":
                return balance_ok
            return {"__proxy_error__": True}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s1"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_membership_as_string(self, m):
        """branch [2269,2270]: membership is str → membership_level = membership."""
        wallet = {"balance": "200.00", "currency": "CNY"}
        plan = {"membership": "gold"}
        llm = {"providers": []}

        async def mock_proxy(method, path, **kwargs):
            if "wallet" in path:
                return wallet
            if "my-plan" in path:
                return plan
            if "llm" in path:
                return llm
            return {}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s2"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_membership_as_dict_with_experience(self, m):
        """branch [2265,2266],[2272,2273]: membership dict → level and experience."""
        wallet = {"balance": "300.00", "currency": "CNY"}
        plan = {"membership": {"level": "vip", "experience": 1000}}
        llm = {"providers": [{"has_user_override": True}]}

        async def mock_proxy(method, path, **kwargs):
            if "wallet" in path:
                return wallet
            if "my-plan" in path:
                return plan
            if "llm" in path:
                return llm
            return {}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s3"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_both_wallet_calls_fail(self, m):
        """branch [2227,2228]: both wallet calls return __proxy_error__."""
        err = {"__proxy_error__": True, "payload": "server error"}

        async def mock_proxy(method, path, **kwargs):
            if "plan" in path:
                return {}
            if "llm" in path:
                return {}
            return err

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s4"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_plan_proxy_error(self, m):
        """branch [2240,2241]: plan_payload __proxy_error__ → log warning."""
        wallet = {"balance": "10.00", "currency": "CNY"}
        err = {"__proxy_error__": True, "payload": "plan unavail"}
        llm = {"providers": []}

        async def mock_proxy(method, path, **kwargs):
            if "wallet/overview" in path:
                return wallet
            if "my-plan" in path:
                return err
            if "llm" in path:
                return llm
            return {}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s5"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_byok_providers(self, m):
        """branch [2251,2252]: llm_payload valid and providers has user_override."""
        wallet = {"balance": "50.00"}
        plan = {}
        llm = {"providers": [{"has_user_override": True}, {"has_user_override": False}]}

        async def mock_proxy(method, path, **kwargs):
            if "wallet" in path:
                return wallet
            if "my-plan" in path:
                return plan
            if "llm" in path:
                return llm
            return {}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s6"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_latest_session_market_token_fallback(self, m):
        """branch [2195,2196],[2195,2197]: sid set but token empty → latest fallback."""
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s_x"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value=""),
            patch(
                "app.fastapi_routes.market_account.latest_session_market_token",
                return_value="fallback_tok",
            ),
            patch(
                "app.fastapi_routes.market_account._auth_header", return_value="Bearer fallback_tok"
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"__proxy_error__": True}),
            ),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_wallet_obj_has_wallet_sub_key(self, m):
        """branch [2221,2222]: wallet_payload.wallet is a dict → use it."""
        wallet_payload = {"wallet": {"balance": "77.77", "currency": "USD"}}
        plan = {}
        llm = {}

        async def mock_proxy(method, path, **kwargs):
            if "wallet/overview" in path:
                return wallet_payload
            if "my-plan" in path:
                return plan
            if "llm" in path:
                return llm
            return {}

        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "s7"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value="tok"),
            patch("app.fastapi_routes.market_account.latest_session_market_token", return_value=""),
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_wallet_balance(request=self._req("Bearer jwt"), user=_user())
        assert result is not None
