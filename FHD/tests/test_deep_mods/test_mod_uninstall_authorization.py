"""Real route authorization for installed Mod removal; all files stay under tmp_path."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.csrf import CSRFMiddleware


@pytest.fixture
def uninstall_client(monkeypatch, mod_accounts):
    from app.fastapi_routes import mod_store_routes, mods_routes

    monkeypatch.setattr(mods_routes, "router", None)
    app = FastAPI()
    app.include_router(mods_routes.get_mods_router())
    app.include_router(mod_store_routes.router, prefix="/api/mod-store")
    app.add_middleware(CSRFMiddleware)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("csrf_token", "fixture-csrf-token")
        yield client


@pytest.fixture
def admin_session(mod_accounts):
    from app.db.models.user import Session, User
    from app.utils.time import utc_now_naive

    with mod_accounts.sessions.begin() as db:
        db.add(
            User(
                id=50,
                username="FIXTURE-ADMIN",
                password="unused",
                role="admin",
                tier="admin",
                is_active=True,
            )
        )
        db.add(
            Session(
                session_id="mod-session-admin",
                user_id=50,
                account_kind="admin",
                market_is_admin=True,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    return "mod-session-admin"


def _authenticated(client: TestClient, session_id: str) -> dict[str, str]:
    client.cookies.set("session_id", session_id)
    return {"X-CSRF-Token": "fixture-csrf-token"}


def _mod_call(client: TestClient, route: str, method: str, headers, mod_id: str, **kwargs):
    if method == "DELETE":
        return client.delete(route, headers=headers)
    body = kwargs.pop("json", {"mod_id": mod_id})
    return client.post(route, json=body, headers=headers, **kwargs)


@pytest.fixture
def isolated_manager(monkeypatch, signed_runtime_mod):
    from app.infrastructure.mods import mod_manager

    manager = mod_manager.ModManager(mods_root=str(signed_runtime_mod.root))
    manager._loaded_mods = ["unknown-ui-fixture", "legacy-global"]
    manager.unload_mod = Mock()
    metadata = {
        mod_id: SimpleNamespace(id=mod_id)
        for mod_id in ("unknown-ui-fixture", "legacy-global", "unowned-private")
    }
    registry = SimpleNamespace(get_mod_metadata=lambda mod_id: metadata.get(mod_id))
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: manager)
    monkeypatch.setattr(mod_manager, "is_mods_disabled", lambda: False)
    return manager


@pytest.mark.parametrize(
    "method,route",
    [
        ("DELETE", "/api/mods/unknown-ui-fixture"),
        ("POST", "/api/mod-store/uninstall"),
    ],
)
def test_owner_can_remove_their_verified_install_through_both_real_routes(
    uninstall_client,
    signed_runtime_mod,
    isolated_manager,
    method,
    route,
):
    target = signed_runtime_mod.install()
    headers = _authenticated(uninstall_client, "mod-session-1")
    response = _mod_call(
        uninstall_client,
        route,
        method,
        headers,
        "unknown-ui-fixture",
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert not target.exists()
    isolated_manager.unload_mod.assert_called_once_with("unknown-ui-fixture")


@pytest.mark.parametrize(
    "method,route",
    [
        ("DELETE", "/api/mods/unknown-ui-fixture"),
        ("POST", "/api/mod-store/uninstall"),
    ],
)
def test_other_customer_cannot_unload_or_remove_owner_install(
    uninstall_client,
    signed_runtime_mod,
    isolated_manager,
    method,
    route,
):
    target = signed_runtime_mod.install(owner="tenant:1")
    headers = _authenticated(uninstall_client, "mod-session-2")
    response = _mod_call(
        uninstall_client,
        route,
        method,
        headers,
        "unknown-ui-fixture",
        json={"mod_id": "unknown-ui-fixture", "owner_scope": "tenant:2"},
    )
    assert response.status_code == 403
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


def test_admin_cannot_remove_another_accounts_install(
    uninstall_client, signed_runtime_mod, isolated_manager, admin_session
):
    target = signed_runtime_mod.install(owner="tenant:1")
    headers = _authenticated(uninstall_client, admin_session)
    response = uninstall_client.delete("/api/mods/unknown-ui-fixture", headers=headers)
    assert response.status_code == 403
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


def test_admin_can_remove_their_own_bound_install(
    uninstall_client, signed_runtime_mod, isolated_manager, admin_session
):
    target = signed_runtime_mod.install(owner="session:50")
    headers = _authenticated(uninstall_client, admin_session)
    response = uninstall_client.delete("/api/mods/unknown-ui-fixture", headers=headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert not target.exists()
    isolated_manager.unload_mod.assert_called_once_with("unknown-ui-fixture")


def test_historical_market_admin_flag_does_not_grant_host_admin_authority(
    uninstall_client, mod_accounts, signed_runtime_mod, isolated_manager
):
    from sqlalchemy import select

    from app.db.models.user import Session

    with mod_accounts.sessions.begin() as db:
        session = db.scalar(select(Session).where(Session.session_id == "mod-session-1"))
        session.market_is_admin = True
    target = signed_runtime_mod.root / "legacy-global"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"id": "legacy-global", "name": "Legacy", "version": "1.0"})
    )
    headers = _authenticated(uninstall_client, "mod-session-1")
    response = uninstall_client.post(
        "/api/mod-store/uninstall", json={"mod_id": "legacy-global"}, headers=headers
    )
    assert response.status_code == 403
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


def test_admin_can_remove_unowned_legacy_global_install(
    uninstall_client, signed_runtime_mod, isolated_manager, admin_session
):
    target = signed_runtime_mod.root / "legacy-global"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"id": "legacy-global", "name": "Legacy", "version": "1.0"})
    )
    headers = _authenticated(uninstall_client, admin_session)
    response = uninstall_client.post(
        "/api/mod-store/uninstall", json={"mod_id": "legacy-global"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert not target.exists()


def test_regular_owner_cannot_claim_unowned_legacy_global_install(
    uninstall_client, signed_runtime_mod, isolated_manager
):
    target = signed_runtime_mod.root / "legacy-global"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"id": "legacy-global", "name": "Legacy", "version": "1.0"})
    )
    headers = _authenticated(uninstall_client, "mod-session-1")
    response = uninstall_client.post(
        "/api/mod-store/uninstall", json={"mod_id": "legacy-global"}, headers=headers
    )
    assert response.status_code == 403
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


@pytest.mark.parametrize("session_id", ["mod-session-1", "mod-session-admin"])
def test_unverifiable_receipt_fails_closed_for_customer_and_admin(
    uninstall_client, signed_runtime_mod, isolated_manager, admin_session, session_id
):
    target = signed_runtime_mod.install(owner="tenant:1")
    receipt = signed_runtime_mod.root / ".install-receipts/unknown-ui-fixture/receipt.json"
    receipt.write_text("{broken")
    headers = _authenticated(uninstall_client, session_id)
    response = uninstall_client.delete("/api/mods/unknown-ui-fixture", headers=headers)
    assert response.status_code == 409
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


@pytest.mark.parametrize(
    "binding",
    [
        {"scope": "account"},
        {"public_listing": False},
        {"visibility": "private"},
        {"visibility": " PRIVATE "},
        {"public_listing": "false"},
        {"owner_scope": "tenant:2"},
        {"owner_user_id": 2},
        {"delivery_owner_user_id": 2},
    ],
)
def test_account_manifest_without_receipt_is_not_admin_legacy(
    uninstall_client, signed_runtime_mod, isolated_manager, admin_session, binding
):
    target = signed_runtime_mod.root / "unowned-private"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "id": "unowned-private",
                "name": "Private",
                "version": "1.0",
                **binding,
            }
        )
    )
    headers = _authenticated(uninstall_client, admin_session)
    response = uninstall_client.post(
        "/api/mod-store/uninstall", json={"mod_id": "unowned-private"}, headers=headers
    )
    assert response.status_code == 403
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


def test_ambiguous_employee_and_mod_identity_cannot_select_another_install(
    uninstall_client, signed_runtime_mod, isolated_manager, admin_session
):
    root = signed_runtime_mod.root
    for target, extra in [
        (root / "legacy-global", {}),
        (root / "_employees/legacy-global", {"public_listing": False}),
    ]:
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(json.dumps({"id": "legacy-global", **extra}))
    response = uninstall_client.delete(
        "/api/mods/legacy-global", headers=_authenticated(uninstall_client, admin_session)
    )
    assert response.status_code == 409
    assert (root / "legacy-global").is_dir()
    assert (root / "_employees/legacy-global").is_dir()
    isolated_manager.unload_mod.assert_not_called()


def test_install_in_progress_lock_prevents_authorization_to_uninstall_race(
    uninstall_client, signed_runtime_mod, isolated_manager
):
    from app.infrastructure.mods import install_receipts
    from app.infrastructure.mods.state_lock import state_lock

    target = signed_runtime_mod.install()
    state = install_receipts._state_dir(signed_runtime_mod.root, "unknown-ui-fixture")
    headers = _authenticated(uninstall_client, "mod-session-1")
    with state_lock(state):
        response = uninstall_client.delete("/api/mods/unknown-ui-fixture", headers=headers)
    assert response.status_code == 409
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


def test_uninstall_removes_verified_pending_update_under_same_lock(
    uninstall_client, signed_runtime_mod, isolated_manager
):
    target = signed_runtime_mod.install()
    signed_runtime_mod.install(version="1.1.0", loaded=True, content="updated")
    pending = next(
        (signed_runtime_mod.root / ".install-receipts/unknown-ui-fixture").glob("pending-*")
    )
    headers = _authenticated(uninstall_client, "mod-session-1")
    response = uninstall_client.delete("/api/mods/unknown-ui-fixture", headers=headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert not target.exists()
    assert not pending.exists()


@pytest.mark.parametrize(
    "method,route", [("DELETE", "/api/mods/nope"), ("POST", "/api/mod-store/uninstall")]
)
def test_session_identity_required_and_x_user_id_or_owner_claim_is_ignored(
    uninstall_client, isolated_manager, method, route
):
    response = _mod_call(
        uninstall_client,
        route,
        method,
        {"X-CSRF-Token": "fixture-csrf-token", "X-User-ID": "1", "X-Owner-Scope": "tenant:1"},
        "unknown-ui-fixture",
        json={"mod_id": "unknown-ui-fixture", "owner_scope": "tenant:1"},
    )
    assert response.status_code == 401
    isolated_manager.unload_mod.assert_not_called()


def test_disabled_account_and_invalid_mod_id_fail_before_unload(uninstall_client, isolated_manager):
    disabled_headers = _authenticated(uninstall_client, "mod-session-3")
    disabled = uninstall_client.post(
        "/api/mod-store/uninstall",
        json={"mod_id": "unknown-ui-fixture"},
        headers=disabled_headers,
    )
    assert disabled.status_code == 403
    invalid_headers = _authenticated(uninstall_client, "mod-session-1")
    invalid = uninstall_client.post(
        "/api/mod-store/uninstall", json={"mod_id": "../other"}, headers=invalid_headers
    )
    assert invalid.status_code == 400
    isolated_manager.unload_mod.assert_not_called()


@pytest.mark.parametrize(
    "method,route",
    [
        ("DELETE", "/api/mods/unknown-ui-fixture"),
        ("POST", "/api/mod-store/uninstall"),
    ],
)
def test_csrf_double_submit_still_protects_both_mutation_routes(
    uninstall_client, signed_runtime_mod, isolated_manager, method, route
):
    target = signed_runtime_mod.install()
    uninstall_client.cookies.set("session_id", "mod-session-1")
    response = _mod_call(
        uninstall_client,
        route,
        method,
        {},
        "unknown-ui-fixture",
    )
    assert response.status_code == 403
    assert target.is_dir()
    isolated_manager.unload_mod.assert_not_called()


@pytest.fixture
def verified_unregistered_install(monkeypatch, signed_runtime_mod, tmp_path):
    from app.infrastructure.mods import mod_manager
    from app.infrastructure.mods.registry import ModRegistry

    registry = ModRegistry()
    manager = mod_manager.ModManager(mods_root=str(signed_runtime_mod.root))
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: manager)
    monkeypatch.setattr(mod_manager, "is_mods_disabled", lambda: False)
    manager.unload_mod = Mock(wraps=manager.unload_mod)

    def prepare(mode):
        source = tmp_path / "disk-only-source"
        source.mkdir()
        manifest = {
            "id": "unknown-ui-fixture",
            "name": "Disk-only fixture",
            "version": "1.0.0",
            "scope": "account",
            "entitlement_mod_id": "taiyangniao-pro",
            "dependencies": {"not-installed-fixture-dependency": "*"}
            if mode == "dependency_failure"
            else {},
            "frontend": {
                "runtime": {
                    "sdk_version": 1,
                    "entry": "frontend/runtime/index.js",
                    "routes": [{"path": "/mod/unknown-ui-fixture/home", "title": "Fixture"}],
                }
            },
        }
        (source / "manifest.json").write_text(json.dumps(manifest))
        entry = source / "frontend/runtime/index.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("export function mount() { return () => {} }")
        target = signed_runtime_mod.install(source=source)
        archive = next(
            (signed_runtime_mod.root / ".install-receipts/unknown-ui-fixture").glob("*.zip")
        )
        ok, message, _ = manager.install_mod_package(
            str(archive), verify_signature=True, activate=mode != "inactive", owner_scope="tenant:1"
        )
        if mode == "inactive":
            assert ok and "未激活" in message
        else:
            assert not ok and "加载失败" in message
        assert target.is_dir()
        assert registry.get_mod_metadata("unknown-ui-fixture") is None
        return target

    return SimpleNamespace(prepare=prepare, manager=manager, registry=registry)


@pytest.mark.parametrize("mode", ["inactive", "dependency_failure"])
@pytest.mark.parametrize(
    "method,route",
    [("DELETE", "/api/mods/unknown-ui-fixture"), ("POST", "/api/mod-store/uninstall")],
)
def test_verified_owner_can_uninstall_disk_only_install_through_real_routes(
    uninstall_client, verified_unregistered_install, mode, method, route
):
    target = verified_unregistered_install.prepare(mode)
    response = _mod_call(
        uninstall_client,
        route,
        method,
        _authenticated(uninstall_client, "mod-session-1"),
        "unknown-ui-fixture",
    )
    assert response.status_code == 200 and response.json()["success"] is True
    assert not target.exists()
    verified_unregistered_install.manager.unload_mod.assert_called_once_with("unknown-ui-fixture")


@pytest.mark.parametrize("mode", ["inactive", "dependency_failure"])
@pytest.mark.parametrize("failure", ["other_owner", "broken_receipt"])
@pytest.mark.parametrize(
    "method,route",
    [("DELETE", "/api/mods/unknown-ui-fixture"), ("POST", "/api/mod-store/uninstall")],
)
def test_disk_only_fallback_keeps_owner_and_receipt_rejections(
    uninstall_client,
    verified_unregistered_install,
    signed_runtime_mod,
    mode,
    failure,
    method,
    route,
):
    target = verified_unregistered_install.prepare(mode)
    if failure == "broken_receipt":
        (signed_runtime_mod.root / ".install-receipts/unknown-ui-fixture/receipt.json").write_text(
            "{broken"
        )
    session = "mod-session-2" if failure == "other_owner" else "mod-session-1"
    response = _mod_call(
        uninstall_client,
        route,
        method,
        _authenticated(uninstall_client, session),
        "unknown-ui-fixture",
    )
    assert response.status_code == (403 if failure == "other_owner" else 409)
    assert target.exists()
    verified_unregistered_install.manager.unload_mod.assert_not_called()


@pytest.mark.parametrize(
    "method,route",
    [("DELETE", "/api/mods/unknown-ui-fixture"), ("POST", "/api/mod-store/uninstall")],
)
def test_disk_only_fallback_does_not_delete_unverified_legacy_directory(
    uninstall_client,
    verified_unregistered_install,
    signed_runtime_mod,
    admin_session,
    method,
    route,
):
    target = signed_runtime_mod.root / "unknown-ui-fixture"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"id": "unknown-ui-fixture", "scope": "global"})
    )
    response = _mod_call(
        uninstall_client,
        route,
        method,
        _authenticated(uninstall_client, admin_session),
        "unknown-ui-fixture",
    )
    assert response.json()["success"] is False
    assert target.exists()
    verified_unregistered_install.manager.unload_mod.assert_not_called()
