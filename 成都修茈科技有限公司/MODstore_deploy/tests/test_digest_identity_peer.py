"""MODSTORE_DIGEST_* 跨部署身份码 peer 与 verify-admin 上游回退。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest


def test_internal_verify_404_when_inbound_disabled(client, monkeypatch):
    monkeypatch.delenv("MODSTORE_DIGEST_PEER_ENABLE_INBOUND", raising=False)
    monkeypatch.delenv("MODSTORE_DIGEST_PEER_SERVICE_TOKEN", raising=False)
    r = client.post("/api/internal/verify-digest-identity", json={"code": "A1B2C3"})
    assert r.status_code == 404


def test_internal_verify_401_wrong_token(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_DIGEST_PEER_SERVICE_TOKEN", "peer-secret-test-token")
    monkeypatch.setenv("MODSTORE_DIGEST_PEER_ENABLE_INBOUND", "1")
    r = client.post(
        "/api/internal/verify-digest-identity",
        json={"code": "A1B2C3"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_internal_verify_200_ok(client, monkeypatch):
    from modstore_server import models

    monkeypatch.setenv("MODSTORE_DIGEST_PEER_SERVICE_TOKEN", "peer-secret-test-token")
    monkeypatch.setenv("MODSTORE_DIGEST_PEER_ENABLE_INBOUND", "1")

    plain = "B0B0B0"
    th = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    sf = models.get_session_factory()
    expires_at = datetime.utcnow() + timedelta(hours=24)
    with sf() as s:
        s.add(
            models.OpsApprovalToken(
                token_hash=th,
                kind="digest_identity",
                payload_json='{"scope":"daily_digest"}',
                authorized_email="u@qq.com",
                expires_at=expires_at,
            )
        )
        s.commit()
    try:
        r = client.post(
            "/api/internal/verify-digest-identity",
            json={"code": plain},
            headers={"Authorization": "Bearer peer-secret-test-token"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("expires_at")
    finally:
        with sf() as s:
            s.query(models.OpsApprovalToken).filter(
                models.OpsApprovalToken.token_hash == th
            ).delete()
            s.commit()


def test_internal_verify_ok_false_when_unknown_code(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_DIGEST_PEER_SERVICE_TOKEN", "peer-secret-test-token")
    monkeypatch.setenv("MODSTORE_DIGEST_PEER_ENABLE_INBOUND", "1")
    r = client.post(
        "/api/internal/verify-digest-identity",
        json={"code": "999999"},
        headers={"Authorization": "Bearer peer-secret-test-token"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_verify_admin_digest_code_upstream_fallback(client, monkeypatch):
    """本地库无记录时，若 call_upstream_digest_verify 返回过期时间则 200。"""
    from modstore_server import market_auth_api, market_shared

    plain = "FACADE"

    def _fake_upstream(_code: str) -> str | None:
        assert _code == plain
        return "2099-12-31T00:00:00+00:00"

    monkeypatch.setattr(market_auth_api, "call_upstream_digest_verify", _fake_upstream)

    admin = __import__("types").SimpleNamespace(id=1, username="a", is_admin=True, email="a@a")
    from modstore_server.app import app

    app.dependency_overrides[market_shared._require_admin] = lambda: admin
    try:
        r = client.post("/api/auth/verify-admin-digest-code", json={"code": plain})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
        assert r.json().get("expires_at") == "2099-12-31T00:00:00+00:00"
    finally:
        app.dependency_overrides.pop(market_shared._require_admin, None)
