from __future__ import annotations

import os
import uuid


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
