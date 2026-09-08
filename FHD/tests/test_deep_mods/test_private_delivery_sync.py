"""Account-bound auto delivery with real sessions, signatures and process locks."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import private_delivery_sync as service
from app.fastapi_routes.delivery_sync_routes import router
from app.infrastructure.mods.install_receipts import read_verified_install
from app.infrastructure.mods.mod_manager import ModManager
from app.infrastructure.mods.state_lock import state_lock
from app.mod_sdk.owner_workspace import owner_workspace


def release(mid="unknown-ui-fixture", **changes):
    return dict(
        {
            "id": mid,
            "version": "1.0.0",
            "package_sha256": "a" * 64,
            "installable": True,
            "publication_status": "signed_release",
            "owner_user_id": 101,
            "delivery_ticket_id": 1,
        },
        **changes,
    )


@pytest.fixture
def sync_client(signed_runtime_mod, monkeypatch):
    manager = ModManager(str(signed_runtime_mod.root))
    monkeypatch.setattr(manager, "all_mods_roots", lambda: [str(signed_runtime_mod.root)])
    monkeypatch.setattr(service, "get_mod_manager", lambda: manager)
    mocks = SimpleNamespace(
        entitlements=AsyncMock(return_value=True),
        fetch=AsyncMock(return_value=[]),
        update=AsyncMock(return_value={"success": True, "updated": True}),
        receipts=AsyncMock(return_value={"pending": 0}),
        issues=AsyncMock(return_value={"reported": 0}),
    )
    monkeypatch.setattr(
        service, "_private_delivery_market_token", AsyncMock(return_value="fixture")
    )
    monkeypatch.setattr(service, "fetch_private_mod_library", mocks.fetch)
    monkeypatch.setattr(service, "refresh_delivery_entitlements", mocks.entitlements)
    monkeypatch.setattr(service, "update_private_mod_from_library", mocks.update)
    monkeypatch.setattr(service, "retry_delivery_receipts", mocks.receipts)
    monkeypatch.setattr(service, "report_ready_issue_identities", mocks.issues)
    app = FastAPI()
    app.include_router(router, prefix="/api/mod-store")
    with TestClient(app) as client:
        client.cookies.set("session_id", "mod-session-1")
        yield client, mocks


def run(sync_client):
    client, _ = sync_client
    response = client.post("/api/mod-store/private-delivery/sync", json={})
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.parametrize("session", [None, "mod-session-3", "mod-session-4"])
def test_anonymous_disabled_expired_never_touch_market(sync_client, session):
    client, mocks = sync_client
    client.cookies.clear()
    if session:
        client.cookies.set("session_id", session)
    assert client.post("/api/mod-store/private-delivery/sync", json={}).status_code in {
        401,
        403,
    }
    mocks.fetch.assert_not_awaited()
    mocks.update.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"installable": False},
        {"package_sha256": ""},
        {"owner_user_id": 102},
        {"delivery_ticket_id": 0},
        {"publication_status": "source_only"},
        {"delivery_ticket_id": {"bad": 1}},
        {"id": "../host"},
        {"id": "taiyangniao-pro"},
    ],
)
def test_unaccepted_or_unbound_rows_never_install(sync_client, changes):
    _, mocks = sync_client
    mocks.fetch.return_value = [release(**changes)]
    result = run(sync_client)
    assert result["installed"] == []
    mocks.update.assert_not_awaited()
    mocks.receipts.assert_awaited_once()
    mocks.issues.assert_awaited_once()
    # No parameter to manufacture a customer acceptance is supplied.
    assert len(mocks.issues.call_args.args) == 1
    assert mocks.issues.call_args.kwargs == {}


def test_new_private_packages_are_bounded_and_account_scope_is_mandatory(sync_client):
    _, mocks = sync_client
    mocks.fetch.return_value = [release(f"private-{i}") for i in range(5)] + [release("private-0")]
    result = run(sync_client)
    assert result["installed"] == ["private-0", "private-1", "private-2"]
    assert result["pending"] == 2
    assert mocks.update.await_count == 3
    assert mocks.update.call_args.kwargs == {
        "expected_version": "1.0.0",
        "owner_scope": "tenant:1",
        "require_account_scope": True,
    }


@pytest.mark.parametrize("kind", ["same", "downgrade", "changed_digest", "pending"])
def test_real_signed_current_or_staged_package_is_never_reinstalled(
    sync_client, signed_runtime_mod, kind
):
    _, mocks = sync_client
    signed_runtime_mod.install(version="2.0.0")
    if kind == "pending":
        signed_runtime_mod.install(version="3.0.0", loaded=True)
    receipt = read_verified_install("unknown-ui-fixture", mods_root=str(signed_runtime_mod.root))
    assert receipt
    mocks.fetch.return_value = [
        release(
            version="1.0.0" if kind == "downgrade" else receipt["package_version"],
            package_sha256=("b" * 64 if kind == "changed_digest" else receipt["package_sha256"]),
        )
    ]
    result = run(sync_client)
    mocks.update.assert_not_awaited()
    assert result["restart_required"] == (["unknown-ui-fixture"] if kind == "pending" else [])
    assert bool(result["errors"]) is (kind == "changed_digest")


def test_signed_private_upgrade_is_allowed_for_same_owner(sync_client, signed_runtime_mod):
    _, mocks = sync_client
    signed_runtime_mod.install()
    mocks.fetch.return_value = [release(version="1.1.0")]
    mocks.update.return_value = {
        "success": True,
        "updated": True,
        "requires_restart": True,
    }
    result = run(sync_client)
    assert result["installed"] == ["unknown-ui-fixture"]
    assert result["restart_required"] == ["unknown-ui-fixture"]


@pytest.mark.parametrize("kind", ["unverified", "other_owner", "public"])
def test_public_or_other_owner_install_is_never_overwritten(
    sync_client, signed_runtime_mod, tmp_path, kind
):
    _, mocks = sync_client
    if kind == "public":
        source = tmp_path / "public-source"
        source.mkdir()
        (source / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "unknown-ui-fixture",
                    "version": "1.0.0",
                    "name": "Public",
                    "scope": "global",
                }
            )
        )
        signed_runtime_mod.install(source=source)
    else:
        signed_runtime_mod.install(
            signed=kind != "unverified",
            owner="tenant:2" if kind == "other_owner" else "tenant:1",
        )
    before = (signed_runtime_mod.root / "unknown-ui-fixture" / "manifest.json").read_bytes()
    mocks.fetch.return_value = [release(version="2.0.0")]
    result = run(sync_client)
    assert result["pending"] == 1
    assert result["errors"]
    mocks.update.assert_not_awaited()
    assert (signed_runtime_mod.root / "unknown-ui-fixture" / "manifest.json").read_bytes() == before


def test_catalog_outage_still_retries_receipts_and_shared_issue_identity(sync_client):
    _, mocks = sync_client
    mocks.fetch.side_effect = ConnectionError("offline")
    mocks.receipts.return_value = {"pending": 2}
    assert run(sync_client)["pending"] == 3
    mocks.receipts.assert_awaited_once()
    mocks.issues.assert_awaited_once()
    mocks.fetch.side_effect = None
    assert run(sync_client)["pending"] == 2
    assert mocks.receipts.await_count == 2


def test_live_owner_lock_prevents_duplicate_sync(sync_client):
    _, mocks = sync_client
    directory = owner_workspace("private-delivery-sync", owner_id="tenant:1").root
    directory.mkdir(parents=True)
    with state_lock(directory):
        assert run(sync_client)["pending"] == 1
    mocks.fetch.assert_not_awaited()
    assert run(sync_client)["pending"] == 0
    mocks.fetch.assert_awaited_once()


def test_session_revocation_during_catalog_read_prevents_install(sync_client, mod_accounts):
    from app.db.models.user import Session

    _, mocks = sync_client

    async def revoke(_token):
        with mod_accounts.sessions.begin() as db:
            db.query(Session).filter_by(session_id="mod-session-1").delete()
        await asyncio.sleep(0)
        return [release()]

    mocks.fetch.side_effect = revoke
    response = sync_client[0].post("/api/mod-store/private-delivery/sync", json={})
    assert response.status_code == 401
    mocks.update.assert_not_awaited()
    mocks.receipts.assert_not_awaited()


def test_install_refreshes_current_entitlements_before_runtime_receipt(sync_client):
    _, mocks = sync_client
    calls = []

    async def install(*args, **kwargs):
        calls.append("install")
        return {"success": True, "updated": True}

    async def refresh(*args):
        calls.append("entitlements")
        return False  # A transient Market failure leaves the delivery pending.

    async def receipt(*args):
        calls.append("receipts")
        return {"pending": 1}

    mocks.fetch.return_value = [release()]
    mocks.update.side_effect = install
    mocks.entitlements.side_effect = refresh
    mocks.receipts.side_effect = receipt
    assert run(sync_client)["pending"] == 2
    assert calls == ["install", "entitlements", "receipts"]


def test_late_entitlements_refresh_reports_routes_changed_without_install(
    sync_client, mod_accounts
):
    from app.db.models.user import Session

    _, mocks = sync_client

    async def refresh(*args):
        with mod_accounts.sessions.begin() as db:
            row = db.query(Session).filter_by(session_id="mod-session-1").one()
            row.entitled_mod_ids_json = '["taiyangniao-pro", "new-private-runtime"]'
        return True

    mocks.entitlements.side_effect = refresh
    result = run(sync_client)
    assert result["installed"] == []
    assert result["routes_changed"] is True
    mocks.entitlements.side_effect = None
    assert run(sync_client)["routes_changed"] is False


def test_admin_impersonation_never_fetches_or_installs_owner_packages(sync_client, mod_accounts):
    from app.db.models.user import Session

    with mod_accounts.sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="mod-session-1").one()
        row.impersonating_market_user_id = 102
        row.impersonating_username = "OTHER"
    client, mocks = sync_client
    response = client.post("/api/mod-store/private-delivery/sync", json={})
    assert response.status_code == 403
    mocks.fetch.assert_not_awaited()
    mocks.entitlements.assert_not_awaited()
    with mod_accounts.sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="mod-session-1").one()
        assert row.entitled_mod_ids_json == '["taiyangniao-pro"]'
        row.impersonating_market_user_id = None
        row.impersonating_username = None
    assert run(sync_client)["pending"] == 0
    mocks.fetch.assert_awaited_once()
