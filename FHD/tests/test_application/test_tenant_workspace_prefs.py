"""Branch coverage tests for app.application.tenant_workspace_prefs.

Covers missing branches in:
- _safe_positive_int (None/empty/zero/negative/non-numeric paths)
- resolve_workspace_owner_id (tenant/session/none paths, enrich errors)
- get_workspace_prefs (empty owner, empty raw, non-dict JSON, recoverable errors)
- _save_workspace_prefs (empty owner early return)
- patch_workspace_prefs (empty owner, disallowed keys, workflow_ai_employees merge edge cases)
- get_selected_industry_id (None owner, None raw, empty text, non-empty text)
- save_selected_industry (deprecation no-op)
"""

from __future__ import annotations

import json
import warnings
from unittest.mock import MagicMock, patch

import pytest

from app.application import tenant_workspace_prefs as prefs_mod
from app.application.tenant_workspace_prefs import (
    _safe_positive_int,
    get_selected_industry_id,
    get_workspace_prefs,
    patch_workspace_prefs,
    resolve_workspace_owner_id,
    save_selected_industry,
)


# ---------------------------------------------------------------------------
# Test fixture: in-memory preference service
# ---------------------------------------------------------------------------


class _FakePrefService:
    """In-memory preference service that mimics the real interface."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}
        self.get_call_count = 0
        self.set_call_count = 0

    def get_preference(self, user_id: str, preference_key: str) -> str | None:
        self.get_call_count += 1
        return self.store.get(user_id, {}).get(preference_key)

    def set_preference(
        self, user_id: str, preference_key: str, preference_value: str
    ) -> bool:
        self.set_call_count += 1
        self.store.setdefault(user_id, {})[preference_key] = preference_value
        return True


@pytest.fixture
def fake_pref_service(monkeypatch):
    """Install an in-memory preference service singleton."""
    svc = _FakePrefService()
    monkeypatch.setattr(
        "app.services.user_preference_service.get_user_preference_service",
        lambda: svc,
    )
    return svc


# ---------------------------------------------------------------------------
# _safe_positive_int
# ---------------------------------------------------------------------------


class TestSafePositiveInt:
    def test_none_returns_none(self):
        assert _safe_positive_int(None) is None

    def test_empty_string_returns_none(self):
        assert _safe_positive_int("") is None

    def test_whitespace_string_returns_none(self):
        assert _safe_positive_int("   ") is None

    def test_positive_int_string_returns_int(self):
        assert _safe_positive_int("42") == 42

    def test_positive_int_passthrough(self):
        assert _safe_positive_int(42) == 42

    def test_zero_returns_none(self):
        assert _safe_positive_int(0) is None

    def test_negative_returns_none(self):
        assert _safe_positive_int(-5) is None

    def test_negative_string_returns_none(self):
        assert _safe_positive_int("-1") is None

    def test_float_string_returns_int(self):
        # int("3.5") raises ValueError -> None
        assert _safe_positive_int("3.5") is None

    def test_non_numeric_string_returns_none(self):
        assert _safe_positive_int("abc") is None

    def test_list_raises_type_error_returns_none(self):
        assert _safe_positive_int([1, 2]) is None

    def test_dict_raises_type_error_returns_none(self):
        assert _safe_positive_int({"a": 1}) is None

    def test_strips_whitespace(self):
        assert _safe_positive_int("  7  ") == 7


# ---------------------------------------------------------------------------
# resolve_workspace_owner_id
# ---------------------------------------------------------------------------


class TestResolveWorkspaceOwnerId:
    def test_no_session_returns_none(self):
        request = MagicMock()
        with patch(
            "app.application.tenant_workspace_prefs.session_id_from_request",
            return_value=None,
        ):
            result = resolve_workspace_owner_id(request, user=None)
        assert result is None

    def test_session_but_no_user_returns_none(self):
        request = MagicMock()
        with patch(
            "app.application.tenant_workspace_prefs.session_id_from_request",
            return_value="sid-1",
        ):
            result = resolve_workspace_owner_id(request, user=None)
        assert result is None

    def test_tenant_id_returned_when_meta_has_tenant(self):
        request = MagicMock()
        user = MagicMock(id=5)

        def fake_enrich(sid, u):
            return {"tenant_id": "42", "local_user_id": "5"}

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=fake_enrich,
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "tenant:42"

    def test_session_user_id_when_no_tenant(self):
        request = MagicMock()
        user = MagicMock(id=99)

        def fake_enrich(sid, u):
            return {"tenant_id": None, "local_user_id": "99"}

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=fake_enrich,
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "session:99"

    def test_falls_back_to_meta_local_user_id_when_user_id_missing(self):
        request = MagicMock()
        user = MagicMock(spec=[])  # no id attribute
        # user.id will raise AttributeError; _safe_positive_int handles it

        def fake_enrich(sid, u):
            return {"tenant_id": None, "local_user_id": "7"}

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=fake_enrich,
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "session:7"

    def test_returns_none_when_no_ids_available(self):
        request = MagicMock()
        user = MagicMock(spec=[])  # no id

        def fake_enrich(sid, u):
            return {"tenant_id": None, "local_user_id": None}

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=fake_enrich,
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result is None

    def test_enrich_recoverable_error_suppressed(self):
        request = MagicMock()
        user = MagicMock(id=5)

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=RuntimeError("enrich failed"),
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        # Falls back to user.id since meta is empty
        assert result == "session:5"

    def test_enrich_key_error_suppressed(self):
        request = MagicMock()
        user = MagicMock(id=3)

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=KeyError("missing"),
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "session:3"

    def test_enrich_value_error_suppressed(self):
        request = MagicMock()
        user = MagicMock(id=8)

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=ValueError("bad value"),
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "session:8"

    def test_tenant_id_zero_falls_back_to_session(self):
        request = MagicMock()
        user = MagicMock(id=11)

        def fake_enrich(sid, u):
            return {"tenant_id": "0", "local_user_id": "11"}

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=fake_enrich,
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "session:11"

    def test_tenant_id_negative_falls_back_to_session(self):
        request = MagicMock()
        user = MagicMock(id=22)

        def fake_enrich(sid, u):
            return {"tenant_id": "-3", "local_user_id": "22"}

        with (
            patch(
                "app.application.tenant_workspace_prefs.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                side_effect=fake_enrich,
            ),
        ):
            result = resolve_workspace_owner_id(request, user=user)
        assert result == "session:22"


# ---------------------------------------------------------------------------
# get_workspace_prefs
# ---------------------------------------------------------------------------


class TestGetWorkspacePrefs:
    def test_empty_owner_returns_empty(self):
        assert get_workspace_prefs("") == {}

    def test_none_owner_returns_empty(self):
        assert get_workspace_prefs(None) == {}

    def test_whitespace_owner_returns_empty(self):
        assert get_workspace_prefs("   ") == {}

    def test_no_stored_preference_returns_empty(self, fake_pref_service):
        assert get_workspace_prefs("tenant:1") == {}

    def test_stored_dict_returned(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": "涂料"})
        }
        result = get_workspace_prefs("tenant:1")
        assert result == {"selected_industry_id": "涂料"}

    def test_stored_non_dict_json_returns_empty(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps([1, 2, 3])
        }
        assert get_workspace_prefs("tenant:1") == {}

    def test_stored_string_json_returns_empty(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps("just a string")
        }
        assert get_workspace_prefs("tenant:1") == {}

    def test_stored_null_json_returns_empty(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps(None)
        }
        assert get_workspace_prefs("tenant:1") == {}

    def test_invalid_json_returns_empty(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {"workspace_prefs": "{invalid json"}
        assert get_workspace_prefs("tenant:1") == {}

    def test_get_preference_raises_value_error_returns_empty(self, monkeypatch):
        class FailingService:
            def get_preference(self, user_id, preference_key):
                raise ValueError("db down")

        monkeypatch.setattr(
            "app.services.user_preference_service.get_user_preference_service",
            lambda: FailingService(),
        )
        assert get_workspace_prefs("tenant:1") == {}

    def test_get_preference_raises_key_error_returns_empty(self, monkeypatch):
        class FailingService:
            def get_preference(self, user_id, preference_key):
                raise KeyError("missing key")

        monkeypatch.setattr(
            "app.services.user_preference_service.get_user_preference_service",
            lambda: FailingService(),
        )
        assert get_workspace_prefs("tenant:1") == {}

    def test_get_preference_raises_runtime_error_returns_empty(self, monkeypatch):
        class FailingService:
            def get_preference(self, user_id, preference_key):
                raise RuntimeError("unexpected")

        monkeypatch.setattr(
            "app.services.user_preference_service.get_user_preference_service",
            lambda: FailingService(),
        )
        assert get_workspace_prefs("tenant:1") == {}


# ---------------------------------------------------------------------------
# patch_workspace_prefs
# ---------------------------------------------------------------------------


class TestPatchWorkspacePrefs:
    def test_empty_owner_returns_empty(self, fake_pref_service):
        result = patch_workspace_prefs("", {"selected_industry_id": "x"})
        assert result == {}
        assert fake_pref_service.set_call_count == 0

    def test_none_owner_returns_empty(self, fake_pref_service):
        result = patch_workspace_prefs(None, {"selected_industry_id": "x"})
        assert result == {}

    def test_whitespace_owner_returns_empty(self, fake_pref_service):
        result = patch_workspace_prefs("  ", {"selected_industry_id": "x"})
        assert result == {}

    def test_none_partial_returns_current(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": "old"})
        }
        result = patch_workspace_prefs("tenant:1", None)
        assert result == {"selected_industry_id": "old"}

    def test_empty_partial_returns_current(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": "old"})
        }
        result = patch_workspace_prefs("tenant:1", {})
        assert result == {"selected_industry_id": "old"}

    def test_disallowed_key_ignored(self, fake_pref_service):
        result = patch_workspace_prefs("tenant:1", {"forbidden_key": "evil"})
        assert result == {}
        # Should still save (empty) prefs
        assert fake_pref_service.set_call_count == 1

    def test_allowed_non_workflow_key_overwrites(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": "old"})
        }
        result = patch_workspace_prefs("tenant:1", {"selected_industry_id": "new"})
        assert result == {"selected_industry_id": "new"}

    def test_product_flow_completed_key(self, fake_pref_service):
        result = patch_workspace_prefs(
            "tenant:1", {"product_flow_completed": True}
        )
        assert result == {"product_flow_completed": True}

    def test_host_pack_acknowledged_key(self, fake_pref_service):
        result = patch_workspace_prefs(
            "tenant:1", {"host_pack_acknowledged": True}
        )
        assert result == {"host_pack_acknowledged": True}

    def test_industry_mod_id_key(self, fake_pref_service):
        result = patch_workspace_prefs(
            "tenant:1", {"industry_mod_id": "coating-mod"}
        )
        assert result == {"industry_mod_id": "coating-mod"}

    def test_workflow_ai_employees_merges_with_existing(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps(
                {"workflow_ai_employees": {"emp-a": True}}
            )
        }
        result = patch_workspace_prefs(
            "tenant:1", {"workflow_ai_employees": {"emp-b": False}}
        )
        assert result == {"workflow_ai_employees": {"emp-a": True, "emp-b": False}}

    def test_workflow_ai_employees_empty_emp_id_skipped(self, fake_pref_service):
        result = patch_workspace_prefs(
            "tenant:1",
            {"workflow_ai_employees": {"": True, "   ": False, "emp-a": True}},
        )
        assert result == {"workflow_ai_employees": {"emp-a": True}}

    def test_workflow_ai_employees_non_bool_value_skipped(self, fake_pref_service):
        result = patch_workspace_prefs(
            "tenant:1",
            {
                "workflow_ai_employees": {
                    "emp-a": True,
                    "emp-b": "yes",  # string, not bool -> skipped
                    "emp-c": 1,  # int, not bool -> skipped
                }
            },
        )
        assert result == {"workflow_ai_employees": {"emp-a": True}}

    def test_workflow_ai_employees_non_dict_value_ignored(self, fake_pref_service):
        # When value is not a dict, falls to else branch and stores as-is
        result = patch_workspace_prefs(
            "tenant:1", {"workflow_ai_employees": ["not", "a", "dict"]}
        )
        assert result == {"workflow_ai_employees": ["not", "a", "dict"]}

    def test_workflow_ai_employees_none_value_overwrites(self, fake_pref_service):
        # None is not a dict, so goes to else branch
        result = patch_workspace_prefs(
            "tenant:1", {"workflow_ai_employees": None}
        )
        assert result == {"workflow_ai_employees": None}

    def test_mixed_keys_partial(self, fake_pref_service):
        result = patch_workspace_prefs(
            "tenant:1",
            {
                "selected_industry_id": "涂料",
                "forbidden": "ignored",
                "workflow_ai_employees": {"emp-a": True},
                "industry_mod_id": "mod-1",
            },
        )
        assert result == {
            "selected_industry_id": "涂料",
            "workflow_ai_employees": {"emp-a": True},
            "industry_mod_id": "mod-1",
        }

    def test_workflow_ai_employees_existing_none_treated_as_empty(
        self, fake_pref_service
    ):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"workflow_ai_employees": None})
        }
        result = patch_workspace_prefs(
            "tenant:1", {"workflow_ai_employees": {"emp-a": True}}
        )
        assert result == {"workflow_ai_employees": {"emp-a": True}}

    def test_workflow_ai_employees_existing_not_dict_treated_as_empty(
        self, fake_pref_service
    ):
        # When existing stored value is a non-dict truthy value (e.g. string),
        # dict(value) raises ValueError. This test documents that behavior.
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"workflow_ai_employees": "invalid"})
        }
        with pytest.raises(ValueError):
            patch_workspace_prefs(
                "tenant:1", {"workflow_ai_employees": {"emp-a": True}}
            )


# ---------------------------------------------------------------------------
# get_selected_industry_id
# ---------------------------------------------------------------------------


class TestGetSelectedIndustryId:
    def test_none_owner_returns_none(self):
        assert get_selected_industry_id(None) is None

    def test_empty_owner_returns_none(self):
        assert get_selected_industry_id("") is None

    def test_no_prefs_returns_none(self, fake_pref_service):
        assert get_selected_industry_id("tenant:1") is None

    def test_prefs_without_key_returns_none(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"other_key": "value"})
        }
        assert get_selected_industry_id("tenant:1") is None

    def test_prefs_with_none_value_returns_none(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": None})
        }
        assert get_selected_industry_id("tenant:1") is None

    def test_prefs_with_empty_string_returns_none(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": ""})
        }
        assert get_selected_industry_id("tenant:1") is None

    def test_prefs_with_whitespace_string_returns_none(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": "   "})
        }
        assert get_selected_industry_id("tenant:1") is None

    def test_prefs_with_value_returns_stripped(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": "  涂料  "})
        }
        assert get_selected_industry_id("tenant:1") == "涂料"

    def test_prefs_with_int_value_returns_string(self, fake_pref_service):
        fake_pref_service.store["tenant:1"] = {
            "workspace_prefs": json.dumps({"selected_industry_id": 42})
        }
        # str(42).strip() = "42", which is truthy
        assert get_selected_industry_id("tenant:1") == "42"


# ---------------------------------------------------------------------------
# save_selected_industry (deprecated no-op)
# ---------------------------------------------------------------------------


class TestSaveSelectedIndustry:
    def test_returns_empty_dict(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = save_selected_industry("tenant:1", "涂料")
        assert result == {}

    def test_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            save_selected_industry("tenant:1", "涂料")
        assert len(caught) == 1
        assert issubclass(caught[0].category, DeprecationWarning)
        assert "deprecated" in str(caught[0].message)

    def test_with_industry_mod_id_still_noop(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = save_selected_industry(
                "tenant:1", "涂料", industry_mod_id="mod-1"
            )
        assert result == {}

    def test_does_not_write_to_storage(self, fake_pref_service):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            save_selected_industry("tenant:1", "涂料")
        assert fake_pref_service.set_call_count == 0
        assert "tenant:1" not in fake_pref_service.store
