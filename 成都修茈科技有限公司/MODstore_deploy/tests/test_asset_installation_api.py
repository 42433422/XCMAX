from __future__ import annotations

import uuid
from decimal import Decimal

from modstore_server.auth_service import decode_access_token
from modstore_server.db.billing import Entitlement
from modstore_server.db.catalog import CatalogItem, Purchase
from modstore_server.db.delivery_commerce import AssetInstallCommand, UpdateInstallationReceipt
from modstore_server.models import User, get_session_factory


def _user_id(auth_headers: dict[str, str]) -> int:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    payload = decode_access_token(token)
    assert payload
    return int(payload["sub"])


def _paid_asset(auth_headers: dict[str, str]) -> tuple[int, int, int, str]:
    user_id = _user_id(auth_headers)
    suffix = uuid.uuid4().hex[:10]
    installation_id = f"desktop-installation-{suffix}"
    sf = get_session_factory()
    with sf() as db:
        item = CatalogItem(
            pkg_id=f"paid-mod-{suffix}",
            version="1.0.0",
            name="Paid Mod",
            price=Decimal("9.90"),
            stored_filename=f"paid-mod-{suffix}.zip",
            sha256="a" * 64,
            is_public=True,
        )
        db.add(item)
        db.flush()
        purchase = Purchase(user_id=user_id, catalog_id=item.id, amount=Decimal("9.90"))
        db.add(purchase)
        db.flush()
        entitlement = Entitlement(
            user_id=user_id,
            catalog_id=item.id,
            entitlement_type="catalog_item",
            source_order_id=f"ORDER-{suffix}",
            is_active=True,
        )
        db.add(entitlement)
        db.add(
            UpdateInstallationReceipt(
                user_id=user_id,
                installation_id=installation_id,
                idempotency_key=f"receipt-{suffix}",
                status="installed",
            )
        )
        db.commit()
        return int(item.id), int(purchase.id), int(entitlement.id), installation_id


def test_paid_asset_command_is_idempotent_claimed_and_completed(client, auth_headers):
    catalog_id, _, _, installation_id = _paid_asset(auth_headers)
    body = {"catalog_id": catalog_id, "idempotency_key": f"click-{uuid.uuid4().hex}"}

    first = client.post("/api/asset-installations/commands", headers=auth_headers, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/api/asset-installations/commands", headers=auth_headers, json=body)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    command_id = int(first.json()["command"]["id"])

    claimed = client.post(
        f"/api/asset-installations/commands/{command_id}/claim",
        headers=auth_headers,
        json={"installation_id": installation_id},
    )
    assert claimed.status_code == 200, claimed.text
    asset = claimed.json()["command"]["asset"]
    assert asset["download_path"] == (
        f"/api/asset-installations/commands/{command_id}/download"
        f"?installation_id={installation_id}"
    )
    assert asset["sha256"] == "a" * 64

    resumable = client.get(
        "/api/asset-installations/commands",
        headers=auth_headers,
        params={"installation_id": installation_id, "pending_only": "true"},
    )
    assert resumable.status_code == 200, resumable.text
    assert [row["id"] for row in resumable.json()["items"]] == [command_id]

    mismatched = client.post(
        f"/api/asset-installations/commands/{command_id}/result",
        headers=auth_headers,
        json={
            "installation_id": installation_id,
            "status": "installed",
            "installed_mod_id": "another-mod",
            "installed_version": asset["version"],
        },
    )
    assert mismatched.status_code == 409, mismatched.text

    wrong_device = client.get(
        f"/api/asset-installations/commands/{command_id}/download",
        headers=auth_headers,
        params={"installation_id": "desktop-installation-other"},
    )
    assert wrong_device.status_code == 403, wrong_device.text

    completed = client.post(
        f"/api/asset-installations/commands/{command_id}/result",
        headers=auth_headers,
        json={
            "installation_id": installation_id,
            "status": "installed",
            "installed_mod_id": asset["pkg_id"],
            "installed_version": asset["version"],
            "result": {"activated": True},
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["command"]["status"] == "installed"

    receipt = client.get(
        f"/api/asset-installations/commands/{command_id}",
        headers=auth_headers,
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["command"]["status"] == "installed"


def test_refunded_entitlement_blocks_and_revokes_pending_command(client, auth_headers):
    catalog_id, purchase_id, entitlement_id, installation_id = _paid_asset(auth_headers)
    from modstore_server.asset_installation_api import queue_install_command

    user_id = _user_id(auth_headers)
    sf = get_session_factory()
    with sf() as db:
        purchase = db.query(Purchase).filter(Purchase.id == purchase_id).one()
        command, _ = queue_install_command(
            db,
            user_id=user_id,
            purchase=purchase,
            catalog_id=catalog_id,
            source="payment_callback",
            source_event_id=f"evt-{uuid.uuid4().hex}",
        )
        db.query(Entitlement).filter(Entitlement.id == entitlement_id).update({"is_active": False})
        db.commit()
        command_id = int(command.id)

    claimed = client.post(
        f"/api/asset-installations/commands/{command_id}/claim",
        headers=auth_headers,
        json={"installation_id": installation_id},
    )
    assert claimed.status_code == 403, claimed.text
    with sf() as db:
        row = db.query(AssetInstallCommand).filter(AssetInstallCommand.id == command_id).one()
        assert row.status == "revoked"
        assert row.error == "payment_refunded"


def test_refund_revokes_exact_order_without_revoking_another_active_purchase(
    client, auth_headers
):
    catalog_id, purchase_id, entitlement_id, _ = _paid_asset(auth_headers)
    user_id = _user_id(auth_headers)
    from modstore_server.asset_installation_api import (
        queue_install_command,
        revoke_asset_install_commands_for_order,
    )

    sf = get_session_factory()
    with sf() as db:
        purchase = db.query(Purchase).filter(Purchase.id == purchase_id).one()
        refunded, _ = queue_install_command(
            db,
            user_id=user_id,
            purchase=purchase,
            catalog_id=catalog_id,
            source="payment_callback",
            source_event_id="payment.paid:ORDER-REFUNDED",
        )
        active_entitlement = Entitlement(
            user_id=user_id,
            catalog_id=catalog_id,
            entitlement_type="catalog_item",
            source_order_id="ORDER-STILL-ACTIVE",
            is_active=True,
        )
        db.add(active_entitlement)
        active_purchase = Purchase(
            user_id=user_id,
            catalog_id=catalog_id,
            amount=Decimal("9.90"),
        )
        db.add(active_purchase)
        db.flush()
        retained, _ = queue_install_command(
            db,
            user_id=user_id,
            purchase=active_purchase,
            catalog_id=catalog_id,
            source="payment_callback",
            source_event_id="payment.paid:ORDER-STILL-ACTIVE",
        )
        db.query(Entitlement).filter(Entitlement.id == entitlement_id).update(
            {"source_order_id": "ORDER-REFUNDED", "is_active": False}
        )
        db.commit()
        refunded_id = int(refunded.id)
        retained_id = int(retained.id)

    assert revoke_asset_install_commands_for_order(
        user_id=user_id, order_no="ORDER-REFUNDED"
    ) == 1
    with sf() as db:
        assert db.get(AssetInstallCommand, refunded_id).status == "revoked"
        assert db.get(AssetInstallCommand, retained_id).status == "pending"


def test_missing_artifact_sha_and_cross_account_idempotency_are_safe(client, auth_headers):
    catalog_id, purchase_id, _, installation_id = _paid_asset(auth_headers)
    user_id = _user_id(auth_headers)
    sf = get_session_factory()
    with sf() as db:
        item = db.query(CatalogItem).filter(CatalogItem.id == catalog_id).one()
        item.sha256 = ""
        db.add(item)
        db.commit()

    blocked = client.post(
        "/api/asset-installations/commands",
        headers=auth_headers,
        json={"catalog_id": catalog_id, "idempotency_key": "shared-client-key"},
    )
    assert blocked.status_code == 409, blocked.text

    with sf() as db:
        item = db.query(CatalogItem).filter(CatalogItem.id == catalog_id).one()
        item.sha256 = "b" * 64
        purchase = db.query(Purchase).filter(Purchase.id == purchase_id).one()
        other_user = User(
            username=f"other-{uuid.uuid4().hex}",
            password_hash="not-used-in-this-test",
        )
        db.add(other_user)
        db.flush()
        other_purchase = Purchase(
            user_id=int(other_user.id),
            catalog_id=catalog_id,
            amount=Decimal("9.90"),
        )
        db.add(other_purchase)
        db.flush()
        from modstore_server.asset_installation_api import queue_install_command

        first, _ = queue_install_command(
            db,
            user_id=user_id,
            purchase=purchase,
            catalog_id=catalog_id,
            installation_id=installation_id,
            source="user_click",
            idempotency_key="shared-client-key",
        )
        second, _ = queue_install_command(
            db,
            user_id=int(other_user.id),
            purchase=other_purchase,
            catalog_id=catalog_id,
            installation_id=installation_id,
            source="user_click",
            idempotency_key="shared-client-key",
        )
        assert first.idempotency_key != second.idempotency_key


def test_non_installable_purchased_asset_remains_download_only(client, auth_headers):
    catalog_id, _, _, _ = _paid_asset(auth_headers)
    sf = get_session_factory()
    with sf() as db:
        item = db.get(CatalogItem, catalog_id)
        item.artifact = "workflow_template"
        db.commit()

    response = client.post(
        "/api/asset-installations/commands",
        headers=auth_headers,
        json={"catalog_id": catalog_id, "idempotency_key": "not-installable"},
    )

    assert response.status_code == 409, response.text
    assert "仅支持下载" in response.json()["detail"]
