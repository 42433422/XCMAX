"""Branch-coverage tests for app.fastapi_routes.mobile_extensions.admin_helpers.

Target: cover all MISSING_BRANCHES listed in the task.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import helper — the module under test is a plain helper file; import directly.
# ---------------------------------------------------------------------------
import app.fastapi_routes.mobile_extensions.admin_helpers as ah
from app.fastapi_routes.mobile_extensions import constants as _const

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_request(
    authorization: str = "",
    headers: dict | None = None,
    cookies: dict | None = None,
):
    """Build a minimal fake Starlette Request-like object."""
    hdrs = {"Authorization": authorization}
    if headers:
        hdrs.update(headers)
    req = MagicMock()
    req.headers = hdrs
    req.cookies = cookies or {}
    return req


# ===========================================================================
# Lines 30-36  _market_profile_keys
# Missing: [34, 32]  — value is falsy → branch that skips append
# ===========================================================================


class TestMarketProfileKeys:
    def test_all_keys_present(self):
        row = {"pkg_id": "P1", "id": "I1", "name": "N1"}
        keys = ah._market_profile_keys(row)
        assert keys == ["p1", "i1", "n1"]

    def test_falsy_value_skips_append(self):
        """Branch [34→32]: value is empty/None → not appended."""
        row = {"pkg_id": "", "id": None, "name": "MyPkg"}
        keys = ah._market_profile_keys(row)
        # empty & None → compact_text gives "" → falsy → skipped
        assert keys == ["mypkg"]

    def test_empty_row(self):
        keys = ah._market_profile_keys({})
        assert keys == []


# ===========================================================================
# Lines 39-56  _admin_employee_match_keys
# Missing: [42, 49] — stored falsy → skip stored/base/parts block
#          [47, 49] — parts len != 2 or parts[1][:1] not digit → skip keys.append(parts[0])
# ===========================================================================


class TestAdminEmployeeMatchKeys:
    def test_no_stored_filename(self):
        """[42→49]: stored_filename absent/empty → skips lines 43-48."""
        raw = {}
        keys = ah._admin_employee_match_keys(raw, "emp-1", "Alice")
        assert "emp-1" in keys
        assert "alice" in keys
        # No stored key
        assert len(keys) == 2

    def test_stored_with_single_part(self):
        """[47→49]: parts after rsplit has len==1 → no parts[0] appended."""
        raw = {"stored_filename": "nodigit.xcemp"}
        keys = ah._admin_employee_match_keys(raw, "e", "n")
        # stored => "nodigit.xcemp", base="nodigit"  parts=["nodigit"] len==1 → skip
        assert "nodigit.xcemp" in keys
        assert "nodigit" in keys
        assert len(keys) == 4  # e, n, nodigit.xcemp, nodigit

    def test_stored_with_digit_prefix(self):
        """[47→48]: parts[1][:1].isdigit() True → parts[0] appended."""
        raw = {"stored_filename": "alice-001.xcemp"}
        keys = ah._admin_employee_match_keys(raw, "e", "n")
        assert "alice" in keys

    def test_stored_with_non_digit_suffix(self):
        """[47→49]: parts[1][:1] NOT digit → skip parts[0] append."""
        raw = {"stored_filename": "alice-beta.xcemp"}
        keys = ah._admin_employee_match_keys(raw, "e", "n")
        assert "alice" not in keys  # parts[1][:1]=="b" not digit

    def test_dedup(self):
        """Ensure duplicates are deduplicated in output."""
        raw = {"stored_filename": "e.xcemp"}
        keys = ah._admin_employee_match_keys(raw, "e", "e")
        # "e" appears as employee_id AND name AND base → dedup to 1
        assert keys.count("e") == 1


# ===========================================================================
# Lines 62-75  _index_market_ai_employee_profiles
# Missing: [65, 66] — row not a dict → continue
#          [69, 70] — material != "ai_employee" → continue
#          [71, 72] — artifact not in set → continue
# ===========================================================================


class TestIndexMarketAiEmployeeProfiles:
    def test_non_dict_row_skipped(self):
        """[65→66]: row is not a dict → skip."""
        result = ah._index_market_ai_employee_profiles(["not_a_dict", 42, None])
        assert result == {}

    def test_wrong_material_skipped(self):
        """[69→70]: material_category exists and != 'ai_employee'."""
        row = {"material_category": "product", "pkg_id": "P1"}
        result = ah._index_market_ai_employee_profiles([row])
        assert result == {}

    def test_wrong_artifact_skipped(self):
        """[71→72]: artifact set but not in allowed set."""
        row = {
            "material_category": "ai_employee",
            "artifact": "other_thing",
            "pkg_id": "P1",
        }
        result = ah._index_market_ai_employee_profiles([row])
        assert result == {}

    def test_valid_row_indexed(self):
        row = {
            "material_category": "ai_employee",
            "artifact": "mod",
            "pkg_id": "P1",
            "name": "Alice",
        }
        result = ah._index_market_ai_employee_profiles([row])
        assert "p1" in result
        assert "alice" in result

    def test_empty_material_passes(self):
        """material is empty string → falsy → condition skipped → included."""
        row = {"material_category": "", "artifact": "", "pkg_id": "X1"}
        result = ah._index_market_ai_employee_profiles([row])
        assert "x1" in result


# ===========================================================================
# Lines 145-162  _apply_market_profile
# Missing: [145, 146] — profile is None/falsy → first branch (not the else)
# ===========================================================================


class TestApplyMarketProfile:
    def test_profile_none_sets_admin_fields(self):
        """[145→146]: profile is falsy → update with admin defaults."""
        item: dict = {}
        ah._apply_market_profile(item, None, market_connected=False)
        assert item["profile_source"] == "admin"
        assert item["market_connected"] is False
        assert item["market_pkg_id"] == ""

    def test_profile_present_sets_market_fields(self):
        """[145→163]: profile truthy → update with market data."""
        item: dict = {}
        profile = {
            "pkg_id": "P1",
            "name": "Alice",
            "description": "desc",
            "version": "1.0",
            "author": "Bob",
            "industry": "tech",
            "material_category": "ai_employee",
            "license_scope": "commercial",
            "security_level": "L1",
            "avatar": "http://img",
        }
        ah._apply_market_profile(item, profile, market_connected=True)
        assert item["profile_source"] == "ai_market"
        assert item["market_connected"] is True
        # _market_profile_text uses _compact_text which does NOT lowercase
        assert item["market_pkg_id"] == "P1"


# ===========================================================================
# Lines 207-218  _load_admin_duty_records
# Missing: [202, 203] — path added loop [202→203 every iter]
#          [202, 204] — loop exits (202→204) — after loop
#          [208, 209] — path.is_file() True → try to parse
#          [208, 218] — path.is_file() False → continue (208→218 = continue)
#          [210, 211] — path.is_file() True (branch taken)
#          [210, 212] — path.is_file() False (branch NOT taken)
#          [214, 208] — back to loop (continue in good path? no — return)
#          [214, 215] — packages is list → return
# ===========================================================================


class TestLoadAdminDutyRecords:
    def test_no_file_returns_empty(self):
        """All paths are_file False → empty list returned."""
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[]
        ):
            result = ah._load_admin_duty_records()
        assert result == []

    def test_file_exists_valid_json(self):
        """[210→211, 214→215]: file found, valid packages list returned."""
        from pathlib import Path

        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = json.dumps(
            {"packages": [{"id": "e1"}, {"id": "e2"}]}
        )
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[mock_path]
        ):
            result = ah._load_admin_duty_records()
        assert len(result) == 2

    def test_file_not_exists_continues(self):
        """[210→212]: is_file False → continue to next."""
        from pathlib import Path

        bad = MagicMock(spec=Path)
        bad.is_file.return_value = False
        good = MagicMock(spec=Path)
        good.is_file.return_value = True
        good.read_text.return_value = json.dumps({"packages": [{"id": "e1"}]})
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[bad, good]
        ):
            result = ah._load_admin_duty_records()
        assert len(result) == 1

    def test_oserror_logged_continues(self):
        """OSError → warning logged, loop continues, returns []."""
        from pathlib import Path

        bad = MagicMock(spec=Path)
        bad.is_file.return_value = True
        bad.read_text.side_effect = OSError("permission denied")
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[bad]
        ):
            result = ah._load_admin_duty_records()
        assert result == []

    def test_json_decode_error_continues(self):
        """JSONDecodeError → warning logged, returns []."""
        from pathlib import Path

        bad = MagicMock(spec=Path)
        bad.is_file.return_value = True
        bad.read_text.return_value = "not valid json{"
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[bad]
        ):
            result = ah._load_admin_duty_records()
        assert result == []

    def test_packages_not_list_skips(self):
        """packages is not a list → skip, return []."""
        from pathlib import Path

        p = MagicMock(spec=Path)
        p.is_file.return_value = True
        p.read_text.return_value = json.dumps({"packages": "not_a_list"})
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[p]
        ):
            result = ah._load_admin_duty_records()
        assert result == []

    def test_non_dict_packages_filtered(self):
        """packages list with non-dict entries → filtered out."""
        from pathlib import Path

        p = MagicMock(spec=Path)
        p.is_file.return_value = True
        p.read_text.return_value = json.dumps(
            {"packages": [{"id": "ok"}, "bad", 42]}
        )
        with patch.object(
            ah, "_candidate_duty_registry_paths", return_value=[p]
        ):
            result = ah._load_admin_duty_records()
        assert result == [{"id": "ok"}]


# ===========================================================================
# Lines 224-227  _employee_text
# Missing: [225, 226] — employee is dict → use .get
#          [225, 227] — employee not dict → use getattr
# ===========================================================================


class TestEmployeeText:
    def test_dict_employee(self):
        """[225→226]: employee is dict."""
        emp = {"label": "Alice"}
        assert ah._employee_text(emp, "label") == "Alice"

    def test_object_employee(self):
        """[225→227]: employee is object with attr."""
        emp = SimpleNamespace(label="Bob")
        assert ah._employee_text(emp, "label") == "Bob"

    def test_object_missing_attr(self):
        """Employee object without attr → getattr default "" → compact_text ""."""
        emp = SimpleNamespace()
        assert ah._employee_text(emp, "label") == ""


# ===========================================================================
# Lines 230-245  _workflow_employee_match_keys
# Missing: [240, 241] — branch: normalized is truthy AND not in seen → append
#          [240, 245] — loop exits normally (all keys exhausted)
#          [242, 240] — normalized already in seen → skip, back to loop top
#          [242, 243] — normalized falsy → skip
# ===========================================================================


class TestWorkflowEmployeeMatchKeys:
    def test_unique_keys(self):
        """[240→241, 240→245]: all keys unique → all appended."""
        emp = {"id": "A", "label": "B", "name": "C", "panel_title": "D"}
        keys = ah._workflow_employee_match_keys("modX", emp)
        # modX + a + b + c + d = 5 unique
        assert len(keys) == 5

    def test_duplicate_keys_deduped(self):
        """[242→240]: key already in seen → skip."""
        emp = {"id": "same", "label": "same", "name": "other", "panel_title": ""}
        keys = ah._workflow_employee_match_keys("same", emp)
        # "same" from mod_id, id, label → only 1 entry; "other" → 1 entry; "" skipped
        assert keys.count("same") == 1
        assert "other" in keys

    def test_empty_key_skipped(self):
        """[242→243]: normalized is falsy ("") → not appended."""
        emp = {"id": "", "label": "", "name": "", "panel_title": ""}
        keys = ah._workflow_employee_match_keys("", emp)
        assert keys == []


# ===========================================================================
# Lines 248-265  _workflow_employee_to_dict
# Missing: [249, 250] — employee is dict → return dict(employee)
#          [249, 251] — employee NOT dict → iterate attrs
#          [252, 262] — for loop body  [252→262 = hitting 'for' start from inside]
#          [252, 265] — loop exits (for exhausted)
#          [263, 252] — value is None → don't add, continue loop
#          [263, 264] — value is not None → add to out
# ===========================================================================


class TestWorkflowEmployeeToDict:
    def test_dict_passthrough(self):
        """[249→250]: dict employee → copied dict returned."""
        emp = {"id": "X", "name": "Y"}
        result = ah._workflow_employee_to_dict(emp)
        assert result == {"id": "X", "name": "Y"}
        assert result is not emp  # copy

    def test_object_with_attrs(self):
        """[249→251, 263→264]: object with some attrs set."""
        emp = SimpleNamespace(
            id="obj-1",
            label="L",
            name="N",
            panel_title="PT",
            panel_summary=None,  # None → not included
            api_base_path="/api",
            phone_channel=None,
            workflow_placeholder=None,
        )
        result = ah._workflow_employee_to_dict(emp)
        assert result["id"] == "obj-1"
        assert result["label"] == "L"
        assert result["api_base_path"] == "/api"
        assert "panel_summary" not in result  # None excluded
        assert "phone_channel" not in result  # None excluded

    def test_object_all_none(self):
        """[263→252]: all getattr values are None → empty dict."""
        emp = SimpleNamespace(
            id=None,
            label=None,
            name=None,
            panel_title=None,
            panel_summary=None,
            api_base_path=None,
            phone_channel=None,
            workflow_placeholder=None,
        )
        result = ah._workflow_employee_to_dict(emp)
        assert result == {}

    def test_object_missing_attrs(self):
        """Attrs not present on object → getattr defaults to None → excluded."""
        emp = SimpleNamespace(id="x")  # only id
        result = ah._workflow_employee_to_dict(emp)
        assert result == {"id": "x"}


# ===========================================================================
# Lines 268-286  _enrich_workflow_employees
# Missing: [276, 277] — employees list has item
#          [279, 280] — market_profiles truthy → look up keys
#          [279, 284] — market_profiles falsy → skip lookup
#          [280, 281] — key found in market_profiles → profile set
#          [280, 284] — key not found → continue loop
#          [282, 280] — profile found → break from inner loop
#          [282, 283] — profile not found → back to inner loop top
# ===========================================================================


class TestEnrichWorkflowEmployees:
    def test_no_employees(self):
        result = ah._enrich_workflow_employees("mod1", [])
        assert result == []

    def test_no_market_profiles(self):
        """[279→284]: market_profiles is None → skip lookup."""
        emp = {"id": "e1", "label": "L", "name": "N", "panel_title": "PT"}
        result = ah._enrich_workflow_employees("mod1", [emp], market_profiles=None)
        assert len(result) == 1
        assert result[0]["profile_source"] == "admin"

    def test_market_profiles_key_hit(self):
        """[280→281, 282→280(break)]: key found → profile applied."""
        emp = {"id": "e1", "label": "L", "name": "N", "panel_title": "PT"}
        profiles = {
            "e1": {"pkg_id": "P1", "name": "MarketName", "description": "d"}
        }
        result = ah._enrich_workflow_employees(
            "mod1", [emp], market_profiles=profiles, market_connected=True
        )
        assert result[0]["profile_source"] == "ai_market"

    def test_market_profiles_key_miss(self):
        """[280→284, 282→283(continue)]: key not found → profile stays None."""
        emp = {"id": "e1", "label": "L", "name": "N", "panel_title": "PT"}
        profiles = {"other_key": {"pkg_id": "P2"}}
        result = ah._enrich_workflow_employees(
            "mod1", [emp], market_profiles=profiles
        )
        assert result[0]["profile_source"] == "admin"

    def test_empty_market_profiles_dict(self):
        """[279→284]: market_profiles is empty dict → falsy → skip lookup."""
        emp = {"id": "e1", "label": "L", "name": "N", "panel_title": "PT"}
        result = ah._enrich_workflow_employees("mod1", [emp], market_profiles={})
        assert result[0]["profile_source"] == "admin"


# ===========================================================================
# Lines 292-322  _mobile_session_meta
# Missing: [300, 301] — authorization starts with "Bearer "
#          [300, 311] — authorization does NOT start with "Bearer "
#          [302, 303] — payload truthy → fill jwt_meta
#          [302, 311] — payload falsy → skip jwt_meta
#          [311, 312] — sid is empty → try session_id_from_request
#          [311, 318] — sid truthy → skip session_id_from_request block
#          [318, 319] — sid truthy → call load_session_account_meta
#          [318, 322] — sid falsy → return jwt_meta
#          [320, 321] — meta truthy → return meta
#          [320, 322] — meta falsy → return jwt_meta
# ===========================================================================


class TestMobileSessionMeta:
    # NOTE: _mobile_session_meta uses LOCAL imports inside the function body,
    # so we must patch at the actual source module, not at admin_helpers.

    def test_bearer_with_valid_payload_and_sid(self):
        """[300→301, 302→303, 311→318(sid set), 318→319, 320→321]."""
        req = _make_request("Bearer validtoken")
        payload = {"session_id": "sid-abc", "account_kind": "admin", "username": "alice"}
        meta_result = {"account_kind": "admin", "username": "alice"}
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=payload),
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="sid-abc",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=meta_result,
            ),
        ):
            result = ah._mobile_session_meta(req)
        assert result == meta_result

    def test_bearer_with_invalid_payload(self):
        """[300→301, 302→311(payload falsy), 311→312(sid empty)]."""
        req = _make_request("Bearer invalidtoken")
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=None),
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            result = ah._mobile_session_meta(req)
        # No sid → returns jwt_meta which is {}
        assert result == {}

    def test_no_authorization_header(self):
        """[300→311]: no bearer → skip bearer block; sid from session fallback."""
        req = _make_request("")
        with (
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="session-xyz",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise"},
            ),
        ):
            result = ah._mobile_session_meta(req)
        assert result == {"account_kind": "enterprise"}

    def test_session_id_from_request_raises_attribute_error(self):
        """[311→312]: session_id_from_request raises AttributeError → sid=""."""
        req = _make_request("")
        with (
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                side_effect=AttributeError("no cookies"),
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            result = ah._mobile_session_meta(req)
        # sid="" → 318→322 → return jwt_meta {}
        assert result == {}

    def test_session_id_from_request_raises_type_error(self):
        """[311→312]: session_id_from_request raises TypeError → sid=""."""
        req = _make_request("")
        with (
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                side_effect=TypeError("wrong type"),
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            result = ah._mobile_session_meta(req)
        assert result == {}

    def test_sid_set_meta_falsy_returns_jwt_meta(self):
        """[318→319, 320→322]: sid set, load_session_account_meta returns falsy."""
        req = _make_request("Bearer tok")
        payload = {"session_id": "s1", "account_kind": "admin", "username": "u"}
        with (
            patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=payload),
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="s1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,  # falsy → return jwt_meta
            ),
        ):
            result = ah._mobile_session_meta(req)
        # returns jwt_meta
        assert result.get("session_id") == "s1"
        assert result.get("account_kind") == "admin"


# ===========================================================================
# Lines 325-345  _require_mobile_admin
# Missing: [330, 331] — user is None → 401
#          [330, 335] — user is not None → proceed
#          [340, 341] — jwt_or_session_admin False → 403
#          [340, 345] — jwt_or_session_admin True → return (meta, None)
# ===========================================================================


class TestRequireMobileAdmin:
    def test_user_none_returns_401(self):
        """[330→331]: user is None."""
        req = _make_request()
        meta, err = ah._require_mobile_admin(req, user=None)
        assert meta == {}
        assert err is not None
        assert err.status_code == 401

    def test_admin_user_passes(self):
        """[330→335, 340→345]: user present, account_kind==admin."""
        req = _make_request()
        user = SimpleNamespace(role="admin")
        session_meta = {"account_kind": "admin", "market_is_admin": True}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin(req, user=user)
        assert err is None

    def test_non_admin_returns_403(self):
        """[330→335, 340→341]: user present but not admin."""
        req = _make_request()
        user = SimpleNamespace(role="user")
        session_meta = {"account_kind": "personal", "market_is_admin": False}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin(req, user=user)
        assert err is not None
        assert err.status_code == 403

    def test_admin_role_via_role_attr(self):
        """account_kind==admin + role in {admin} → passes."""
        req = _make_request()
        user = SimpleNamespace(role="admin")
        session_meta = {"account_kind": "admin", "market_is_admin": False}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin(req, user=user)
        assert err is None


# ===========================================================================
# Lines 348-376  _require_mobile_admin_or_enterprise
# Missing: [356, 357] — user is None → 401
#          [356, 361] — user not None → proceed
#          [364, 365] — account_kind empty → derive from role
#          [364, 366] — account_kind present → skip derive
#          [366, 367] — account_kind == "enterprise" → pass (None)
#          [366, 368] — account_kind != "enterprise" → check admin
#          [368, 372] — admin check passes → return (meta, None)
#          [368, 373] — admin check fails → 403
# ===========================================================================


class TestRequireMobileAdminOrEnterprise:
    def test_user_none_returns_401(self):
        """[356→357]: user is None."""
        req = _make_request()
        meta, err = ah._require_mobile_admin_or_enterprise(req, user=None)
        assert meta == {}
        assert err is not None
        assert err.status_code == 401

    def test_enterprise_role_passes(self):
        """[364→365(derive enterprise), 366→367]: role=enterprise → pass."""
        req = _make_request()
        user = SimpleNamespace(role="enterprise")
        session_meta = {"account_kind": ""}  # empty → derive
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin_or_enterprise(req, user=user)
        assert err is None

    def test_account_kind_enterprise_passes(self):
        """[364→366, 366→367]: account_kind from meta is 'enterprise'."""
        req = _make_request()
        user = SimpleNamespace(role="user")
        session_meta = {"account_kind": "enterprise"}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin_or_enterprise(req, user=user)
        assert err is None

    def test_admin_account_kind_passes(self):
        """[366→368, 368→372]: account_kind==admin with market_is_admin."""
        req = _make_request()
        user = SimpleNamespace(role="admin")
        session_meta = {"account_kind": "admin", "market_is_admin": True}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin_or_enterprise(req, user=user)
        assert err is None

    def test_personal_account_kind_returns_403(self):
        """[366→368, 368→373]: account_kind personal → 403."""
        req = _make_request()
        user = SimpleNamespace(role="user")
        session_meta = {"account_kind": "personal", "market_is_admin": False}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin_or_enterprise(req, user=user)
        assert err is not None
        assert err.status_code == 403

    def test_empty_role_derives_personal(self):
        """[364→365]: account_kind empty, role is not 'enterprise' → 'personal'."""
        req = _make_request()
        user = SimpleNamespace(role="user")
        session_meta = {"account_kind": ""}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin_or_enterprise(req, user=user)
        # personal → 403
        assert err is not None
        assert err.status_code == 403

    def test_admin_portal_role_passes(self):
        """[368→372]: account_kind=='admin_portal', role in set."""
        req = _make_request()
        user = SimpleNamespace(role="admin_portal")
        session_meta = {"account_kind": "admin_portal", "market_is_admin": False}
        with patch.object(ah, "_mobile_session_meta", return_value=session_meta):
            meta, err = ah._require_mobile_admin_or_enterprise(req, user=user)
        assert err is None


# ===========================================================================
# Lines 379-401  _mobile_request_user_id
# Missing: [386, 390] — Bearer present, uid falsy → fall through to attr loop
#          [390, 401] — loop exhausted → return 0
#          [399, 390] — uid_int > 0 → return uid_int (not 390 again)
# ===========================================================================


class TestMobileRequestUserId:
    # NOTE: _mobile_request_user_id imports user_id_from_mobile_bearer locally.
    # We patch at the actual source module.

    def test_bearer_uid_returned(self):
        """[386→390(not taken)]: bearer uid truthy → int(uid) returned."""
        req = _make_request("Bearer validtoken")
        with patch(
            "app.security.mobile_jwt.user_id_from_mobile_bearer",
            return_value=42,
        ):
            uid = ah._mobile_request_user_id(req, user=None)
        assert uid == 42

    def test_bearer_uid_zero_falls_through_to_attrs(self):
        """[386→390]: bearer uid is 0/falsy → check user attrs."""
        req = _make_request("Bearer weaktoken")
        user = SimpleNamespace(id=99, user_id=99)
        with patch(
            "app.security.mobile_jwt.user_id_from_mobile_bearer",
            return_value=0,
        ):
            uid = ah._mobile_request_user_id(req, user=user)
        # falls through → user.id = 99
        assert uid == 99

    def test_no_bearer_uses_user_id_attr(self):
        """[390→401]: no bearer, user has id."""
        req = _make_request("")  # no bearer
        user = SimpleNamespace(id=7, user_id=7)
        uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 7

    def test_no_bearer_no_user_returns_zero(self):
        """[390→401]: no bearer, user=None → return 0."""
        req = _make_request("")
        uid = ah._mobile_request_user_id(req, user=None)
        assert uid == 0

    def test_user_attr_none_skips(self):
        """uid is None → int(None or 0) = 0 → not > 0 → loop continues."""
        req = _make_request("")
        user = SimpleNamespace(id=None, user_id=None)
        uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 0

    def test_bearer_import_error_falls_through(self):
        """ImportError in bearer block → except → fall through."""
        req = _make_request("Bearer sometoken")
        user = SimpleNamespace(id=5, user_id=5)
        with patch(
            "app.security.mobile_jwt.user_id_from_mobile_bearer",
            side_effect=ImportError("no mod"),
        ):
            uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 5

    def test_bearer_value_error_falls_through(self):
        """ValueError in bearer block → except → fall through."""
        req = _make_request("Bearer sometoken")
        user = SimpleNamespace(id=3, user_id=3)
        with patch(
            "app.security.mobile_jwt.user_id_from_mobile_bearer",
            side_effect=ValueError("bad value"),
        ):
            uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 3

    def test_uid_int_zero_continues_loop(self):
        """uid_int == 0 → not > 0 → continue to next attr."""
        req = _make_request("")
        user = SimpleNamespace(id=0, user_id=10)
        uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 10

    def test_uid_int_conversion_error(self):
        """int("abc") → ValueError → uid_int = 0 → continue."""
        req = _make_request("")
        user = SimpleNamespace(id="not_an_int", user_id=5)
        uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 5

    def test_no_bearer_prefix(self):
        """Authorization header present but not starting with 'Bearer '."""
        req = _make_request("Basic abc123")
        user = SimpleNamespace(id=11, user_id=11)
        uid = ah._mobile_request_user_id(req, user=user)
        assert uid == 11

    def test_getattr_raises_attribute_error(self):
        """getattr raises AttributeError → continue loop."""
        req = _make_request("")

        class BadUser:
            @property
            def id(self):
                raise AttributeError("nope")

            @property
            def user_id(self):
                raise AttributeError("nope")

        uid = ah._mobile_request_user_id(req, user=BadUser())
        assert uid == 0
