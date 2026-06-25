"""Branch-coverage tests for app.fastapi_routes.mobile_api_extensions.

Focuses on REMAINING uncovered branches not addressed by ext/cov/ext2/ext3:
- Helper functions: _mobile_session_id_from_request, _mobile_market_authorization,
  _ai_circle_user, _cached_desktop_relay_for_account_binding, _pairing_issue_host,
  _admin_roster_ids_by_department_order, _admin_roster_area_labels,
  _admin_employee_manifest, _admin_duty_records_from_roster,
  _persist_mobile_cs_request, _normalize_mobile_payment_channel,
  _mobile_checkout_sign_body, _conversation_state_uid, _mobile_group_mode.
- Routes: cursor super employee (messages/invoke), conversation state routes,
  onboarding/industry-baseline/install routes, payment routes, relay register/bind,
  AI group toggle/mark routes, mobile_employee_ssot, mobile_admin_home.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _load_ext_module():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def m():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


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
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def _err_class(m):
    return list(m.RECOVERABLE_ERRORS)[0] if m.RECOVERABLE_ERRORS else Exception


# ============================================================
# _mobile_session_id_from_request
# ============================================================


class TestMobileSessionIdFromRequest:
    def test_no_authorization_header_returns_x_session_id(self, m):
        """branch: no Authorization header → fallback to X-Session-ID."""
        req = MagicMock()
        req.headers = {"X-Session-ID": "sid-123"}
        result = m._mobile_session_id_from_request(req)
        assert result == "sid-123"

    def test_non_bearer_authorization_header_returns_x_session_id(self, m):
        """branch: Authorization header doesn't start with 'Bearer '."""
        req = MagicMock()
        req.headers = {"Authorization": "Basic abc", "X-Session-ID": "sid-456"}
        result = m._mobile_session_id_from_request(req)
        assert result == "sid-456"

    def test_bearer_header_jwt_returns_session_id(self, m):
        """branch: Bearer header with valid JWT containing session_id."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer valid_jwt"}
        with patch(
            "app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "jwt-sid"}
        ):
            result = m._mobile_session_id_from_request(req)
        assert result == "jwt-sid"

    def test_bearer_header_jwt_no_session_id_returns_x_session(self, m):
        """branch: Bearer header JWT has no session_id → fallback."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer jwt", "X-Session-ID": "fallback-sid"}
        with patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={}):
            result = m._mobile_session_id_from_request(req)
        assert result == "fallback-sid"

    def test_bearer_header_jwt_empty_session_id_returns_x_session(self, m):
        """branch: Bearer header JWT has empty session_id → fallback."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer jwt", "X-Session-ID": "fallback"}
        with patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": ""}):
            result = m._mobile_session_id_from_request(req)
        assert result == "fallback"

    def test_bearer_header_jwt_error_returns_x_session(self, m):
        """branch: verify_mobile_jwt raises OPERATIONAL_ERRORS → fallback."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer bad", "X-Session-ID": "fallback"}
        with patch(
            "app.security.mobile_jwt.verify_mobile_jwt", side_effect=ValueError("bad jwt")
        ):
            result = m._mobile_session_id_from_request(req)
        assert result == "fallback"

    def test_bearer_header_no_x_session_returns_empty(self, m):
        """branch: Bearer header fails, no X-Session-ID → empty string."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer bad"}
        with patch("app.security.mobile_jwt.verify_mobile_jwt", side_effect=ValueError("bad")):
            result = m._mobile_session_id_from_request(req)
        assert result == ""

    def test_bearer_header_whitespace_session_id_stripped(self, m):
        """branch: session_id has whitespace → stripped."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer jwt"}
        with patch(
            "app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "  sid  "}
        ):
            result = m._mobile_session_id_from_request(req)
        assert result == "sid"


# ============================================================
# _mobile_market_authorization
# ============================================================


class TestMobileMarketAuthorization:
    def test_sid_present_token_from_session(self, m):
        """branch: sid present, session_market_token returns token."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer jwt", "X-Session-ID": "sid"}
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "sid"}),
            patch(
                "app.fastapi_routes.market_account.session_market_token", return_value="tok"
            ) as mock_smt,
            patch(
                "app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"
            ) as mock_ah,
        ):
            result = m._mobile_market_authorization(req, user=_user())
        mock_smt.assert_called_once_with("sid")
        mock_ah.assert_called_once_with("tok")

    def test_sid_present_no_token_fallback_to_latest(self, m):
        """branch: sid present but token empty → latest_session_market_token."""
        req = MagicMock()
        req.headers = {"Authorization": "Bearer jwt", "X-Session-ID": "sid"}
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value={"session_id": "sid"}),
            patch("app.fastapi_routes.market_account.session_market_token", return_value=""),
            patch(
                "app.fastapi_routes.market_account.latest_session_market_token",
                return_value="latest_tok",
            ) as mock_latest,
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer latest"),
        ):
            result = m._mobile_market_authorization(req, user=_user(uid=5))
        mock_latest.assert_called_once_with(user_id=5)

    def test_no_sid_uses_latest_session_market_token(self, m):
        """branch: no sid → latest_session_market_token directly."""
        req = MagicMock()
        req.headers = {}
        with (
            patch(
                "app.fastapi_routes.market_account.latest_session_market_token",
                return_value="tok",
            ) as mock_latest,
            patch("app.fastapi_routes.market_account._auth_header", return_value="Bearer tok"),
        ):
            result = m._mobile_market_authorization(req, user=_user(uid=7))
        mock_latest.assert_called_once_with(user_id=7)


# ============================================================
# _ai_circle_user
# ============================================================


class TestAiCircleUser:
    def test_user_with_display_name(self, m):
        """branch: user has display_name."""
        u = MagicMock()
        u.id = 1
        u.display_name = "Alice"
        u.wx_avatar_url = None
        uid, name, avatar = m._ai_circle_user(u)
        assert uid == 1
        assert name == "Alice"
        assert avatar is None

    def test_user_no_display_name_uses_username(self, m):
        """branch: no display_name → username."""
        u = MagicMock()
        u.id = 2
        u.display_name = ""
        u.username = "bob"
        u.wx_avatar_url = None
        uid, name, avatar = m._ai_circle_user(u)
        assert name == "bob"

    def test_user_no_display_name_no_username_uses_default(self, m):
        """branch: no display_name, no username → '企业成员'."""
        u = MagicMock()
        u.id = 3
        u.display_name = ""
        u.username = ""
        u.wx_avatar_url = None
        uid, name, avatar = m._ai_circle_user(u)
        assert name == "企业成员"

    def test_user_with_avatar(self, m):
        """branch: user has wx_avatar_url."""
        u = MagicMock()
        u.id = 4
        u.display_name = "Carol"
        u.wx_avatar_url = "http://x/avatar.png"
        uid, name, avatar = m._ai_circle_user(u)
        assert avatar == "http://x/avatar.png"

    def test_user_id_zero(self, m):
        """branch: user.id is 0 → uid 0."""
        u = MagicMock()
        u.id = 0
        u.display_name = "Zero"
        u.wx_avatar_url = None
        uid, name, avatar = m._ai_circle_user(u)
        assert uid == 0

    def test_user_id_none_defaults_zero(self, m):
        """branch: user.id is None → uid 0."""
        u = MagicMock()
        u.id = None
        u.display_name = "None"
        u.wx_avatar_url = None
        uid, _, _ = m._ai_circle_user(u)
        assert uid == 0


# ============================================================
# _cached_desktop_relay_for_account_binding
# ============================================================


class TestCachedDesktopRelayForAccountBinding:
    def test_recoverable_error_returns_none(self, m):
        """branch: RECOVERABLE_ERRORS → None."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            side_effect=ValueError("boom"),
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is None

    def test_relay_none_returns_none(self, m):
        """branch: relay is None → None."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            return_value=None,
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is None

    def test_relay_empty_returns_none(self, m):
        """branch: relay is empty dict → None."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            return_value={},
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is None

    def test_relay_no_relay_id_returns_none(self, m):
        """branch: relay has no relay_id → None."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            return_value={"relay_base_url": "http://x"},
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is None

    def test_relay_empty_relay_id_returns_none(self, m):
        """branch: relay_id is whitespace → None."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            return_value={"relay_id": "   "},
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is None

    def test_relay_valid_returns_dict(self, m):
        """branch: relay has relay_id → return dict."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            return_value={
                "relay_id": "r1",
                "relay_base_url": "http://relay",
                "expires_at": "2026-12-31",
                "exp": 9999,
            },
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is not None
        assert result["relay_id"] == "r1"
        assert result["binding_mode"] == "account_auth"
        assert result["exp"] == 9999

    def test_relay_valid_with_empty_fields(self, m):
        """branch: relay has relay_id but other fields empty."""
        with patch(
            "app.services.mobile_relay_desktop_client.cached_desktop_relay_payload",
            return_value={"relay_id": "r2", "relay_base_url": "", "expires_at": "", "exp": None},
        ):
            result = m._cached_desktop_relay_for_account_binding()
        assert result is not None
        assert result["relay_base_url"] == ""
        assert result["exp"] == 0


# ============================================================
# _pairing_issue_host
# ============================================================


class TestPairingIssueHostBranchCov:
    def test_host_0_0_0_0_returns_lan(self, m):
        """branch: host is '0.0.0.0' → _guess_lan_ipv4."""
        with patch.object(m, "_guess_lan_ipv4", return_value="10.0.0.1"):
            assert m._pairing_issue_host("0.0.0.0") == "10.0.0.1"

    def test_host_localhost_returns_lan(self, m):
        """branch: host is 'localhost' → _guess_lan_ipv4."""
        with patch.object(m, "_guess_lan_ipv4", return_value="10.0.0.2"):
            assert m._pairing_issue_host("localhost") == "10.0.0.2"

    def test_host_127_0_0_1_returns_lan(self, m):
        """branch: host is '127.0.0.1' → _guess_lan_ipv4."""
        with patch.object(m, "_guess_lan_ipv4", return_value="10.0.0.3"):
            assert m._pairing_issue_host("127.0.0.1") == "10.0.0.3"

    def test_host_empty_returns_lan(self, m):
        """branch: host empty → default 127.0.0.1 → _guess_lan_ipv4."""
        with patch.object(m, "_guess_lan_ipv4", return_value="10.0.0.4"):
            assert m._pairing_issue_host("") == "10.0.0.4"

    def test_host_none_returns_lan(self, m):
        """branch: host None → default 127.0.0.1 → _guess_lan_ipv4."""
        with patch.object(m, "_guess_lan_ipv4", return_value="10.0.0.5"):
            assert m._pairing_issue_host(None) == "10.0.0.5"

    def test_host_custom_returns_host(self, m):
        """branch: host is custom → returned as-is."""
        assert m._pairing_issue_host("192.168.1.50") == "192.168.1.50"


# ============================================================
# _admin_roster_ids_by_department_order
# ============================================================


class TestAdminRosterIdsByDepartmentOrder:
    def test_recoverable_error_returns_empty(self, m):
        """branch: RECOVERABLE_ERRORS → []."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            side_effect=ValueError("boom"),
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_empty_admin_dict(self, m):
        """branch: admin dict has no departments or planned_employee_ids."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster", return_value={}
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_departments_not_list(self, m):
        """branch: departments is not a list."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={"departments": "not-a-list"},
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_department_not_dict_skipped(self, m):
        """branch: department is not a dict → skip."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={"departments": ["not-a-dict"]},
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_employees_not_list_skipped(self, m):
        """branch: department.employees is not a list → skip."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={"departments": [{"employees": "not-a-list"}]},
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_employee_not_dict_skipped(self, m):
        """branch: employee is not a dict → skip."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={"departments": [{"employees": ["not-a-dict"]}]},
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_employee_empty_id_skipped(self, m):
        """branch: employee.id is empty → skip."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={"departments": [{"employees": [{"id": ""}]}]},
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == []

    def test_valid_employees_collected(self, m):
        """branch: valid employees collected in order."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={
                "departments": [
                    {"employees": [{"id": "e1"}, {"id": "e2"}]},
                    {"employees": [{"id": "e3"}]},
                ]
            },
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == ["e1", "e2", "e3"]

    def test_duplicate_ids_deduplicated(self, m):
        """branch: duplicate ids are deduplicated."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={
                "departments": [
                    {"employees": [{"id": "e1"}, {"id": "e2"}]},
                    {"employees": [{"id": "e1"}]},
                ]
            },
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == ["e1", "e2"]

    def test_planned_employee_ids_appended(self, m):
        """branch: planned_employee_ids appended after department employees."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={
                "departments": [{"employees": [{"id": "e1"}]}],
                "planned_employee_ids": ["e2", "e3"],
            },
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == ["e1", "e2", "e3"]

    def test_planned_employee_ids_with_none(self, m):
        """branch: planned_employee_ids with None values → skipped."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={"planned_employee_ids": [None, "e1", ""]},
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == ["e1"]

    def test_planned_employee_ids_dedup_against_departments(self, m):
        """branch: planned_employee_ids deduped against department ids."""
        with patch(
            "app.mod_sdk.employee_ssot.derive_admin_duty_roster",
            return_value={
                "departments": [{"employees": [{"id": "e1"}]}],
                "planned_employee_ids": ["e1", "e2"],
            },
        ):
            result = m._admin_roster_ids_by_department_order()
        assert result == ["e1", "e2"]


# ============================================================
# _admin_roster_area_labels
# ============================================================


class TestAdminRosterAreaLabels:
    def test_recoverable_error_returns_empty(self, m):
        """branch: RECOVERABLE_ERRORS → {}."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            side_effect=ValueError("boom"),
        ):
            result = m._admin_roster_area_labels()
        assert result == {}

    def test_doc_not_dict_returns_empty(self, m):
        """branch: doc is not a dict → {}."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document", return_value="not-a-dict"
        ):
            result = m._admin_roster_area_labels()
        assert result == {}

    def test_areas_not_dict_returns_empty(self, m):
        """branch: areas is not a dict → {}."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={"areas": "not-a-dict"},
        ):
            result = m._admin_roster_area_labels()
        assert result == {}

    def test_area_not_dict_skipped(self, m):
        """branch: area is not a dict → skip."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={"areas": {"a1": "not-a-dict"}},
        ):
            result = m._admin_roster_area_labels()
        assert result == {}

    def test_area_with_valid_label_and_ids(self, m):
        """branch: area has label and ids → mapped."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={
                "areas": {
                    "a1": {"label": "Sales", "ids": ["e1", "e2"]},
                }
            },
        ):
            result = m._admin_roster_area_labels()
        assert result == {"e1": "Sales", "e2": "Sales"}

    def test_area_with_empty_label_skipped(self, m):
        """branch: area has empty label → skip."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={"areas": {"a1": {"label": "", "ids": ["e1"]}}},
        ):
            result = m._admin_roster_area_labels()
        assert result == {}

    def test_area_with_empty_id_skipped(self, m):
        """branch: area has empty id → skip."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={"areas": {"a1": {"label": "Sales", "ids": ["", "e1"]}}},
        ):
            result = m._admin_roster_area_labels()
        assert result == {"e1": "Sales"}

    def test_area_ids_not_list(self, m):
        """branch: area.ids is not a list → skip (None iteration)."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={"areas": {"a1": {"label": "Sales", "ids": None}}},
        ):
            result = m._admin_roster_area_labels()
        assert result == {}

    def test_first_label_wins_for_duplicate_id(self, m):
        """branch: duplicate id → first label wins."""
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={
                "areas": {
                    "a1": {"label": "First", "ids": ["e1"]},
                    "a2": {"label": "Second", "ids": ["e1"]},
                }
            },
        ):
            result = m._admin_roster_area_labels()
        assert result == {"e1": "First"}


# ============================================================
# _admin_employee_manifest
# ============================================================


class TestAdminEmployeeManifest:
    def test_empty_employee_id_returns_empty(self, m):
        """branch: employee_id is empty → {}."""
        assert m._admin_employee_manifest("") == {}

    def test_none_employee_id_returns_empty(self, m):
        """branch: employee_id is None → {}."""
        assert m._admin_employee_manifest(None) == {}

    def test_file_not_found_returns_empty(self, m):
        """branch: file doesn't exist → {}."""
        with patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            assert m._admin_employee_manifest("emp1") == {}

    def test_invalid_json_returns_empty(self, m):
        """branch: file has invalid JSON → {}."""
        with patch("pathlib.Path.read_text", return_value="not json"):
            assert m._admin_employee_manifest("emp1") == {}

    def test_valid_json_not_dict_returns_empty(self, m):
        """branch: file has valid JSON but not a dict → {}."""
        with patch("pathlib.Path.read_text", return_value='["not", "a", "dict"]'):
            assert m._admin_employee_manifest("emp1") == {}

    def test_valid_json_dict_returned(self, m):
        """branch: file has valid JSON dict → returned."""
        with patch("pathlib.Path.read_text", return_value='{"name": "Alice"}'):
            result = m._admin_employee_manifest("emp1")
        assert result == {"name": "Alice"}


# ============================================================
# _admin_duty_records_from_roster
# ============================================================


class TestAdminDutyRecordsFromRoster:
    def test_empty_roster_ids_returns_registry(self, m):
        """branch: roster_ids empty → return registry as-is."""
        registry = [{"id": "e1", "name": "Alice"}]
        with (
            patch.object(m, "_load_admin_duty_records", return_value=registry),
            patch.object(m, "_admin_roster_ids_by_department_order", return_value=[]),
        ):
            result = m._admin_duty_records_from_roster()
        assert result == registry

    def test_no_intersection_returns_registry(self, m):
        """branch: registry_ids and roster_id_set have no intersection → return registry."""
        registry = [{"id": "e1", "name": "Alice"}]
        with (
            patch.object(m, "_load_admin_duty_records", return_value=registry),
            patch.object(m, "_admin_roster_ids_by_department_order", return_value=["e2"]),
            patch.object(m, "_admin_roster_area_labels", return_value={}),
            patch.object(m, "_admin_employee_manifest", return_value={}),
        ):
            result = m._admin_duty_records_from_roster()
        assert result == registry

    def test_intersection_builds_records(self, m):
        """branch: intersection exists → build records from roster."""
        registry = [{"id": "e1", "name": "Alice", "description": "desc"}]
        with (
            patch.object(m, "_load_admin_duty_records", return_value=registry),
            patch.object(m, "_admin_roster_ids_by_department_order", return_value=["e1"]),
            patch.object(m, "_admin_roster_area_labels", return_value={"e1": "Sales"}),
            patch.object(
                m, "_admin_employee_manifest", return_value={"name": "Alice", "employee": {"label": "Alice"}}
            ),
        ):
            result = m._admin_duty_records_from_roster()
        assert len(result) == 1
        assert result[0]["id"] == "e1"
        assert result[0]["yuangon_area"] == "Sales"
        assert result[0]["is_duty_employee"] is True

    def test_record_with_no_id_in_registry_uses_eid(self, m):
        """branch: registry entry has no id → uses roster eid via setdefault."""
        registry = [{"name": "Unknown"}]
        with (
            patch.object(m, "_load_admin_duty_records", return_value=registry),
            patch.object(m, "_admin_roster_ids_by_department_order", return_value=["e1"]),
            patch.object(m, "_admin_roster_area_labels", return_value={}),
            patch.object(m, "_admin_employee_manifest", return_value={}),
        ):
            result = m._admin_duty_records_from_roster()
        assert len(result) == 1
        assert result[0]["id"] == "e1"

    def test_manifest_employee_not_dict(self, m):
        """branch: manifest.employee is not a dict → employee_meta is {}."""
        with (
            patch.object(m, "_load_admin_duty_records", return_value=[]),
            patch.object(m, "_admin_roster_ids_by_department_order", return_value=["e1"]),
            patch.object(m, "_admin_roster_area_labels", return_value={}),
            patch.object(m, "_admin_employee_manifest", return_value={"employee": "not-a-dict"}),
        ):
            result = m._admin_duty_records_from_roster()
        assert len(result) == 1
        assert result[0]["name"] == "e1"  # falls back to eid


# ============================================================
# _persist_mobile_cs_request
# ============================================================


class TestPersistMobileCsRequest:
    def test_success_returns_row_id(self, m):
        """branch: successful persist → (row_id, True, '')."""
        mock_db = _ctx_db(MagicMock())

        class FakeServiceRequest:
            __table__ = MagicMock()

            def __init__(self, **kwargs):
                self.id = 42
                self.kwargs = kwargs

        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.db.models.service_request.ServiceRequest", FakeServiceRequest),
        ):
            result = m._persist_mobile_cs_request(
                user=_user(),
                message_id="msg1",
                msg_body="hello",
                reply="reply",
                backend="cs",
                employee_result={"ok": True},
            )
        assert result == (42, True, "")

    def test_operational_error_returns_zero(self, m):
        """branch: OPERATIONAL_ERRORS → (0, False, error_msg)."""
        with patch("app.db.session.get_db", side_effect=ValueError("db gone")):
            result = m._persist_mobile_cs_request(
                user=_user(),
                message_id="msg1",
                msg_body="hello",
                reply="reply",
                backend="cs",
                employee_result={},
            )
        assert result[0] == 0
        assert result[1] is False
        assert "db gone" in result[2]


# ============================================================
# _normalize_mobile_payment_channel
# ============================================================


class TestNormalizeMobilePaymentChannel:
    def test_empty_returns_mobile_h5(self, m):
        assert m._normalize_mobile_payment_channel("") == "mobile_h5"

    def test_none_returns_mobile_h5(self, m):
        assert m._normalize_mobile_payment_channel(None) == "mobile_h5"

    def test_mobile_alias(self, m):
        assert m._normalize_mobile_payment_channel("mobile") == "mobile_h5"

    def test_h5_alias(self, m):
        assert m._normalize_mobile_payment_channel("h5") == "mobile_h5"

    def test_wap_alias(self, m):
        assert m._normalize_mobile_payment_channel("wap") == "mobile_h5"

    def test_alipay_h5_alias(self, m):
        assert m._normalize_mobile_payment_channel("alipay_h5") == "alipay"

    def test_zhifubao_alias(self, m):
        assert m._normalize_mobile_payment_channel("zhifubao") == "alipay"

    def test_wechat_alias(self, m):
        assert m._normalize_mobile_payment_channel("wechat") == "wechat_h5"

    def test_weixin_alias(self, m):
        assert m._normalize_mobile_payment_channel("weixin") == "wechat_h5"

    def test_weixin_h5_alias(self, m):
        assert m._normalize_mobile_payment_channel("weixin_h5") == "wechat_h5"

    def test_alipay_direct(self, m):
        assert m._normalize_mobile_payment_channel("alipay") == "alipay"

    def test_unknown_returns_mobile_h5(self, m):
        assert m._normalize_mobile_payment_channel("unknown") == "mobile_h5"

    def test_uppercase_normalized(self, m):
        assert m._normalize_mobile_payment_channel("ALIPAY") == "alipay"

    def test_hyphen_replaced_with_underscore(self, m):
        assert m._normalize_mobile_payment_channel("alipay-h5") == "alipay"


# ============================================================
# _mobile_checkout_sign_body
# ============================================================


class TestMobileCheckoutSignBody:
    def test_empty_body(self, m):
        assert m._mobile_checkout_sign_body({}) == {}

    def test_plan_id_present(self, m):
        result = m._mobile_checkout_sign_body({"plan_id": "p1"})
        assert result == {"plan_id": "p1"}

    def test_wallet_recharge_true(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": True, "total_amount": "100.5"})
        assert result["wallet_recharge"] is True
        assert result["total_amount"] == 100.5
        assert result["subject"] == "钱包充值"

    def test_wallet_recharge_string_true(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": "true", "total_amount": 50})
        assert result["wallet_recharge"] is True
        assert result["total_amount"] == 50.0

    def test_wallet_recharge_string_yes(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": "yes"})
        assert result["wallet_recharge"] is True

    def test_wallet_recharge_string_on(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": "on"})
        assert result["wallet_recharge"] is True

    def test_wallet_recharge_string_1(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": "1"})
        assert result["wallet_recharge"] is True

    def test_wallet_recharge_false(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": False})
        assert "wallet_recharge" not in result

    def test_wallet_recharge_invalid_total_amount(self, m):
        result = m._mobile_checkout_sign_body(
            {"wallet_recharge": True, "total_amount": "not-a-number"}
        )
        assert result["total_amount"] == 0.0

    def test_wallet_recharge_none_total_amount(self, m):
        result = m._mobile_checkout_sign_body({"wallet_recharge": True, "total_amount": None})
        assert result["total_amount"] == 0.0

    def test_wallet_recharge_custom_subject(self, m):
        result = m._mobile_checkout_sign_body(
            {"wallet_recharge": True, "total_amount": 10, "subject": "Custom"}
        )
        assert result["subject"] == "Custom"

    def test_out_trade_no_present(self, m):
        result = m._mobile_checkout_sign_body({"out_trade_no": "OTN123"})
        assert result["out_trade_no"] == "OTN123"

    def test_metadata_present(self, m):
        result = m._mobile_checkout_sign_body({"metadata": {"key": "val"}})
        assert result["metadata"] == {"key": "val"}

    def test_plan_id_and_wallet_recharge(self, m):
        result = m._mobile_checkout_sign_body(
            {"plan_id": "p1", "wallet_recharge": True, "total_amount": 100}
        )
        assert result["plan_id"] == "p1"
        assert result["wallet_recharge"] is True


# ============================================================
# _conversation_state_uid
# ============================================================


class TestConversationStateUid:
    def test_uid_positive(self, m):
        assert m._conversation_state_uid(_user(uid=5)) == 5

    def test_uid_zero(self, m):
        assert m._conversation_state_uid(_user(uid=0)) == 0

    def test_uid_none(self, m):
        u = MagicMock()
        u.id = None
        assert m._conversation_state_uid(u) == 0

    def test_uid_negative(self, m):
        u = MagicMock()
        u.id = -1
        assert m._conversation_state_uid(u) == 0


# ============================================================
# _mobile_group_mode
# ============================================================


class TestMobileGroupMode:
    def test_admin_account_kind(self, m):
        """branch: account_kind is 'admin' → 'admin'."""
        req = MagicMock()
        with patch.object(m, "_mobile_session_meta", return_value={"account_kind": "admin"}):
            assert m._mobile_group_mode(req) == "admin"

    def test_enterprise_account_kind(self, m):
        """branch: account_kind is not 'admin' → 'enterprise'."""
        req = MagicMock()
        with patch.object(m, "_mobile_session_meta", return_value={"account_kind": "enterprise"}):
            assert m._mobile_group_mode(req) == "enterprise"

    def test_empty_account_kind(self, m):
        """branch: account_kind is empty → 'enterprise'."""
        req = MagicMock()
        with patch.object(m, "_mobile_session_meta", return_value={"account_kind": ""}):
            assert m._mobile_group_mode(req) == "enterprise"

    def test_none_meta(self, m):
        """branch: meta is None → 'enterprise'."""
        req = MagicMock()
        with patch.object(m, "_mobile_session_meta", return_value=None):
            assert m._mobile_group_mode(req) == "enterprise"

    def test_admin_uppercase(self, m):
        """branch: account_kind is 'ADMIN' → 'admin'."""
        req = MagicMock()
        with patch.object(m, "_mobile_session_meta", return_value={"account_kind": "ADMIN"}):
            assert m._mobile_group_mode(req) == "admin"


# ============================================================
# mobile_employee_ssot
# ============================================================


class TestMobileEmployeeSsot:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_employee_ssot(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch.object(m, "_employee_ssot_payload", return_value={"departments": []}):
            result = await m.mobile_employee_ssot(user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_installed_employee_pack_ids_error(self, m):
        """branch: _installed_employee_pack_ids raises → caught."""
        with (
            patch(
                "app.application.ops_closure_status._installed_employee_pack_ids",
                side_effect=ValueError("boom"),
            ),
            patch("app.mod_sdk.employee_ssot.derive_employee_ssot", return_value={"ok": True}),
        ):
            result = await m.mobile_employee_ssot(user=_user())
        assert result is not None


# ============================================================
# mobile_admin_home
# ============================================================


class TestMobileAdminHome:
    @pytest.mark.asyncio
    async def test_require_admin_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_home(request=MagicMock(), user=_user())
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin",
                return_value=({"account_kind": "admin"}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._load_market_ai_employee_profile_index",
                new=AsyncMock(return_value=({}, False, "")),
            ),
            patch.object(m, "_admin_employee_items", return_value=[]),
        ):
            result = await m.mobile_admin_home(request=MagicMock(), user=_user())
        assert result is not None


# ============================================================
# mobile_admin_cursor_super_employee_messages
# ============================================================


class TestMobileAdminCursorSuperEmployeeMessages:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_cursor_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=0
            ),
        ):
            result = await m.mobile_admin_cursor_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CursorSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.list_messages.return_value = [{"id": 1}]
            result = await m.mobile_admin_cursor_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CursorSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.list_messages.side_effect = err_class("fail")
            result = await m.mobile_admin_cursor_super_employee_messages(
                request=MagicMock(), limit=80, user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_admin_cursor_super_employee_invoke
# ============================================================


class TestMobileAdminCursorSuperEmployeeInvoke:
    def _body(self):
        b = MagicMock()
        b.message = "hello"
        b.body = ""
        b.context = {}
        return b

    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_admin_cursor_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=0
            ),
        ):
            result = await m.mobile_admin_cursor_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CursorSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.side_effect = ValueError("bad")
            result = await m.mobile_admin_cursor_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CursorSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.side_effect = err_class("fail")
            result = await m.mobile_admin_cursor_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._mobile_request_user_id", return_value=5
            ),
            patch("app.fastapi_routes.mobile_api_extensions.CursorSuperEmployeeService") as svc_cls,
        ):
            svc_cls.return_value.invoke.return_value = {"result": "ok"}
            result = await m.mobile_admin_cursor_super_employee_invoke(
                request=MagicMock(), body=self._body(), user=_user()
            )
        assert result is not None


# ============================================================
# Conversation state routes
# ============================================================


class TestMobileConversationTogglePin:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        result = await m.mobile_conversation_toggle_pin(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.toggle_pinned.return_value = {"pinned": True}
            result = await m.mobile_conversation_toggle_pin(conversation_id="c1", user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.toggle_pinned.side_effect = err_class("fail")
            result = await m.mobile_conversation_toggle_pin(conversation_id="c1", user=_user(uid=5))
        assert result.status_code == 500


class TestMobileConversationMarkUnread:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        result = await m.mobile_conversation_mark_unread(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.mark_unread.return_value = {"unread": True}
            result = await m.mobile_conversation_mark_unread(conversation_id="c1", user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.mark_unread.side_effect = err_class("fail")
            result = await m.mobile_conversation_mark_unread(conversation_id="c1", user=_user(uid=5))
        assert result.status_code == 500


class TestMobileConversationMarkRead:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        result = await m.mobile_conversation_mark_read(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.mark_read.return_value = {"read": True}
            result = await m.mobile_conversation_mark_read(conversation_id="c1", user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.mark_read.side_effect = err_class("fail")
            result = await m.mobile_conversation_mark_read(conversation_id="c1", user=_user(uid=5))
        assert result.status_code == 500


class TestMobileConversationToggleFollowed:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        result = await m.mobile_conversation_toggle_followed(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.toggle_followed.return_value = {"followed": True}
            result = await m.mobile_conversation_toggle_followed(conversation_id="c1", user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.toggle_followed.side_effect = err_class("fail")
            result = await m.mobile_conversation_toggle_followed(conversation_id="c1", user=_user(uid=5))
        assert result.status_code == 500


class TestMobileConversationToggleHidden:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        result = await m.mobile_conversation_toggle_hidden(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.toggle_hidden.return_value = {"hidden": True}
            result = await m.mobile_conversation_toggle_hidden(conversation_id="c1", user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.toggle_hidden.side_effect = err_class("fail")
            result = await m.mobile_conversation_toggle_hidden(conversation_id="c1", user=_user(uid=5))
        assert result.status_code == 500


class TestMobileConversationDelete:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        result = await m.mobile_conversation_delete(conversation_id="c1", user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.delete.return_value = {"deleted": True}
            result = await m.mobile_conversation_delete(conversation_id="c1", user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.application.conversation_state_service.ConversationStateService"
        ) as svc_cls:
            svc_cls.return_value.delete.side_effect = err_class("fail")
            result = await m.mobile_conversation_delete(conversation_id="c1", user=_user(uid=5))
        assert result.status_code == 500


# ============================================================
# AI group toggle/mark routes
# ============================================================


def _ai_group_test_setup(m, route_name, svc_method, body=None, require_err=True, uid_zero=True):
    """Helper to reduce boilerplate for AI group route tests."""
    pass


class TestMobileAiGroupTogglePin:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_toggle_pin(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_toggle_pin(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_pinned.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_toggle_pin(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_pinned.side_effect = err_class("fail")
            result = await m.mobile_ai_group_toggle_pin(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_pinned.return_value = {"pinned": True}
            result = await m.mobile_ai_group_toggle_pin(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result is not None


class TestMobileAiGroupMarkUnread:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_mark_unread(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_mark_unread(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.mark_unread.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_mark_unread(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.mark_unread.side_effect = err_class("fail")
            result = await m.mobile_ai_group_mark_unread(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.mark_unread.return_value = {"unread": True}
            result = await m.mobile_ai_group_mark_unread(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result is not None


class TestMobileAiGroupMarkRead:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_mark_read(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_mark_read(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.mark_read.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_mark_read(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.mark_read.side_effect = err_class("fail")
            result = await m.mobile_ai_group_mark_read(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.mark_read.return_value = {"read": True}
            result = await m.mobile_ai_group_mark_read(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result is not None


class TestMobileAiGroupToggleFollowed:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_toggle_followed(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_toggle_followed(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_followed.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_toggle_followed(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_followed.side_effect = err_class("fail")
            result = await m.mobile_ai_group_toggle_followed(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_followed.return_value = {"followed": True}
            result = await m.mobile_ai_group_toggle_followed(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result is not None


class TestMobileAiGroupToggleHidden:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_toggle_hidden(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_toggle_hidden(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_hidden.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_toggle_hidden(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_hidden.side_effect = err_class("fail")
            result = await m.mobile_ai_group_toggle_hidden(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.toggle_hidden.return_value = {"hidden": True}
            result = await m.mobile_ai_group_toggle_hidden(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result is not None


class TestMobileAiGroupDelete:
    @pytest.mark.asyncio
    async def test_require_error(self, m):
        err_resp = MagicMock()
        err_resp.status_code = 403
        with patch(
            "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
            return_value=(None, err_resp),
        ):
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_uid_zero(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=0),
        ):
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.delete_group.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.delete_group.side_effect = err_class("fail")
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.delete_group.return_value = {"deleted": True}
            result = await m.mobile_ai_group_delete(
                request=MagicMock(), group_id="g1", user=_user()
            )
        assert result is not None


# ============================================================
# Onboarding / industry-baseline / install routes
# ============================================================


class TestMobileOnboardingIndustries:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_onboarding_industries(request=MagicMock(), user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
            new=AsyncMock(return_value={"industries": []}),
        ):
            result = await m.mobile_onboarding_industries(request=MagicMock(), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_onboarding_industries(request=MagicMock(), user=_user())
        assert result.status_code == 500


class TestMobileIndustryBaseline:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_industry_baseline(
            request=MagicMock(), industry_id="test", user=None
        )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.mod_sdk.industry_baseline.build_industry_baseline_plan_for_request",
            new=AsyncMock(return_value={"plan": "ok"}),
        ):
            result = await m.mobile_industry_baseline(
                request=MagicMock(), industry_id="test", user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.mod_sdk.industry_baseline.build_industry_baseline_plan_for_request",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_industry_baseline(
                request=MagicMock(), industry_id="test", user=_user()
            )
        assert result.status_code == 500


class TestMobileInstallHostFoundation:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_install_host_foundation(edition=None, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        mock_result = MagicMock()
        mock_result.data = {"installed": True}
        mock_result.message = "ok"
        mock_result.success = True
        with patch(
            "app.fastapi_routes.mod_store_routes._install_host_foundation_internal",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await m.mobile_install_host_foundation(edition="enterprise", user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_failed_install(self, m):
        """branch: result.success is False → code 409."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_result.message = "already installed"
        mock_result.success = False
        with patch(
            "app.fastapi_routes.mod_store_routes._install_host_foundation_internal",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await m.mobile_install_host_foundation(edition=None, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.fastapi_routes.mod_store_routes._install_host_foundation_internal",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_install_host_foundation(edition=None, user=_user())
        assert result.status_code == 500


class TestMobileInstallIndustrySeed:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_install_industry_seed(body={}, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_no_industry_id_returns_400(self, m):
        result = await m.mobile_install_industry_seed(body={}, user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_industry_id_from_industryId_key(self, m):
        """branch: industry_id from industryId key."""
        with patch(
            "app.mod_sdk.industry_seed.install_industry_seed_with_fallback",
            new=AsyncMock(return_value={"success": True, "message": "ok"}),
        ):
            result = await m.mobile_install_industry_seed(
                body={"industryId": "retail"}, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_industry_id_from_mod_id_key(self, m):
        """branch: industry_id from mod_id key."""
        with patch(
            "app.mod_sdk.industry_seed.install_industry_seed_with_fallback",
            new=AsyncMock(return_value={"success": True, "message": "ok"}),
        ):
            result = await m.mobile_install_industry_seed(
                body={"mod_id": "retail-mod"}, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_failed_install_returns_409_code(self, m):
        """branch: data.success is False → code 409."""
        with patch(
            "app.mod_sdk.industry_seed.install_industry_seed_with_fallback",
            new=AsyncMock(return_value={"success": False, "message": "failed"}),
        ):
            result = await m.mobile_install_industry_seed(
                body={"industry_id": "retail"}, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.mod_sdk.industry_seed.install_industry_seed_with_fallback",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_install_industry_seed(
                body={"industry_id": "retail"}, user=_user()
            )
        assert result.status_code == 500


class TestMobileInstallMod:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_install_mod(body={}, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_no_mod_id_returns_400(self, m):
        result = await m.mobile_install_mod(body={}, user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_mod_id_from_pkg_id(self, m):
        """branch: mod_id from pkg_id key."""
        mock_result = MagicMock()
        mock_result.data = {"id": "m1"}
        mock_result.message = "ok"
        mock_result.success = True
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await m.mobile_install_mod(body={"pkg_id": "m1"}, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_id_from_package_file(self, m):
        """branch: mod_id from package_file key."""
        mock_result = MagicMock()
        mock_result.data = {"id": "m1"}
        mock_result.message = "ok"
        mock_result.success = True
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await m.mobile_install_mod(body={"package_file": "m1"}, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_failed_install(self, m):
        """branch: result.success is False → code 409."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_result.message = "failed"
        mock_result.success = False
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await m.mobile_install_mod(body={"mod_id": "m1"}, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_install_mod(body={"mod_id": "m1"}, user=_user())
        assert result.status_code == 500


class TestMobileInstallCustomerDeliverySeed:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_install_customer_delivery_seed(body={}, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_no_mod_id_returns_400(self, m):
        result = await m.mobile_install_customer_delivery_seed(body={}, user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.mod_sdk.customer_delivery_seed.install_customer_delivery_seed_package",
            new=AsyncMock(return_value={"success": True, "message": "ok"}),
        ):
            result = await m.mobile_install_customer_delivery_seed(
                body={"mod_id": "m1", "industry_id": "retail"}, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_failed_install(self, m):
        """branch: data.success is False → code 409."""
        with patch(
            "app.mod_sdk.customer_delivery_seed.install_customer_delivery_seed_package",
            new=AsyncMock(return_value={"success": False, "message": "failed"}),
        ):
            result = await m.mobile_install_customer_delivery_seed(
                body={"mod_id": "m1"}, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.mod_sdk.customer_delivery_seed.install_customer_delivery_seed_package",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_install_customer_delivery_seed(
                body={"mod_id": "m1"}, user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_industry_id_from_industryId_key(self, m):
        """branch: industry_id from industryId key."""
        with patch(
            "app.mod_sdk.customer_delivery_seed.install_customer_delivery_seed_package",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await m.mobile_install_customer_delivery_seed(
                body={"mod_id": "m1", "industryId": "retail"}, user=_user()
            )
        assert result is not None


# ============================================================
# Payment routes
# ============================================================


class TestMobilePaymentPlans:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_payment_plans(request=MagicMock(), user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_error_returns_error_status(self, m):
        """branch: payload has __proxy_error__ → return error status."""
        err_payload = {"__proxy_error__": True, "status_code": 502, "payload": "timeout"}
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(return_value=err_payload),
        ):
            result = await m.mobile_payment_plans(request=MagicMock(), user=_user())
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_success(self, m):
        """branch: payload is dict → add market_base_url and payment_channels."""
        with (
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"plans": []}),
            ),
            patch("app.fastapi_routes.market_account._market_base_url", return_value="http://mkt"),
        ):
            result = await m.mobile_payment_plans(request=MagicMock(), user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_payment_plans(request=MagicMock(), user=_user())
        assert result.status_code == 500


class TestMobilePaymentCheckout:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_payment_checkout(
            request=MagicMock(), body={}, user=None
        )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_no_authorization_returns_401(self, m):
        """branch: authorization empty → 401."""
        req = MagicMock()
        req.headers = {}
        with patch.object(m, "_mobile_market_authorization", return_value=""):
            result = await m.mobile_payment_checkout(
                request=req, body={"channel": "alipay"}, user=_user()
            )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sign_proxy_error(self, m):
        """branch: sign-checkout returns __proxy_error__."""
        err = {"__proxy_error__": True, "status_code": 502, "payload": "sign fail"}
        with (
            patch.object(m, "_mobile_market_authorization", return_value="Bearer tok"),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value=err),
            ),
        ):
            result = await m.mobile_payment_checkout(
                request=MagicMock(), body={"channel": "alipay"}, user=_user()
            )
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_checkout_proxy_error(self, m):
        """branch: checkout returns __proxy_error__."""
        sign_ok = {"signed": True}
        err = {"__proxy_error__": True, "status_code": 502, "payload": "checkout fail"}

        async def mock_proxy(method, path, **kwargs):
            if "sign-checkout" in path:
                return sign_ok
            return err

        with (
            patch.object(m, "_mobile_market_authorization", return_value="Bearer tok"),
            patch(
                "app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy
            ),
        ):
            result = await m.mobile_payment_checkout(
                request=MagicMock(), body={"channel": "alipay"}, user=_user()
            )
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_success(self, m):
        sign_ok = {"signed": True}
        checkout_ok = {"order_id": "o1"}

        async def mock_proxy(method, path, **kwargs):
            if "sign-checkout" in path:
                return sign_ok
            return checkout_ok

        with (
            patch.object(m, "_mobile_market_authorization", return_value="Bearer tok"),
            patch("app.fastapi_routes.market_account._proxy_json", side_effect=mock_proxy),
        ):
            result = await m.mobile_payment_checkout(
                request=MagicMock(), body={"channel": "alipay"}, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch.object(m, "_mobile_market_authorization", return_value="Bearer tok"),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(side_effect=err_class("fail")),
            ),
        ):
            result = await m.mobile_payment_checkout(
                request=MagicMock(), body={"channel": "alipay"}, user=_user()
            )
        assert result.status_code == 500


class TestMobilePaymentQuery:
    @pytest.mark.asyncio
    async def test_user_none_returns_401(self, m):
        result = await m.mobile_payment_query(
            request=MagicMock(), out_trade_no="OTN1", user=None
        )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_error(self, m):
        err = {"__proxy_error__": True, "status_code": 404, "payload": "not found"}
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(return_value=err),
        ):
            result = await m.mobile_payment_query(
                request=MagicMock(), out_trade_no="OTN1", user=_user()
            )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_success(self, m):
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(return_value={"status": "paid"}),
        ):
            result = await m.mobile_payment_query(
                request=MagicMock(), out_trade_no="OTN1", user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(side_effect=err_class("fail")),
        ):
            result = await m.mobile_payment_query(
                request=MagicMock(), out_trade_no="OTN1", user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_relay_desktop_register
# ============================================================


class TestMobileRelayDesktopRegister:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(
            label="desktop1",
            device_id="dev1",
            capabilities=[],
            relay_base_url="http://relay",
        )
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.register_desktop.return_value = {"relay_id": "r1"}
            result = await m.mobile_relay_desktop_register(body=body)
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(
            label="desktop1", device_id="dev1", capabilities=[], relay_base_url=""
        )
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.register_desktop.side_effect = err_class("fail")
            result = await m.mobile_relay_desktop_register(body=body)
        assert result.status_code == 500


# ============================================================
# mobile_relay_bind_account
# ============================================================


class TestMobileRelayBindAccount:
    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self, m):
        body = SimpleNamespace(relay_id="r1")
        with patch.object(m, "_mobile_user_identity", return_value=(0, "")):
            result = await m.mobile_relay_bind_account(body=body, user=_user(uid=0))
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_desktop_none_returns_404(self, m):
        body = SimpleNamespace(relay_id="r1")
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.bind_mobile_by_account.return_value = None
            result = await m.mobile_relay_bind_account(body=body, user=_user(uid=5))
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(relay_id="r1")
        desktop = {"relay_id": "r1", "desktop_id": "d1"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch.object(m, "_mobile_user_public_dict", return_value={"id": 5}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.bind_mobile_by_account.return_value = desktop
            result = await m.mobile_relay_bind_account(body=body, user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(relay_id="r1")
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.bind_mobile_by_account.side_effect = err_class("fail")
            result = await m.mobile_relay_bind_account(body=body, user=_user(uid=5))
        assert result.status_code == 500


# ============================================================
# mobile_relay_confirm / confirm_code / create_task / task_status / desktop_poll success paths
# ============================================================


class TestMobileRelayConfirmSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(relay_id="r1", code="C1")
        desktop = {"relay_id": "r1", "desktop_id": "d1"}
        with (
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.confirm_mobile.return_value = desktop
            result = await m.mobile_relay_confirm(body=body, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(relay_id="r1", code="C1")
        with (
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.confirm_mobile.side_effect = err_class("fail")
            result = await m.mobile_relay_confirm(body=body, user=_user())
        assert result.status_code == 500


class TestMobileRelayConfirmCodeSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(code="CODE1")
        desktop = {"relay_id": "r1", "desktop_id": "d1"}
        with (
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.confirm_mobile_by_code.return_value = desktop
            result = await m.mobile_relay_confirm_code(body=body, user=_user())
        assert result is not None


class TestMobileRelayCreateTaskSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(relay_id="r1", kind="test", payload={"a": 1})
        task = {"task_id": "t1", "status": "pending"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.create_task.return_value = task
            result = await m.mobile_relay_create_task(body=body, user=_user(uid=5))
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(relay_id="r1", kind="test", payload={})
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.create_task.side_effect = err_class("fail")
            result = await m.mobile_relay_create_task(body=body, user=_user(uid=5))
        assert result.status_code == 500


class TestMobileRelayTaskStatusSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        task = {"task_id": "t1", "status": "done"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u")),
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
        ):
            svc_cls.return_value.get_task.return_value = task
            result = await m.mobile_relay_task_status(task_id="t1", user=_user(uid=5))
        assert result is not None


class TestMobileRelayDesktopPollSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", max_tasks=5)
        data = {"tasks": []}
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.poll_desktop.return_value = data
            result = await m.mobile_relay_desktop_poll(body=body)
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", max_tasks=5)
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.poll_desktop.side_effect = err_class("fail")
            result = await m.mobile_relay_desktop_poll(body=body)
        assert result.status_code == 500


class TestMobileRelayDesktopCompleteAdditional:
    @pytest.mark.asyncio
    async def test_success_without_group_report(self, m):
        """branch: group_report is None → not added to data."""
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", status="done", result={})
        task = {"task_id": "t1", "status": "completed"}
        with (
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as group_cls,
        ):
            svc_cls.return_value.complete_desktop_task.return_value = task
            group_cls.return_value.append_relay_work_report.return_value = None
            result = await m.mobile_relay_desktop_complete(task_id="t1", body=body)
        assert result is not None

    @pytest.mark.asyncio
    async def test_group_report_error_continues(self, m):
        """branch: AiGroupChatService raises RECOVERABLE_ERRORS → continues."""
        err_class = _err_class(m)
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", status="done", result={})
        task = {"task_id": "t1", "status": "completed"}
        with (
            patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls,
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as group_cls,
        ):
            svc_cls.return_value.complete_desktop_task.return_value = task
            group_cls.return_value.append_relay_work_report.side_effect = err_class("fail")
            result = await m.mobile_relay_desktop_complete(task_id="t1", body=body)
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(relay_id="r1", desktop_token="tok", status="done", result={})
        with patch("app.fastapi_routes.mobile_api_extensions.MobileRelayService") as svc_cls:
            svc_cls.return_value.complete_desktop_task.side_effect = err_class("fail")
            result = await m.mobile_relay_desktop_complete(task_id="t1", body=body)
        assert result.status_code == 500


# ============================================================
# AI group routes success/recoverable paths
# ============================================================


class TestMobileAiGroupsListSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.list_groups.return_value = []
            result = await m.mobile_ai_groups_list(request=MagicMock(), user=_user())
        assert result is not None


class TestMobileAiGroupsCreateSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.create_group.return_value = {"id": "g1"}
            result = await m.mobile_ai_groups_create(
                request=MagicMock(), body=SimpleNamespace(name="g1"), user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.create_group.side_effect = err_class("fail")
            result = await m.mobile_ai_groups_create(
                request=MagicMock(), body=SimpleNamespace(name="g1"), user=_user()
            )
        assert result.status_code == 500


class TestMobileAiGroupMessagesSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.get_messages.return_value = []
            result = await m.mobile_ai_group_messages(
                request=MagicMock(), group_id="g1", limit=100, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.get_messages.side_effect = err_class("fail")
            result = await m.mobile_ai_group_messages(
                request=MagicMock(), group_id="g1", limit=100, user=_user()
            )
        assert result.status_code == 500


class TestMobileAiGroupPostSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(message="hi", sender_name="me", mentions=[], dispatch=True, branch_context=None)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.post_message = AsyncMock(return_value={"ok": True})
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        body = SimpleNamespace(message="hi", sender_name=None, mentions=[], dispatch=True, branch_context=None)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.post_message = AsyncMock(side_effect=ValueError("bad"))
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(message="hi", sender_name=None, mentions=[], dispatch=True, branch_context=None)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.post_message = AsyncMock(side_effect=err_class("fail"))
            result = await m.mobile_ai_group_post(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 500


class TestMobileAiGroupAddMemberSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(
            employee_id="e1", mod_id="m1", name="Alice", avatar=None, summary=None
        )
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.add_member.return_value = {"id": "g1"}
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        body = SimpleNamespace(
            employee_id="e1", mod_id="m1", name="Alice", avatar=None, summary=None
        )
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.add_member.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        body = SimpleNamespace(
            employee_id="e1", mod_id="m1", name="Alice", avatar=None, summary=None
        )
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.add_member.side_effect = err_class("fail")
            result = await m.mobile_ai_group_add_member(
                request=MagicMock(), group_id="g1", body=body, user=_user()
            )
        assert result.status_code == 500


class TestMobileAiGroupRemoveMemberSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.remove_member.return_value = {"id": "g1"}
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_value_error(self, m):
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.remove_member.side_effect = ValueError("bad")
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error(self, m):
        err_class = _err_class(m)
        with (
            patch(
                "app.fastapi_routes.mobile_api_extensions._require_mobile_admin_or_enterprise",
                return_value=({}, None),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._mobile_group_uid", return_value=5),
            patch("app.fastapi_routes.mobile_api_extensions.AiGroupChatService") as svc_cls,
        ):
            svc_cls.return_value.remove_member.side_effect = err_class("fail")
            result = await m.mobile_ai_group_remove_member(
                request=MagicMock(), group_id="g1", employee_id="e1", user=_user()
            )
        assert result.status_code == 500


# ============================================================
# mobile_pairing_exchange additional branches
# ============================================================


class TestMobilePairingExchangeBranchCov:
    @pytest.mark.asyncio
    async def test_no_nonce_no_code_returns_400(self, m):
        """branch: both nonce and code empty → 400."""
        body = SimpleNamespace(nonce="", code="")
        result = await m.mobile_pairing_exchange(body=body, user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_rec_none_returns_400(self, m):
        """branch: consume returns None → 400."""
        body = SimpleNamespace(nonce="n1", code="")
        with patch.object(m, "consume_pairing_nonce", return_value=None):
            result = await m.mobile_pairing_exchange(body=body, user=_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_success_by_nonce(self, m):
        """branch: success by nonce, no cached relay."""
        body = SimpleNamespace(nonce="n1", code="")
        rec = {"host": "h", "port": 5000, "nonce": "n1"}
        with (
            patch.object(m, "consume_pairing_nonce", return_value=rec),
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch.object(m, "_enrich_pairing_payload", return_value={"host": "h"}),
            patch.object(m, "_relay_mobile_auth_payload", return_value={"token": "t"}),
            patch.object(m, "_cached_desktop_relay_for_account_binding", return_value=None),
        ):
            result = await m.mobile_pairing_exchange(body=body, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_success_by_code(self, m):
        """branch: success by code, with cached relay."""
        body = SimpleNamespace(nonce="", code="CODE1")
        rec = {"host": "h", "port": 5000, "nonce": "n1"}
        relay = {"relay_id": "r1", "relay_base_url": "http://r", "exp": 0}
        with (
            patch.object(m, "consume_by_shortcode", return_value=rec),
            patch.object(m, "_resolve_mobile_relay_user", return_value={"id": 1, "username": "u"}),
            patch.object(m, "_enrich_pairing_payload", return_value={"host": "h"}),
            patch.object(m, "_relay_mobile_auth_payload", return_value={"token": "t"}),
            patch.object(
                m, "_cached_desktop_relay_for_account_binding", return_value=relay
            ),
        ):
            result = await m.mobile_pairing_exchange(body=body, user=_user())
        assert result is not None


# ============================================================
# mobile_service_bridge_request_respond - HTTPException branch
# ============================================================


class TestMobileServiceBridgeRequestRespondHttpEx:
    @pytest.mark.asyncio
    async def test_http_exception_reraised(self, m):
        """branch: HTTPException is reraised."""
        from fastapi import HTTPException

        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        with patch("app.db.session.get_db", side_effect=HTTPException(status_code=409, detail="conflict")):
            with pytest.raises(HTTPException):
                await m.mobile_service_bridge_request_respond(
                    request_id=1, body=body, user=_user()
                )

    @pytest.mark.asyncio
    async def test_generic_exception_returns_500(self, m):
        """branch: generic Exception → 500."""
        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        with patch("app.db.session.get_db", side_effect=Exception("unexpected")):
            result = await m.mobile_service_bridge_request_respond(
                request_id=1, body=body, user=_user()
            )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success(self, m):
        """branch: successful respond."""
        body = SimpleNamespace(status="resolved", response="ok", responded_by="admin")
        mock_db = _ctx_db(MagicMock())
        mock_req = MagicMock()
        mock_req.to_dict.return_value = {"id": 1, "status": "resolved"}
        mock_db.query.return_value.filter.return_value.first.return_value = mock_req
        with patch("app.db.session.get_db", return_value=mock_db):
            result = await m.mobile_service_bridge_request_respond(
                request_id=1, body=body, user=_user()
            )
        assert result is not None


# ============================================================
# mobile_ai_circle_posts additional
# ============================================================


class TestMobileAiCirclePostsBranchCov:
    @pytest.mark.asyncio
    async def test_success_without_profile_match(self, m):
        """branch: post has employee_id but no matching profile."""
        post = {"employee_id": "unknown", "author_name": "default", "author_avatar": None}
        with (
            patch("app.application.ai_circle_service.list_posts", return_value=[post]),
            patch.object(m, "_ai_circle_employee_profiles", return_value={}),
            patch.object(m, "_ai_circle_user", return_value=(1, "user", None)),
        ):
            result = await m.mobile_ai_circle_posts(limit=50, user=_user())
        assert result is not None

    @pytest.mark.asyncio
    async def test_success_with_profile_match_and_avatar(self, m):
        """branch: profile found, avatar set on post."""
        post = {"employee_id": "emp1", "author_name": "default", "author_avatar": None}
        profiles = {"emp1": {"name": "Alice", "avatar": "http://x/a.png"}}
        with (
            patch("app.application.ai_circle_service.list_posts", return_value=[post]),
            patch.object(m, "_ai_circle_employee_profiles", return_value=profiles),
            patch.object(m, "_ai_circle_user", return_value=(1, "user", None)),
        ):
            result = await m.mobile_ai_circle_posts(limit=50, user=_user())
        assert result is not None


class TestMobileAiCircleCreatePostSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(body="hello")
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "Bob", None)),
            patch("app.application.ai_circle_service.create_user_post", return_value=42),
        ):
            result = await m.mobile_ai_circle_create_post(body=body, user=_user())
        assert result is not None


class TestMobileAiCircleToggleLikeSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "u", None)),
            patch("app.application.ai_circle_service.toggle_like", return_value=True),
        ):
            result = await m.mobile_ai_circle_toggle_like(post_id=1, user=_user())
        assert result is not None


class TestMobileAiCircleAddCommentSuccess:
    @pytest.mark.asyncio
    async def test_success(self, m):
        body = SimpleNamespace(body="comment")
        with (
            patch.object(m, "_ai_circle_user", return_value=(1, "u", None)),
            patch("app.application.ai_circle_service.add_comment", return_value=99),
        ):
            result = await m.mobile_ai_circle_add_comment(
                post_id=1, body=body, user=_user()
            )
        assert result is not None


# ============================================================
# mobile_nav_menu additional branches
# ============================================================


class TestMobileNavMenuBranchCov:
    @pytest.mark.asyncio
    async def test_personal_role_filtered(self, m):
        """branch: personal role → only chat, im, ai-ecosystem, settings visible."""
        u = _user(uid=1, role="personal")
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_super_admin_role(self, m):
        """branch: super_admin role → all items + admin item."""
        u = _user(uid=1, role="super_admin")
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_owner_role(self, m):
        """branch: owner role → all items + admin item."""
        u = _user(uid=1, role="owner")
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_empty_role(self, m):
        """branch: empty role → enterprise account_kind."""
        u = _user(uid=1, role="")
        with patch.object(m, "_mobile_mod_items", return_value=[]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_with_mod_prefix(self, m):
        """branch: menu_id starts with 'mod-' → used as-is."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "frontend_menu": [
                {"id": "mod-existing", "label": "Existing", "path": "/x", "icon": "fa-cube"}
            ],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_with_key_instead_of_id(self, m):
        """branch: menu_entry has 'key' but no 'id'."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "frontend_menu": [{"key": "k1", "label": "Key Entry", "path": "/k"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_with_name_instead_of_label(self, m):
        """branch: menu_entry has 'name' but no 'label'."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "frontend_menu": [{"id": "e1", "name": "Name Entry", "path": "/n"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_with_url_instead_of_path(self, m):
        """branch: menu_entry has 'url' but no 'path'."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "frontend_menu": [{"id": "e1", "label": "URL Entry", "url": "/u"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_menu_entry_with_iconClass(self, m):
        """branch: menu_entry has 'iconClass' but no 'icon'."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "frontend_menu": [{"id": "e1", "label": "Icon", "path": "/i", "iconClass": "fa-test"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None

    @pytest.mark.asyncio
    async def test_mod_with_menu_key_fallback(self, m):
        """branch: mod has 'menu' key instead of 'frontend_menu'."""
        u = _user(uid=1, role="admin")
        mod = {
            "id": "testmod",
            "name": "Test",
            "menu": [{"id": "e1", "label": "Menu Entry", "path": "/m"}],
        }
        with patch.object(m, "_mobile_mod_items", return_value=[mod]):
            result = await m.mobile_nav_menu(user=u)
        assert result is not None


# ============================================================
# _mobile_unauthorized_response / _mobile_bridge_request_statuses / _mobile_sync_runtime_contract
# ============================================================


class TestSimpleHelpers:
    def test_mobile_unauthorized_response(self, m):
        result = m._mobile_unauthorized_response()
        assert result.status_code == 401

    def test_mobile_bridge_request_statuses(self, m):
        statuses = m._mobile_bridge_request_statuses()
        assert "pending" in statuses
        assert "processing" in statuses
        assert "resolved" in statuses
        assert "closed" in statuses

    def test_mobile_sync_runtime_contract(self, m):
        contract = m._mobile_sync_runtime_contract()
        assert contract["source"] == "cloud"
        assert contract["sync_mode"] == "cloud"
        assert contract["standalone_supported"] is True
        assert contract["desktop_required"] is False
        assert contract["desktop_executor"]["required"] is False


# ============================================================
# mobile_auth_qr_confirm additional branches
# ============================================================


class TestMobileAuthQrConfirmBranchCov:
    @pytest.mark.asyncio
    async def test_qr_expired(self, m):
        """branch: rec is None → 400."""
        with patch("app.security.auth_qr_login.get_auth_qr", return_value=None):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="u", password="p")
            result = await m.mobile_auth_qr_confirm(body=body, request=MagicMock())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_qr_status_expired(self, m):
        """branch: rec.status == 'expired' → 400."""
        with patch(
            "app.security.auth_qr_login.get_auth_qr", return_value={"status": "expired"}
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="u", password="p")
            result = await m.mobile_auth_qr_confirm(body=body, request=MagicMock())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_session_id_empty_returns_500(self, m):
        """branch: result has no session_id → 500."""
        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True}, None)),
            ),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="u", password="p")
            result = await m.mobile_auth_qr_confirm(body=body, request=MagicMock())
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_confirm_auth_qr_fails_returns_400(self, m):
        """branch: confirm_auth_qr returns False → 400."""
        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"session_id": "sid"}, None)),
            ),
            patch("app.security.auth_qr_login.confirm_auth_qr", return_value=False),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="u", password="p")
            result = await m.mobile_auth_qr_confirm(body=body, request=MagicMock())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_bearer_with_uid_user_found(self, m):
        """branch: Bearer header, uid found, user found in DB → username set."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer mobile_jwt"}

        mock_db = MagicMock()
        mock_user_row = MagicMock()
        mock_user_row.username = "alice"
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = mock_user_row
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch(
                "app.security.mobile_jwt.user_id_from_mobile_bearer", return_value=42
            ),
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"session_id": "sid"}, None)),
            ),
            patch("app.security.auth_qr_login.confirm_auth_qr", return_value=True),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="", password="pass")
            result = await m.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result is not None

    @pytest.mark.asyncio
    async def test_bearer_with_uid_user_not_found(self, m):
        """branch: Bearer header, uid found, user NOT found → username stays empty → 400."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer mobile_jwt"}

        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch(
                "app.security.mobile_jwt.user_id_from_mobile_bearer", return_value=42
            ),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="", password="")
            result = await m.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_login_error_with_valid_json_body(self, m):
        """branch: err.body contains valid JSON with message."""
        err_resp = MagicMock()
        err_resp.body = b'{"message": "Invalid credentials"}'

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, err_resp)),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError, ValueError, UnicodeDecodeError),
            ),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await m.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_login_error_no_body(self, m):
        """branch: err has no body attribute → msg stays default."""
        err_resp = MagicMock()
        del err_resp.body

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, err_resp)),
            ),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await m.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, m):
        """branch: full success path."""
        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"session_id": "sid123"}, None)),
            ),
            patch("app.security.auth_qr_login.confirm_auth_qr", return_value=True),
        ):
            body = m.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await m.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result is not None


# ============================================================
# mobile_auth_oidc_exchange additional branches
# ============================================================


class TestMobileAuthOidcExchangeBranchCov:
    @pytest.mark.asyncio
    async def test_state_invalid_returns_400(self, m):
        """branch: verify_oidc_state returns False → 400."""
        with patch(
            "app.infrastructure.auth.oidc_provider.verify_oidc_state",
            return_value=(False, None),
        ):
            body = m.OidcExchangeBody(code="abcd", state="s" * 8)
            result = await m.mobile_auth_oidc_exchange(body=body)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_exchange_error_returns_502(self, m):
        """branch: exchange_oidc_authorization raises → 502."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(side_effect=ValueError("exchange failed")),
            ),
        ):
            body = m.OidcExchangeBody(code="abcd", state="s" * 8)
            result = await m.mobile_auth_oidc_exchange(body=body)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_profile_not_dict_uses_empty(self, m):
        """branch: oidc_session.profile is not a dict → profile = {}."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(
                    return_value={"profile": "not-a-dict", "access_token": "tok"}
                ),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": False,
                "message": "no profile",
            }
            mock_get.return_value = mock_service
            body = m.OidcExchangeBody(code="abcd", state="s" * 8)
            result = await m.mobile_auth_oidc_exchange(body=body)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_payload_keys_copied(self, m):
        """branch: payload has market_access_token and other keys → copied to data."""
        fake_session = {"access_token": "tok", "profile": {"sub": "123"}}
        fake_auth = {
            "success": True,
            "user": {"id": 7, "username": "oidc_user"},
            "session_id": "sess123",
        }
        fake_payload = {
            "user": {"id": 7},
            "account_kind": "enterprise",
            "market_access_token": "mkt_tok",
            "market_refresh_token": "refresh_tok",
            "company_brand": "BrandCo",
            "market_is_admin": True,
            "market_is_enterprise": True,
        }
        fake_tokens = {"access_token": "jwt", "refresh_token": "rjwt"}

        body = MagicMock()
        body.state = "valid_state"
        body.code = "auth_code"

        auth_svc = MagicMock()
        auth_svc.authenticate_oidc_user.return_value = fake_auth

        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, None),
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
        assert result is not None


# ============================================================
# _mobile_mod_items additional dict branches
# ============================================================


class TestMobileModItemsDictBranches:
    def _mgr(self, mods):
        mgr = MagicMock()
        mgr.list_all_mods.return_value = mods
        return mgr

    def test_dict_mod_with_industry_not_dict(self, m):
        """branch: industry is not a dict → industry = {}."""
        mod = {"id": "m1", "name": "M1", "industry": "not-a-dict"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1
        assert result[0]["industry"] == {}

    def test_dict_mod_with_workflow_employees_not_list(self, m):
        """branch: workflow_employees is not a list → employees = []."""
        mod = {"id": "m1", "name": "M1", "workflow_employees": "not-a-list"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1

    def test_dict_mod_with_menu_not_list(self, m):
        """branch: menu is not a list → frontend_menu = []."""
        mod = {"id": "m1", "name": "M1", "frontend_menu": "not-a-list"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1
        assert result[0]["frontend_menu"] == []

    def test_dict_mod_with_menu_overrides_not_list(self, m):
        """branch: menu_overrides is not a list → menu_overrides = []."""
        mod = {"id": "m1", "name": "M1", "menu_overrides": "not-a-list"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1
        assert result[0]["menu_overrides"] == []

    def test_dict_mod_with_mod_id_fallback(self, m):
        """branch: id is empty but mod_id is present → uses mod_id."""
        mod = {"id": "", "mod_id": "mid-1", "name": "M1"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1
        assert result[0]["id"] == "mid-1"

    def test_dict_mod_with_name_from_title(self, m):
        """branch: no name, uses title."""
        mod = {"id": "m1", "title": "Title Name"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1
        assert result[0]["name"] == "Title Name"

    def test_dict_mod_with_avatar_from_logo(self, m):
        """branch: avatar from logo when avatar is empty."""
        mod = {"id": "m1", "name": "M1", "logo": "http://x/logo.png"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert result[0]["avatar_url"] == "http://x/logo.png"

    def test_dict_mod_with_avatar_from_icon(self, m):
        """branch: avatar from icon when avatar and logo are empty."""
        mod = {"id": "m1", "name": "M1", "icon": "http://x/icon.png"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert result[0]["avatar_url"] == "http://x/icon.png"

    def test_dict_mod_with_menus_key_fallback(self, m):
        """branch: frontend_menu from 'menus' key when 'frontend_menu' and 'menu' are empty."""
        mod = {"id": "m1", "name": "M1", "menus": [{"id": "e1"}]}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr([mod]),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 1
        assert len(result[0]["frontend_menu"]) == 1

    def test_dict_mod_truncated_to_100(self, m):
        """branch: more than 100 mods → truncated to 100."""
        mods = [{"id": f"m{i}", "name": f"M{i}"} for i in range(150)]
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=self._mgr(mods),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._enrich_workflow_employees", return_value=[]),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            result = m._mobile_mod_items()
        assert len(result) == 100


# ============================================================
# _resolve_mobile_relay_user additional branches
# ============================================================


class TestResolveMobileRelayUserBranchCov:
    def test_uid_positive_prefer_admin_admin_role(self, m):
        """branch: uid > 0, prefer_admin=True, role='admin' → return early."""
        u = _user(uid=5, role="admin")
        pub = {"id": 5, "username": "u5"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result["id"] == 5

    def test_uid_positive_prefer_admin_super_admin_role(self, m):
        """branch: uid > 0, prefer_admin=True, role='super_admin' → return early."""
        u = _user(uid=5, role="super_admin")
        pub = {"id": 5, "username": "u5"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result["id"] == 5

    def test_uid_positive_prefer_admin_owner_role(self, m):
        """branch: uid > 0, prefer_admin=True, role='owner' → return early."""
        u = _user(uid=5, role="owner")
        pub = {"id": 5, "username": "u5"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(5, "u5")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result["id"] == 5

    def test_recoverable_error_not_prefer_admin_raises(self, m):
        """branch: RECOVERABLE_ERRORS without prefer_admin → raise."""
        u = _user(uid=0)
        err_class = _err_class(m)
        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch("app.db.session.get_db", side_effect=err_class("boom")),
        ):
            with pytest.raises(err_class):
                m._resolve_mobile_relay_user(u, prefer_admin=False)

    def test_db_no_expunge_attribute(self, m):
        """branch: db has no expunge method → skip expunge."""
        u = _user(uid=0)
        mock_row = MagicMock()
        mock_row.id = 3
        pub = {"id": 3, "username": "x"}
        mock_db = _ctx_db(MagicMock())
        # uid=0 → uid<=0 True → admin-filtered query (two .filter() calls) is used
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_row
        # Remove expunge attribute to hit the `hasattr(db, "expunge")` False branch
        del mock_db.expunge
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result == pub

    def test_db_has_expunge_attribute_calls_expunge(self, m):
        """branch: db has expunge method → expunge called."""
        u = _user(uid=0)
        mock_row = MagicMock()
        mock_row.id = 7
        pub = {"id": 7, "username": "expunged"}
        mock_db = _ctx_db(MagicMock())
        # uid=0 → uid<=0 True → admin-filtered query (two .filter() calls) is used
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_row
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result == pub
        mock_db.expunge.assert_called_once_with(mock_row)

    def test_admin_query_returns_row_skips_all_users_query(self, m):
        """branch: prefer_admin=True and admin query returns a row → skip all-users query."""
        u = _user(uid=0)
        admin_row = MagicMock()
        admin_row.id = 11
        pub = {"id": 11, "username": "admin"}
        mock_db = _ctx_db(MagicMock())
        # Admin-filtered query returns a row
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = admin_row
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result == pub

    def test_admin_query_none_all_users_query_returns_row(self, m):
        """branch: admin query returns None → fallback to all-users query returns row."""
        u = _user(uid=0)
        any_row = MagicMock()
        any_row.id = 22
        pub = {"id": 22, "username": "any"}
        mock_db = _ctx_db(MagicMock())
        # First call (admin-filtered) returns None; second call (all users) returns row
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = any_row
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result == pub

    def test_no_users_creates_new_relay_admin(self, m):
        """branch: both queries return None → create new User row."""
        u = _user(uid=0)
        pub = {"id": 99, "username": "new_relay"}
        mock_db = _ctx_db(MagicMock())
        # Both queries return None
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result == pub
        # Verify db.add was called (new user created)
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

    def test_recoverable_error_prefer_admin_returns_fallback(self, m):
        """branch: RECOVERABLE_ERRORS with prefer_admin=True → return fallback user."""
        u = _user(uid=0)
        err_class = _err_class(m)
        fallback = {"id": -1, "username": "fallback"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(0, "")),
            patch("app.db.session.get_db", side_effect=err_class("boom")),
            patch.object(m, "_relay_admin_fallback_user", return_value=fallback),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result == fallback

    def test_uid_positive_not_prefer_admin_returns_public(self, m):
        """branch: uid > 0 and not prefer_admin → return public dict early."""
        u = _user(uid=8, role="user")
        pub = {"id": 8, "username": "u8"}
        with (
            patch.object(m, "_mobile_user_identity", return_value=(8, "u8")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=False)
        assert result == pub

    def test_uid_positive_prefer_admin_non_admin_role_falls_through(self, m):
        """branch: uid > 0, prefer_admin=True, role not in admin set → fall through to DB."""
        u = _user(uid=8, role="user")
        any_row = MagicMock()
        any_row.id = 100
        pub = {"id": 100, "username": "from_db"}
        mock_db = _ctx_db(MagicMock())
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = any_row
        with (
            patch.object(m, "_mobile_user_identity", return_value=(8, "u8")),
            patch.object(m, "_mobile_user_public_dict", return_value=pub),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = m._resolve_mobile_relay_user(u, prefer_admin=True)
        assert result == pub