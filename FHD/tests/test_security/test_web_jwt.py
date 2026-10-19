"""Web JWT signing, verification, refresh rotation and flag gating."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.security import web_jwt as w


@pytest.fixture(autouse=True)
def _isolated_refresh_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'web-jwt.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE web_refresh_token_uses "
                "(jti VARCHAR(64) PRIMARY KEY, expires_at BIGINT NOT NULL)"
            )
        )
    factory = sessionmaker(bind=engine)

    @contextmanager
    def scope():
        with factory.begin() as db:
            yield db

    monkeypatch.setenv("SECRET_KEY", "web-jwt-test-only-not-production-" * 2)
    monkeypatch.setattr("app.db.session.get_host_db", scope)
    yield
    engine.dispose()


class TestWebJwt:
    def test_session_binding_survives_refresh(self):
        tokens = w.issue_web_tokens(user_id=7, session_id="bound-session")
        assert w.verify_web_jwt(tokens["access_token"])["session_id"] == "bound-session"
        rotated = w.refresh_web_access_token(tokens["refresh_token"])
        assert rotated is not None
        for token in rotated.values():
            assert w.verify_web_jwt(token)["session_id"] == "bound-session"

    def test_issue_and_verify(self):
        toks = w.issue_web_tokens(user_id=7, username="bob", account_kind="enterprise")
        assert "access_token" in toks and "refresh_token" in toks
        payload = w.verify_web_jwt(toks["access_token"])
        assert payload is not None
        assert payload["typ"] == "access"
        assert payload["user_id"] == 7
        assert payload["account_kind"] == "enterprise"

    def test_verify_rejects_garbage(self):
        assert w.verify_web_jwt("not.a.jwt") is None
        assert w.verify_web_jwt("") is None

    def test_refresh_rotation_one_time(self):
        toks = w.issue_web_tokens(user_id=7)
        rotated = w.refresh_web_access_token(toks["refresh_token"])
        assert rotated is not None and "access_token" in rotated
        assert w.refresh_web_access_token(toks["refresh_token"]) is None

    def test_access_token_cannot_refresh(self):
        toks = w.issue_web_tokens(user_id=7)
        assert w.refresh_web_access_token(toks["access_token"]) is None

    def test_resolve_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_WEB_JWT_AUTH", raising=False)
        toks = w.issue_web_tokens(user_id=7)
        assert w.web_jwt_auth_enabled() is False
        assert w.resolve_user_from_web_jwt(toks["access_token"]) is None

    def test_flag_enabled_detection(self, monkeypatch):
        monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
        assert w.web_jwt_auth_enabled() is True
