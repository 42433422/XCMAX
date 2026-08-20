# mypy: disable-error-code="func-returns-value"
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.application import auth_permission_resolver as permissions


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" PERSONAL ", "personal"),
        ("Enterprise", "enterprise"),
        ("ADMIN", "admin"),
        ("unknown", "personal"),
        (None, "personal"),
    ],
)
def test_normalize_account_kind_is_closed_to_known_values(raw: object, expected: str) -> None:
    assert permissions._normalize_account_kind(raw) == expected


@pytest.mark.parametrize(
    ("user", "meta", "expected"),
    [
        (SimpleNamespace(), {"enterprise_role": "custom_owner"}, "custom_owner"),
        (SimpleNamespace(), {"rbac_role": "custom_admin"}, "custom_admin"),
        (SimpleNamespace(role="enterprise_operator"), {}, "enterprise_operator"),
        (SimpleNamespace(role="unknown", tier="enterprise"), {}, "enterprise_owner"),
        (SimpleNamespace(role="unknown", tier="personal"), {}, "enterprise_viewer"),
    ],
)
def test_resolve_enterprise_role_uses_explicit_role_then_account_defaults(
    user: object, meta: dict[str, str], expected: str
) -> None:
    assert permissions.resolve_enterprise_role(user, meta) == expected


def test_personal_desktop_and_non_admin_route_are_blocked() -> None:
    decision = permissions.resolve_permissions(
        user=SimpleNamespace(account_kind="personal"),
        session_meta={"client_shell": "desktop"},
        route="/api/admin/users",
    )
    assert decision["account_kind"] == "personal"
    assert decision["route_reason"] == "admin_only"
    assert decision["personal_shell_blocked"] is True
    assert decision["allowed"] is False


def test_enterprise_employee_execute_respects_role_permission() -> None:
    allowed = permissions.resolve_permissions(
        user=SimpleNamespace(account_kind="enterprise", role="enterprise_operator"),
        route="/api/employees/demo/execute",
    )
    assert allowed["route_allowed"] is True
    assert "employee.invoke" in allowed["permissions"]

    denied = permissions.resolve_permissions(
        user=SimpleNamespace(account_kind="enterprise", role="enterprise_viewer"),
        route="/api/employees/demo/execute",
    )
    assert denied["route_allowed"] is False
    assert denied["route_reason"] == "employee_invoke_denied"


def test_admin_employee_execute_is_allowed_off_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.application.desktop_admin_gate.is_desktop_runtime", lambda: False)
    decision = permissions.resolve_permissions(
        user=SimpleNamespace(account_kind="admin"),
        route="/api/employees/demo/execute",
    )
    assert decision["route_allowed"] is True
    assert decision["admin_shell_blocked"] is False
    assert decision["allowed"] is True


def test_admin_desktop_detection_failure_falls_back_to_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_detection() -> bool:
        raise RuntimeError("runtime probe unavailable")

    monkeypatch.setattr("app.application.desktop_admin_gate.is_desktop_runtime", fail_detection)
    blocked = permissions.resolve_permissions(
        user=SimpleNamespace(account_kind="admin"),
        session_meta={"shell": "desktop"},
    )
    assert blocked["admin_shell_blocked"] is True
    assert blocked["allowed"] is False

    allowed = permissions.resolve_permissions(
        user=SimpleNamespace(account_kind="admin"),
        session_meta={"shell": "web"},
    )
    assert allowed["admin_shell_blocked"] is False
    assert allowed["allowed"] is True


def test_enterprise_mod_entitlement_allowed_denied_and_recoverable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mod_id: mod_id == "allowed-mod",
    )
    user = SimpleNamespace(account_kind="enterprise", role="enterprise_owner")

    allowed = permissions.resolve_permissions(user=user, mod_id="allowed-mod")
    assert allowed["mod_allowed"] is True
    assert allowed["mod_id"] == "allowed-mod"

    denied = permissions.resolve_permissions(user=user, mod_id="denied-mod")
    assert denied["mod_allowed"] is False
    assert denied["mod_reason"] == "mod_entitlement_required"
    assert denied["allowed"] is False

    def fail_check(_mod_id: str) -> bool:
        raise OSError("entitlement database unavailable")

    monkeypatch.setattr("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", fail_check)
    failed = permissions.resolve_permissions(user=user, mod_id="broken-mod")
    assert failed["mod_allowed"] is False
    assert failed["mod_reason"] == "mod_entitlement_check_failed"


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        (
            {
                "user": SimpleNamespace(account_kind="personal"),
                "route": "/api/admin/users",
            },
            "admin_only",
        ),
        (
            {
                "user": SimpleNamespace(account_kind="personal"),
                "session_meta": {"shell": "mobile"},
            },
            "personal_shell_blocked",
        ),
    ],
)
def test_require_allowed_returns_stable_forbidden_reason(
    kwargs: dict[str, object], detail: str
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        permissions.require_allowed(**kwargs)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == detail


def test_require_allowed_returns_for_success() -> None:
    assert permissions.require_allowed(user=SimpleNamespace(account_kind="personal")) is None
