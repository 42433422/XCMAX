"""Real SQLite replay protection across independent DB connections/processes."""

from __future__ import annotations

import multiprocessing
import time
from contextlib import contextmanager

import jwt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.security import web_jwt as w


@pytest.fixture
def replay_db(tmp_path, monkeypatch):
    path = str(tmp_path / "replay.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 15})
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE web_refresh_token_uses "
                "(jti VARCHAR(64) PRIMARY KEY, expires_at BIGINT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_web_refresh_token_uses_expires_at "
                "ON web_refresh_token_uses (expires_at)"
            )
        )
    factory = sessionmaker(bind=engine)

    @contextmanager
    def db_scope():
        with factory.begin() as db:
            yield db

    monkeypatch.setenv("SECRET_KEY", "isolated-test-secret-not-for-production-" * 2)
    monkeypatch.setattr("app.db.session.get_host_db", db_scope)
    yield path, db_scope
    engine.dispose()


def _consume_in_process(args):
    path, jti, expiry = args
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 15})
    try:
        with sessionmaker(bind=engine).begin() as db:
            result = w._consume_refresh_jti(db, jti, expiry, int(time.time()))
        return result
    finally:
        engine.dispose()


def test_atomic_refresh_claim_has_only_one_process_winner(replay_db):
    path, _ = replay_db
    # A fresh interpreter per worker also excludes inherited in-memory replay state.
    context = multiprocessing.get_context("spawn")
    args = [(path, "one-token", int(time.time()) + 600)] * 6
    with context.Pool(3) as pool:
        results = pool.map_async(_consume_in_process, args).get(timeout=20)
    assert sum(results) == 1
    with context.Pool(1) as fresh_pool:
        assert fresh_pool.map_async(_consume_in_process, args[:1]).get(timeout=20) == [False]


def test_refresh_binding_and_replay(replay_db):
    _, scope = replay_db
    tokens = w.issue_web_tokens(user_id=7, session_id="bound-session")
    rotated = w.refresh_web_access_token(tokens["refresh_token"])
    assert rotated is not None
    assert all(
        w.verify_web_jwt(token)["session_id"] == "bound-session" for token in rotated.values()
    )
    assert w.refresh_web_access_token(tokens["refresh_token"]) is None
    with scope() as db:
        assert db.execute(text("SELECT COUNT(*) FROM web_refresh_token_uses")).scalar_one() == 1


def test_rollback_does_not_burn_refresh_identity(replay_db):
    _, scope = replay_db
    with pytest.raises(RuntimeError, match="abort"), scope() as db:
        assert w._consume_refresh_jti(db, "rolled-back", int(time.time()) + 600, int(time.time()))
        raise RuntimeError("abort")
    with scope() as db:
        assert w._consume_refresh_jti(db, "rolled-back", int(time.time()) + 600, int(time.time()))


def test_missing_jti_is_rejected(replay_db):
    token = w.issue_web_tokens(user_id=7)["refresh_token"]
    claims = w.verify_web_jwt(token)
    claims.pop("jti")
    malformed = jwt.encode(claims, w._secret_key(), algorithm=w.WEB_JWT_ALG)
    assert w.refresh_web_access_token(malformed) is None


def test_store_unavailable_fails_closed(replay_db, monkeypatch):
    _, scope = replay_db
    token = w.issue_web_tokens(user_id=7)["refresh_token"]

    @contextmanager
    def unavailable():
        raise SQLAlchemyError("injected store outage")
        yield  # pragma: no cover

    monkeypatch.setattr("app.db.session.get_host_db", unavailable)
    assert w.refresh_web_access_token(token) is None
    monkeypatch.setattr("app.db.session.get_host_db", scope)
    assert w.refresh_web_access_token(token) is not None


def test_enabled_auth_requires_shared_secret(monkeypatch):
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        w.issue_web_tokens(user_id=7)


@pytest.mark.parametrize("jti, expiry", [("", 1000), ("x" * 65, 1000), ("x", 1), ("x", True)])
def test_invalid_claim_cannot_be_consumed(replay_db, jti, expiry):
    _, scope = replay_db
    with scope() as db:
        assert not w._consume_refresh_jti(db, jti, expiry, 100)
        assert db.execute(text("SELECT COUNT(*) FROM web_refresh_token_uses")).scalar_one() == 0
