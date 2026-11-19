"""MODstore 内部 SSO JWT 签发。"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "unit-test-internal-key")
    monkeypatch.setenv("MODSTORE_JWT_SECRET", "unit-test-jwt-secret-at-least-32-chars-long")

    from modstore_server.app import app

    return TestClient(app)


def test_sso_issue_token_requires_internal_key(client):
    res = client.post(
        "/api/auth/internal/sso-issue-token",
        json={"username": "sso-new", "email": "sso-new@example.com"},
    )
    assert res.status_code == 403


def test_sso_issue_token_jit_provision(client, monkeypatch):
    from modstore_server.auth_service import find_user_for_sso_identity

    username = "sso-jit-user"
    assert find_user_for_sso_identity(username=username) is None
    res = client.post(
        "/api/auth/internal/sso-issue-token",
        json={"username": username, "email": "jit@example.com", "display_name": "JIT"},
        headers={"X-Internal-Api-Key": os.environ["XCAGI_MARKET_INTERNAL_API_KEY"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("success") is True
    data = body.get("data") or {}
    assert data.get("token")
    assert data.get("refresh_token")
    assert (data.get("user") or {}).get("username") == username
    assert find_user_for_sso_identity(username=username) is not None


@pytest.mark.parametrize("plan_id", ["saas-personal-free", "saas-trial-30"])
def test_sso_keeps_legacy_personal_access_mask_and_paid_access(client, plan_id):
    from modstore_server.models import UserPlan, get_session_factory

    username = f"sso-plan-{uuid.uuid4().hex[:12]}"
    registered = client.post(
        "/api/auth/register", json={"username": username, "password": "sso-plan-pass-12"}
    ).json()
    with get_session_factory()() as session:
        session.add(UserPlan(user_id=registered["user"]["id"], plan_id=plan_id))
        session.commit()
    response = client.post(
        "/api/auth/internal/sso-issue-token",
        json={"username": username},
        headers={"X-Internal-Api-Key": os.environ["XCAGI_MARKET_INTERNAL_API_KEY"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    for projection in (data, data["user"]):
        assert projection["active_plan_id"] == plan_id
        assert projection["desktop_access"] is (plan_id != "saas-personal-free")
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    ).json()
    assert me["id"] == registered["user"]["id"]
    assert me["desktop_access"] == data["desktop_access"]
    login = client.post(
        "/api/auth/login", json={"username": username, "password": "sso-plan-pass-12"}
    ).json()
    for projection in (login, login["user"], me):
        for key in ("account_state", "active_plan_id", "desktop_access", "next_action"):
            assert projection[key] == data[key]
