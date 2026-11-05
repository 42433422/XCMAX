# mypy: disable-error-code="arg-type"
from __future__ import annotations

from types import SimpleNamespace

from app.fastapi_routes import dataset_access


class _PermissionService:
    @staticmethod
    def get_user_permissions(_user: object) -> set[str]:
        return set()


class _ReadOnlyPermissionService:
    @staticmethod
    def get_user_permissions(_user: object) -> set[str]:
        return {"dataset.read"}


def _request(headers: dict[str, str] | None = None, host: str = "testclient") -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def test_regular_user_does_not_gain_unassigned_knowledge_permissions(monkeypatch) -> None:
    user = SimpleNamespace(id=7, tenant_id=23, role="user")
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: _PermissionService(),
    )

    context = dataset_access.dataset_access_context_from_request(_request())

    assert context is not None
    assert context.actor_id == "7"
    assert context.tenant_id == "23"
    assert context.permissions == frozenset()
    assert context.is_admin is False


def test_viewer_keeps_only_assigned_read_permission(monkeypatch) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="viewer")
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: _ReadOnlyPermissionService(),
    )

    context = dataset_access.dataset_access_context_from_request(_request())

    assert context is not None
    assert context.permissions == frozenset({"dataset.read"})


def test_tenant_admin_named_role_does_not_gain_global_dataset_admin(monkeypatch) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="admin", tier="admin")
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: _PermissionService(),
    )

    context = dataset_access.dataset_access_context_from_request(_request())

    assert context is not None
    assert context.is_admin is False
    assert context.permissions == frozenset()


def test_disabled_session_does_not_keep_dataset_permissions(monkeypatch) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="user", is_active=False)
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: _ReadOnlyPermissionService(),
    )

    context = dataset_access.dataset_access_context_from_request(_request())

    assert context is not None
    assert context.actor_id == ""
    assert context.permissions == frozenset()


def test_production_rejects_untrusted_dataset_permission_headers(monkeypatch) -> None:
    monkeypatch.setenv("FHD_ENV", "production")
    monkeypatch.delenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", raising=False)
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: None)

    context = dataset_access.dataset_access_context_from_request(
        _request(
            {
                "X-Dataset-Actor-ID": "attacker",
                "X-Dataset-Tenant-ID": "victim",
                "X-Dataset-Admin": "true",
            },
            host="203.0.113.10",
        )
    )

    assert context is not None
    assert context.permissions == frozenset()
    assert context.is_admin is False


def test_desktop_rejects_forged_admin_headers_even_with_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", "1")
    monkeypatch.setattr(dataset_access, "is_desktop_mode", lambda: True)
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: None)

    context = dataset_access.dataset_access_context_from_request(
        _request(
            {
                "X-Dataset-Actor-ID": "attacker",
                "X-Dataset-Tenant-ID": "victim",
                "X-Dataset-Admin": "true",
            },
            host="127.0.0.1",
        ),
        allow_local_default_read=True,
    )

    assert context is not None
    assert context.actor_id == ""
    assert context.tenant_id == ""
    assert context.permissions == frozenset()
    assert context.is_admin is False


def test_production_can_explicitly_trust_gateway_headers(monkeypatch) -> None:
    monkeypatch.setenv("FHD_ENV", "production")
    monkeypatch.setenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", "1")
    monkeypatch.setattr(dataset_access, "resolve_session_user", lambda _request: None)

    context = dataset_access.dataset_access_context_from_request(
        _request(
            {
                "X-Dataset-Actor-ID": "gateway-user",
                "X-Dataset-Tenant-ID": "tenant-1",
                "X-Dataset-Permissions": "dataset.read",
            },
            host="203.0.113.10",
        )
    )

    assert context is not None
    assert context.actor_id == "gateway-user"
    assert context.permissions == frozenset({"dataset.read"})
