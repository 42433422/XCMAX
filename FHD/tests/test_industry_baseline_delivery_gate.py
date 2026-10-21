"""Account-scoped deferral is not proof of delivery or runtime readiness."""

from unittest.mock import patch

import pytest

from app.application import private_mod_delivery_state as state
from app.mod_sdk.industry_baseline_plans import (
    build_industry_baseline_plan,
    delivery_statuses_for_session,
)

HOST = [
    "xcagi-planner-bridge",
    "xcagi-neuro-bus-bridge",
    "xcagi-erp-domain-bridge",
    "xcagi-planner-excel-tools",
    "xcagi-approval-bridge",
    "accessories-packaging-industry",
    "attendance-industry",
    "xcagi-core-workflow-employees",
    "xcagi-office-employee-pack-bridge",
]


def plan(status, installed=None):
    return build_industry_baseline_plan(
        "饰品包装",
        installed_mod_ids=HOST if installed is None else installed,
        entitled_mod_ids={"taiyangniao-pro"},
        account_username="SUNBIRD",
        delivery_statuses={"taiyangniao-pro": status},
    )


@pytest.mark.parametrize("status", ["production", "testing", "acceptance", "rework", "partial"])
def test_pending_private_delivery_is_deferred_not_delivered(status):
    result = plan(status)
    assert result["baseline_ready"]
    assert not result["full_stack_ready"]
    assert result["missing_account_custom_mod_ids"] == ["taiyangniao-pro"]
    assert "taiyangniao-pro" not in result["missing_required_mod_ids"]
    assert result["deferred_account_custom_mod_ids"] == ["taiyangniao-pro"]
    assert not result["account_delivery_seed_packages"]


@pytest.mark.parametrize("status", ["delivered", "unknown", "", "invalid"])
def test_delivered_or_unknown_missing_package_still_blocks(status):
    result = plan(status)
    assert not result["baseline_ready"]
    assert "taiyangniao-pro" in result["missing_required_mod_ids"]
    assert not result["deferred_account_custom_mod_ids"]


def test_installed_runtime_wins_over_stale_pending_status():
    result = plan("production", [*HOST, "sunbird-attendance-custom"])
    assert result["full_stack_ready"]
    assert not result["deferred_account_custom_mod_ids"]


def test_standard_employee_extension_still_required():
    result = plan("production", [mid for mid in HOST if mid != "xcagi-core-workflow-employees"])
    assert not result["baseline_ready"]
    assert "xcagi-core-workflow-employees" in result["missing_required_mod_ids"]


def binding():
    return {"market_user_id": 7, "username": "test-owner", "mod_ids": {"mine"}}


def project():
    return {
        "mod_id": "mine",
        "tracks": {
            "modules": {"status": "production", "nodes": {}},
            "employees": {"status": "production", "nodes": {}},
        },
    }


def call_statuses(monkeypatch, value=None, row=None):
    monkeypatch.setattr(
        "app.enterprise.private_delivery_binding.load_session_private_delivery_binding",
        lambda sid: binding() if value is None else value,
    )
    monkeypatch.setattr(
        "app.mod_sdk.customer_delivery.delivery_for_account_custom_mod",
        lambda mid: row
        or {"delivery_mode": "private_mod", "customer_account": "test-owner", "market_user_id": 7},
    )
    return delivery_statuses_for_session("current-session")


def test_identity_matched_private_project_only(monkeypatch):
    with patch.object(state, "account_projects", return_value=[project()]) as read:
        assert call_statuses(monkeypatch) == {"mine": "production"}
        read.assert_called_once_with("market:7", {"mine"}, strict=True)


@pytest.mark.parametrize("uid", [None, 0, -1, True, "7"])
def test_invalid_market_identity_does_not_read_projects(monkeypatch, uid):
    with patch.object(state, "account_projects") as read:
        assert call_statuses(monkeypatch, {**binding(), "market_user_id": uid}) == {}
        read.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"customer_account": "other"},
        {"market_user_id": 8},
        {"delivery_mode": "integrated"},
    ],
)
def test_mismatched_owner_or_nonprivate_mod_not_deferred(monkeypatch, overrides):
    row = {
        "delivery_mode": "private_mod",
        "customer_account": "test-owner",
        "market_user_id": 7,
        **overrides,
    }
    with patch.object(state, "account_projects") as read:
        assert call_statuses(monkeypatch, row=row) == {}
        read.assert_not_called()


@pytest.mark.parametrize(
    "content",
    [
        "bad json",
        "[]",
        '{"accounts": []}',
        '{"accounts": {"market:7": []}}',
        '{"accounts": {"market:7": {"projects": []}}}',
    ],
)
def test_corrupt_state_does_not_become_production(monkeypatch, tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    monkeypatch.setattr(state, "_state_path", lambda: path)
    with patch.object(state, "_write_state") as write:
        assert call_statuses(monkeypatch) == {}
        write.assert_not_called()
    assert path.read_text() == content


@pytest.mark.parametrize(
    "nodes", [[], {"node": {}}, {"node": None}, {"node": {"status": "invalid"}}]
)
def test_invalid_node_status_does_not_roll_up_to_production(monkeypatch, nodes):
    value = project()
    value["tracks"]["modules"]["nodes"] = nodes
    with patch.object(state, "account_projects", return_value=[value]):
        assert call_statuses(monkeypatch) == {}


def test_missing_state_defaults_without_writing(monkeypatch, tmp_path):
    path = tmp_path / "absent" / "state.json"
    monkeypatch.setattr(state, "_state_path", lambda: path)
    assert call_statuses(monkeypatch) == {"mine": "production"}
    assert not path.parent.exists()


def test_io_failure_is_unknown_not_pending(monkeypatch):
    with patch.object(state, "account_projects", side_effect=PermissionError("denied")):
        assert call_statuses(monkeypatch) == {}


@pytest.mark.parametrize("mod_id", [[], {}, None, 7])
def test_malformed_stored_project_identifier_is_unknown(monkeypatch, mod_id):
    value = project()
    value["mod_id"] = mod_id
    with patch.object(state, "account_projects", return_value=[value]):
        assert call_statuses(monkeypatch) == {}
