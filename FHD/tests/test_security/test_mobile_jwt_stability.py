"""移动端 JWT：稳定签名密钥 + refresh 会话有效性校验。"""

from __future__ import annotations

import pytest

from app.security import jwt_signing_key as signing_key
from app.security import mobile_jwt


@pytest.fixture(autouse=True)
def _reset_signing_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    monkeypatch.setattr(mobile_jwt, "_redis_blacklist", lambda: None)
    signing_key._cached_path = None
    signing_key._cached_secret = None
    signing_key._process_secret = None
    yield
    signing_key._cached_path = None
    signing_key._cached_secret = None
    signing_key._process_secret = None


def test_env_secret_takes_precedence(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "stable-test-secret-at-least-32-bytes")
    assert (
        signing_key.resolve_jwt_signing_key()
        == "stable-test-secret-at-least-32-bytes"
    )


def test_persisted_secret_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    tokens = mobile_jwt.issue_mobile_tokens(user_id=7, session_id="session-7")

    # 模拟进程重启：清空模块内缓存后，仍应读回同一密钥并验签通过。
    signing_key._cached_path = None
    signing_key._cached_secret = None
    signing_key._process_secret = None

    payload = mobile_jwt.verify_mobile_jwt(tokens["access_token"])
    assert payload is not None
    assert payload["user_id"] == 7
    assert (tmp_path / ".jwt-signing-secret").is_file()


class _MissingSessionService:
    def get_session_info(self, session_id: str):
        return None


class _LiveSessionService:
    def get_session_info(self, session_id: str):
        return {"session_id": session_id, "user_id": 7, "username": "bob"}


def test_refresh_rejected_when_session_no_longer_exists(monkeypatch):
    tokens = mobile_jwt.issue_mobile_tokens(user_id=7, session_id="session-dead")
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: _MissingSessionService(),
    )

    assert mobile_jwt.refresh_mobile_access_token(tokens["refresh_token"]) is None


def test_refresh_allowed_when_session_is_live(monkeypatch):
    tokens = mobile_jwt.issue_mobile_tokens(user_id=7, session_id="session-live")
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: _LiveSessionService(),
    )

    rotated = mobile_jwt.refresh_mobile_access_token(tokens["refresh_token"])
    assert rotated is not None
    assert mobile_jwt.verify_mobile_jwt(rotated["access_token"])["user_id"] == 7


def test_relay_session_refresh_skips_database_lookup(monkeypatch):
    tokens = mobile_jwt.issue_mobile_tokens(
        user_id=7,
        session_id="mobile-relay-abc123",
        account_kind="enterprise",
    )
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: _MissingSessionService(),
    )

    rotated = mobile_jwt.refresh_mobile_access_token(tokens["refresh_token"])
    assert rotated is not None
