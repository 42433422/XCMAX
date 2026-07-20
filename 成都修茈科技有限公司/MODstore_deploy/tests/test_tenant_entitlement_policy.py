"""T-E03：TenantModAccessPolicy 单测 + entitlement-check API。"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock


def test_decision_helpers():
    from modstore_server.tenant_entitlement import Decision

    allow = Decision.allow_with("ok", foo=1)
    deny = Decision.deny_with("no")
    assert allow.allow is True and allow.metadata["foo"] == 1
    assert deny.allow is False and deny.reason == "no"


def test_policy_denies_unsupported_action():
    from modstore_server.tenant_entitlement import TenantModAccessPolicy

    policy = TenantModAccessPolicy(lambda: MagicMock())
    d = policy.check(1, "consume_cost", "mod-a")
    assert d.allow is False
    assert "unsupported action" in d.reason


def test_policy_denies_empty_mod_id():
    from modstore_server.tenant_entitlement import TenantModAccessPolicy

    policy = TenantModAccessPolicy(lambda: MagicMock())
    d = policy.check(1, TenantModAccessPolicy.ACTION_ACCESS_MOD, "  ")
    assert d.allow is False
    assert "empty" in d.reason


def test_policy_denies_invalid_tenant():
    from modstore_server.tenant_entitlement import TenantModAccessPolicy

    policy = TenantModAccessPolicy(lambda: MagicMock())
    d = policy.check(0, TenantModAccessPolicy.ACTION_ACCESS_MOD, "mod-a")
    assert d.allow is False
    assert "must be positive" in d.reason


def test_policy_allow_when_user_mod_exists(client):
    from modstore_server.auth_service import register_user
    from modstore_server.models import get_session_factory
    from modstore_server.models_db import add_user_mod
    from modstore_server.tenant_entitlement import TenantModAccessPolicy

    username = f"tenant-pol-{uuid.uuid4().hex[:10]}"
    user = register_user(username, "pass123", f"{username}@example.com")
    add_user_mod(int(user.id), "coating-industry")

    policy = TenantModAccessPolicy(get_session_factory())
    d = policy.check(
        int(user.id),
        TenantModAccessPolicy.ACTION_ACCESS_MOD,
        "coating-industry",
    )
    assert d.allow is True
    assert d.metadata.get("mod_id") == "coating-industry"


def test_policy_deny_when_user_mod_missing(client):
    from modstore_server.auth_service import register_user
    from modstore_server.models import get_session_factory
    from modstore_server.tenant_entitlement import TenantModAccessPolicy

    username = f"tenant-pol-deny-{uuid.uuid4().hex[:10]}"
    user = register_user(username, "pass123", f"{username}@example.com")

    policy = TenantModAccessPolicy(get_session_factory())
    d = policy.check(
        int(user.id),
        TenantModAccessPolicy.ACTION_ACCESS_MOD,
        "coating-industry",
    )
    assert d.allow is False
    assert "entitlement not found" in d.reason


def test_entitlement_check_api_allow_and_deny(client):
    from modstore_server.auth_service import create_access_token, register_user
    from modstore_server.models_db import add_user_mod

    username = f"tenant-api-{uuid.uuid4().hex[:10]}"
    user = register_user(username, "pass123", f"{username}@example.com")
    add_user_mod(int(user.id), "coating-industry")
    headers = {
        "Authorization": f"Bearer {create_access_token(int(user.id), user.username, is_admin=False)}"
    }

    ok = client.get(
        "/api/enterprise/entitlement-check",
        params={"mod_id": "coating-industry"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["allow"] is True
    assert body["tenant_id"] == int(user.id)

    deny = client.get(
        "/api/enterprise/entitlement-check",
        params={"mod_id": "no-such-mod"},
        headers=headers,
    )
    assert deny.status_code == 200, deny.text
    assert deny.json()["allow"] is False
