import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mod_runtime_frontend import router


@pytest.fixture
def runtime_client(signed_runtime_mod):
    app = FastAPI()
    app.include_router(router, prefix="/api/mods")
    with TestClient(app) as client:
        client.cookies.set("session_id", "mod-session-1")
        yield client


def test_unknown_compiled_mod_is_served_from_real_signed_install(
    runtime_client, signed_runtime_mod
):
    signed_runtime_mod.install(
        content="export function mount(node) { node.textContent='v1'; return () => {} }"
    )
    response = runtime_client.get("/api/mods/runtime/unknown-ui-fixture")
    assert response.status_code == 200
    metadata = response.json()["data"]
    assert metadata["owner_scope"] == "tenant:1"
    assert metadata["routes"][0]["path"] == "/mod/unknown-ui-fixture/home"
    asset = runtime_client.get(metadata["entry_url"])
    assert asset.status_code == 200
    assert "node.textContent='v1'" in asset.text
    assert asset.headers["cache-control"] == "no-store"
    assert asset.headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("session", [None, "mod-session-2", "mod-session-4"])
def test_metadata_and_assets_are_protected_on_every_request(
    runtime_client, signed_runtime_mod, session
):
    signed_runtime_mod.install()
    metadata = runtime_client.get("/api/mods/runtime/unknown-ui-fixture").json()["data"]
    runtime_client.cookies.clear()
    if session:
        runtime_client.cookies.set("session_id", session)
    for path in ("/api/mods/runtime/unknown-ui-fixture", metadata["entry_url"]):
        assert runtime_client.get(path).status_code in {401, 403}


@pytest.mark.parametrize("signed,owner", [(False, "tenant:1"), (True, "")])
def test_unsigned_or_unbound_private_package_cannot_mount(
    runtime_client, signed_runtime_mod, signed, owner
):
    if not owner:
        with pytest.raises(ValueError, match="requires an owner"):
            signed_runtime_mod.install(signed=signed, owner=owner)
    else:
        signed_runtime_mod.install(signed=signed, owner=owner)
    assert runtime_client.get("/api/mods/runtime/unknown-ui-fixture").status_code in {
        403,
        409,
    }


def test_modified_asset_is_rejected_even_after_metadata_was_read(
    runtime_client, signed_runtime_mod
):
    installed = signed_runtime_mod.install()
    metadata = runtime_client.get("/api/mods/runtime/unknown-ui-fixture").json()["data"]
    (installed / "frontend/runtime/index.js").write_text("export const tampered = true")
    assert runtime_client.get(metadata["entry_url"]).status_code == 409


def test_pending_upgrade_cannot_mix_new_frontend_with_old_backend(
    runtime_client, signed_runtime_mod, monkeypatch
):
    from app.infrastructure.mods import install_receipts

    signed_runtime_mod.install()
    signed_runtime_mod.install(
        version="1.1.0",
        loaded=True,
        content="export function mount() { return () => {} } // new",
    )
    assert runtime_client.get("/api/mods/runtime/unknown-ui-fixture").status_code == 409
    monkeypatch.setattr(install_receipts, "PROCESS_ID", "independent-new-process")
    assert install_receipts.activate_pending_install(
        "unknown-ui-fixture", mods_root=str(signed_runtime_mod.root)
    )
    assert (
        runtime_client.get("/api/mods/runtime/unknown-ui-fixture").json()["data"]["package_version"]
        == "1.1.0"
    )


@pytest.mark.parametrize("kind", ["remote_entry", "host_route"])
def test_signed_manifest_cannot_route_to_remote_code_or_shadow_host(
    runtime_client, signed_runtime_mod, tmp_path, kind
):
    source = tmp_path / "invalid-source"
    source.mkdir()
    manifest = {
        "id": "unknown-ui-fixture",
        "name": "Fixture",
        "version": "1.0.0",
        "scope": "account",
        "entitlement_mod_id": "taiyangniao-pro",
        "frontend": {
            "runtime": {
                "sdk_version": 1,
                "entry": "frontend/runtime/index.js",
                "routes": [{"path": "/mod/unknown-ui-fixture/home"}],
            }
        },
    }
    if kind == "remote_entry":
        manifest["frontend"]["runtime"]["entry"] = "https://untrusted.invalid/index.js"
    else:
        manifest["frontend"]["runtime"]["routes"][0]["path"] = "/login"
    (source / "manifest.json").write_text(json.dumps(manifest))
    entry = source / "frontend/runtime/index.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("export function mount() { return () => {} }")
    signed_runtime_mod.install(source=source)
    assert runtime_client.get("/api/mods/runtime/unknown-ui-fixture").status_code == 409


@pytest.mark.parametrize("right", ["taiyangniao-pro", "unknown-ui-fixture", "other-private-mod"])
def test_signed_account_mod_accepts_runtime_or_legacy_right_for_same_owner(
    runtime_client, signed_runtime_mod, mod_accounts, right
):
    from app.db.models.user import Session

    signed_runtime_mod.install()
    with mod_accounts.sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="mod-session-1").one()
        row.entitled_mod_ids_json = json.dumps([right])
    response = runtime_client.get("/api/mods/runtime/unknown-ui-fixture")
    assert response.status_code == (403 if right == "other-private-mod" else 200)
    # Direct runtime entitlement still cannot cross the owner-scoped installation.
    with mod_accounts.sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="mod-session-2").one()
        row.entitled_mod_ids_json = '["unknown-ui-fixture"]'
    runtime_client.cookies.set("session_id", "mod-session-2")
    assert runtime_client.get("/api/mods/runtime/unknown-ui-fixture").status_code == 403
