"""MODstore 内部 SSO JWT 签发。"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "unit-test-internal-key")
    monkeypatch.setenv("MODSTORE_JWT_SECRET", "unit-test-jwt-secret-at-least-32-chars-long")
    from fastapi.testclient import TestClient

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
