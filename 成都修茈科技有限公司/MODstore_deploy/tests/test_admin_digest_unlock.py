"""POST /api/auth/verify-admin-digest-code: 复用每日摘要邮件 6 位身份码解锁前端管理端 Tab。"""

from __future__ import annotations

import hashlib
import types
from datetime import datetime, timedelta


def _override_admin(app, market_shared_module):
    admin = types.SimpleNamespace(id=1, username="a", is_admin=True, email="a@a")
    app.dependency_overrides[market_shared_module._require_admin] = lambda: admin
    return admin


def test_verify_digest_code_success(client):
    """匹配未过期的 digest_identity token 应返回 ok + expires_at。"""
    from modstore_server import market_shared, models
    from modstore_server.app import app

    plain = "A1B2C3"
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

    _override_admin(app, market_shared)
    try:
        r = client.post("/api/auth/verify-admin-digest-code", json={"code": plain})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "expires_at" in body and body["expires_at"]
    finally:
        app.dependency_overrides.pop(market_shared._require_admin, None)
        with sf() as s:
            s.query(models.OpsApprovalToken).filter(
                models.OpsApprovalToken.token_hash == th
            ).delete()
            s.commit()


def test_verify_digest_code_accepts_copied_spacing(client):
    """邮箱客户端复制出的空格/连字符不应导致有效身份码失败。"""
    from modstore_server import market_shared, models
    from modstore_server.app import app

    plain = "A1B2C3"
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

    _override_admin(app, market_shared)
    try:
        r = client.post("/api/auth/verify-admin-digest-code", json={"code": " A1 B2-C3 "})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
    finally:
        app.dependency_overrides.pop(market_shared._require_admin, None)
        with sf() as s:
            s.query(models.OpsApprovalToken).filter(
                models.OpsApprovalToken.token_hash == th
            ).delete()
            s.commit()


def test_verify_digest_code_invalid_format(client):
    """非 6 位十六进制应直接 400，不查 DB。"""
    from modstore_server import market_shared
    from modstore_server.app import app

    _override_admin(app, market_shared)
    try:
        r = client.post("/api/auth/verify-admin-digest-code", json={"code": "ZZZ"})
        assert r.status_code == 400, r.text
        assert "格式" in r.text
    finally:
        app.dependency_overrides.pop(market_shared._require_admin, None)


def test_verify_digest_code_expired(client):
    """过期 token 不应通过校验。"""
    from modstore_server import market_shared, models
    from modstore_server.app import app

    plain = "DEADBE"
    th = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.OpsApprovalToken(
                token_hash=th,
                kind="digest_identity",
                payload_json='{"scope":"daily_digest"}',
                authorized_email="u@qq.com",
                expires_at=datetime.utcnow() - timedelta(hours=1),
            )
        )
        s.commit()

    _override_admin(app, market_shared)
    try:
        r = client.post("/api/auth/verify-admin-digest-code", json={"code": plain})
        assert r.status_code == 400, r.text
        assert "身份码无效或已过期" in r.text
    finally:
        app.dependency_overrides.pop(market_shared._require_admin, None)
        with sf() as s:
            s.query(models.OpsApprovalToken).filter(
                models.OpsApprovalToken.token_hash == th
            ).delete()
            s.commit()


def test_verify_digest_code_does_not_consume_used_at(client):
    """Web 端校验后 used_at 必须仍为空，避免影响邮件回信侧消费。"""
    from modstore_server import market_shared, models
    from modstore_server.app import app

    plain = "CAFE01"
    th = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.OpsApprovalToken(
                token_hash=th,
                kind="digest_identity",
                payload_json='{"scope":"daily_digest"}',
                authorized_email="u@qq.com",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
        )
        s.commit()

    _override_admin(app, market_shared)
    try:
        r = client.post("/api/auth/verify-admin-digest-code", json={"code": plain})
        assert r.status_code == 200, r.text
        with sf() as s:
            row = (
                s.query(models.OpsApprovalToken)
                .filter(models.OpsApprovalToken.token_hash == th)
                .one()
            )
            assert row.used_at is None
    finally:
        app.dependency_overrides.pop(market_shared._require_admin, None)
        with sf() as s:
            s.query(models.OpsApprovalToken).filter(
                models.OpsApprovalToken.token_hash == th
            ).delete()
            s.commit()
