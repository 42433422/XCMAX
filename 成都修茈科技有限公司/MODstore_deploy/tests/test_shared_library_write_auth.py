"""Shared executable-code mutation is not granted by a customer's entitlement."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import mod_sync_catalog_api as sync_v1
from modstore_server.api import auth_deps, authoring, catalog, sync
from modstore_server.api.csrf import CSRFMiddleware
from modstore_server.application.auth import AuthApplicationService, AuthenticationError

CASES = [
    ("POST", "/api/mods/shared/snapshots/synthetic/restore", None, "restore"),
    ("POST", "/api/mods/shared/manifest/bump-patch-version", None, "bump"),
    ("POST", "/api/mods/shared/frontend/regenerate", {}, "frontend"),
    (
        "POST",
        "/api/mods/shared/workflow-employees/scaffold",
        {"id": "synthetic", "label": "Synthetic"},
        "scaffold",
    ),
    ("POST", "/api/mods/shared/snapshots", {}, "snapshot"),
    ("POST", "/api/mods/shared/attach-catalog-employee", {"pkg_id": "synthetic"}, "attach"),
    (
        "POST",
        "/api/mods/ai-scaffold",
        {"brief": "synthetic", "_manifest_override": {"id": "shared"}},
        "ai",
    ),
    ("PUT", "/api/mods/shared/manifest", {"manifest": {"id": "shared"}}, "manifest"),
    ("PUT", "/api/mods/shared/file", {"path": "hello.txt", "content": "synthetic"}, "file"),
    ("DELETE", "/api/mods/shared", None, "delete"),
    ("POST", "/api/sync/push", {}, "push"),
    ("POST", "/api/sync/push", {"mod_ids": []}, "push"),
    ("POST", "/api/sync/push", {"mod_ids": ["shared"]}, "push"),
    ("POST", "/api/sync/pull", {}, "pull"),
    ("POST", "/api/sync/pull", {"mod_ids": []}, "pull"),
    ("POST", "/api/sync/pull", {"mod_ids": ["shared"]}, "pull"),
    ("POST", "/v1/mod-sync/push", {}, "push"),
    ("POST", "/v1/mod-sync/push", {"mod_ids": []}, "push"),
    ("POST", "/v1/mod-sync/push", {"mod_ids": ["shared"]}, "push"),
    ("POST", "/v1/mod-sync/pull", {}, "pull"),
    ("POST", "/v1/mod-sync/pull", {"mod_ids": []}, "pull"),
    ("POST", "/v1/mod-sync/pull", {"mod_ids": ["shared"]}, "pull"),
]


@pytest.fixture
def guarded_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.setenv("MODSTORE_ENFORCE_SYNC_QUOTA", "0")
    users = {
        "Bearer member": SimpleNamespace(id=8, is_admin=False),
        "Bearer admin": SimpleNamespace(id=7, is_admin=True),
    }

    def resolve(_self, token):
        if token not in users:
            raise AuthenticationError("synthetic invalid credential")
        return users[token]

    monkeypatch.setattr(AuthApplicationService, "current_user_from_authorization", resolve)
    monkeypatch.setattr(
        sync_v1,
        "decode_access_token",
        lambda token: {"sub": users[f"Bearer {token}"].id} if f"Bearer {token}" in users else None,
    )
    monkeypatch.setattr(
        sync_v1,
        "get_user_by_id",
        lambda uid: next((user for user in users.values() if user.id == uid), None),
    )
    pats = {
        "pat_member": SimpleNamespace(user=users["Bearer member"], scopes=("mod:sync",)),
        "pat_admin": SimpleNamespace(user=users["Bearer admin"], scopes=("mod:sync",)),
        "pat_no_scope": SimpleNamespace(user=users["Bearer admin"], scopes=()),
    }
    monkeypatch.setattr(sync_v1, "resolve_pat_identity", lambda token: pats.get(token))
    monkeypatch.setattr(sync_v1, "get_user_mod_ids", lambda uid: ["shared"])
    monkeypatch.setattr(sync_v1, "user_owns_mod", lambda *_: True)
    monkeypatch.setattr(auth_deps, "user_owns_mod", lambda *_: True)
    resolve_mod = Mock(return_value=tmp_path / "shared")
    resolve_cfg = Mock(return_value={})
    monkeypatch.setattr(catalog.library_paths, "mod_dir", resolve_mod)
    monkeypatch.setattr(catalog.library_paths, "lib", lambda: tmp_path)
    monkeypatch.setattr(sync.library_paths, "cfg", resolve_cfg)
    monkeypatch.setattr(sync, "resolved_xcagi", lambda _: tmp_path / "host")
    monkeypatch.setattr("modstore_server.app._cfg", resolve_cfg)
    monkeypatch.setattr(sync_v1, "resolved_xcagi", lambda _: tmp_path / "host")
    monkeypatch.setattr(sync_v1, "_lib", lambda: tmp_path)
    monkeypatch.setattr(sync_v1, "list_mods", lambda _: [{"id": "shared"}, {"id": "other"}])
    monkeypatch.setattr(
        "modstore_server.customer_delivery_catalog.authorized_runtime_ids", lambda uid: {"shared"}
    )
    monkeypatch.setattr(
        "modstore_server.customer_delivery_catalog.private_release_rows", lambda *args: {}
    )
    writers = {
        "manifest": Mock(return_value=[]),
        "file": Mock(return_value=tmp_path / "shared/hello.txt"),
        "delete": Mock(),
        "push": Mock(return_value=["shared"]),
        "pull": Mock(return_value=["shared"]),
    }
    monkeypatch.setattr(catalog, "save_manifest_validated", writers["manifest"])
    monkeypatch.setattr(catalog, "write_text_under_mod", writers["file"])
    monkeypatch.setattr(catalog, "remove_mod_by_manifest_id", writers["delete"])
    monkeypatch.setattr(catalog, "remove_user_mod", Mock())
    monkeypatch.setattr(sync, "deploy_to_xcagi", writers["push"])
    monkeypatch.setattr(sync, "pull_from_xcagi", writers["pull"])
    monkeypatch.setattr(sync_v1, "deploy_to_xcagi", writers["push"])
    monkeypatch.setattr(sync_v1, "pull_from_xcagi", writers["pull"])
    monkeypatch.setattr(authoring, "assert_user_owns_mod", lambda *_: None)
    session = MagicMock()
    session.query.return_value.filter.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(pkg_id="synthetic", name="Synthetic", description="")
    )
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(authoring, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        authoring, "read_manifest", lambda _: ({"id": "shared", "workflow_employees": []}, None)
    )
    for key, name, result in [
        ("restore", "restore_manifest_snapshot", ({}, [])),
        ("bump", "bump_manifest_patch_version", ({}, [])),
        ("frontend", "regenerate_frontend", {"ok": True}),
        ("scaffold", "run_workflow_employee_scaffold", {"ok": True}),
        ("snapshot", "capture_manifest_snapshot", {"id": "synthetic"}),
        ("attach", "save_manifest_validated", []),
    ]:
        writers[key] = Mock(return_value=result)
        monkeypatch.setattr(authoring, name, writers[key])
    writers["ai"] = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.run_mod_suite_ai_scaffold_async", writers["ai"]
    )
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.analyze_mod_employee_readiness", lambda *_: {}
    )
    app = FastAPI()
    app.include_router(authoring.router)
    app.include_router(catalog.router)
    app.include_router(sync.router)
    app.include_router(sync_v1.router)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        yield client, writers, resolve_mod, resolve_cfg


@pytest.mark.parametrize("method,path,payload,writer", CASES)
@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Cookie": "csrf_token=t", "X-CSRF-Token": "t"}, 401),
        ({"Authorization": "Bearer forged", "Cookie": "csrf_token=t", "X-CSRF-Token": "t"}, 401),
        ({"Authorization": "Bearer member"}, 403),
        ({"Authorization": "Bearer forged", "Cookie": "is_admin=true; csrf_token=t"}, 403),
    ],
)
def test_untrusted_and_entitled_members_cannot_mutate_shared_code(
    guarded_client, method, path, payload, writer, headers, status
):
    client, writers, resolve_mod, resolve_cfg = guarded_client
    response = client.request(
        method, path + "?is_admin=true&user_id=7", json=payload, headers=headers
    )
    assert response.status_code == status
    for operation in writers.values():
        operation.assert_not_called()
    resolve_mod.assert_not_called()
    resolve_cfg.assert_not_called()


@pytest.mark.parametrize("method,path,payload,writer", CASES)
def test_admin_retains_existing_shared_write_contract(
    guarded_client, method, path, payload, writer
):
    client, writers, _, _ = guarded_client
    response = client.request(method, path, json=payload, headers={"Authorization": "Bearer admin"})
    assert response.status_code == 200, response.text
    writers[writer].assert_called_once()


@pytest.mark.parametrize("operation", ["push", "pull"])
@pytest.mark.parametrize(
    "token,status",
    [("pat_member", 403), ("pat_admin", 200), ("pat_no_scope", 403), ("pat_revoked", 401)],
)
def test_v1_write_requires_both_admin_role_and_existing_pat_scope(
    guarded_client, operation, token, status
):
    client, writers, _, resolve_cfg = guarded_client
    response = client.post(
        f"/v1/mod-sync/{operation}",
        json={"mod_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status, response.text
    if status == 200:
        writers[operation].assert_called_once()
    else:
        writers[operation].assert_not_called()
        resolve_cfg.assert_not_called()


@pytest.mark.parametrize("token", ["member", "pat_member"])
def test_member_retains_authorized_remote_mod_listing(guarded_client, token):
    client, _, _, _ = guarded_client
    response = client.get("/v1/mod-sync/mods", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["data"]] == ["shared"]
