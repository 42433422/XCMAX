from __future__ import annotations

import os
import uuid
from pathlib import Path


def test_internal_ensure_enterprise_profile_grants_only_requested_mods(client, monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "unit-test-internal-key")

    from modstore_server.auth_service import register_user
    from modstore_server.models_db import get_user_mod_ids

    username = f"enterprise-grant-{uuid.uuid4().hex[:10]}"
    user = register_user(username, "pass123", f"{username}@example.com")

    res = client.post(
        "/api/internal/cs-intake/ensure-enterprise-profile",
        json={
            "market_user_id": int(user.id),
            "display_name": username,
            "mod_ids": ["coating-industry", "coating-industry"],
        },
        headers={"X-Internal-Api-Key": os.environ["XCAGI_MARKET_INTERNAL_API_KEY"]},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["is_enterprise"] is True
    assert body["mod_ids"] == ["coating-industry"]
    assert body["added_mod_ids"] == ["coating-industry"]
    assert sorted(get_user_mod_ids(int(user.id))) == ["coating-industry"]


def _register_seed_package(tmp_path: Path):
    from modstore_server.catalog_store import append_package

    seed = tmp_path / "seed.zip"
    seed.write_bytes(b"PK\x03\x04seed")
    return append_package(
        {
            "id": "sunbird-delivery-seed",
            "version": "1.0.0",
            "name": "Sunbird Seed",
            "artifact": "customer_delivery_seed",
            "account_mod_id": "taiyangniao-pro",
        },
        seed,
    )


def _auth_header_for(username: str) -> tuple[int, dict[str, str]]:
    from modstore_server.auth_service import create_access_token, register_user

    user = register_user(username, "pass123", f"{username}@example.com")
    token = create_access_token(int(user.id), user.username, is_admin=False)
    return int(user.id), {"Authorization": f"Bearer {token}"}


def test_enterprise_customer_delivery_seed_download_requires_entitlement(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    _register_seed_package(tmp_path)

    username = f"seed-denied-{uuid.uuid4().hex[:10]}"
    _, headers = _auth_header_for(username)

    res = client.get(
        "/api/enterprise/customer-delivery-seeds/sunbird-delivery-seed/1.0.0/download"
        "?mod_id=taiyangniao-pro",
        headers=headers,
    )

    assert res.status_code == 403


def test_enterprise_customer_delivery_seed_download_returns_file_for_authorized_account(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    _register_seed_package(tmp_path)

    username = f"seed-ok-{uuid.uuid4().hex[:10]}"
    user_id, headers = _auth_header_for(username)
    from modstore_server.models_db import add_user_mod

    add_user_mod(user_id, "taiyangniao-pro")

    res = client.get(
        "/api/enterprise/customer-delivery-seeds/sunbird-delivery-seed/1.0.0/download"
        "?mod_id=taiyangniao-pro",
        headers=headers,
    )

    assert res.status_code == 200, res.text
    assert res.content == b"PK\x03\x04seed"


def test_enterprise_customer_delivery_seed_download_rejects_wrong_mod_id(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    _register_seed_package(tmp_path)

    username = f"seed-wrong-{uuid.uuid4().hex[:10]}"
    user_id, headers = _auth_header_for(username)
    from modstore_server.models_db import add_user_mod

    add_user_mod(user_id, "taiyangniao-pro")

    res = client.get(
        "/api/enterprise/customer-delivery-seeds/sunbird-delivery-seed/1.0.0/download"
        "?mod_id=other-mod",
        headers=headers,
    )

    assert res.status_code == 403
