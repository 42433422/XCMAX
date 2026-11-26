"""Host session revocation invalidates already issued Web JWTs on all workers.

The PostgreSQL multi-process case is an explicit acceptance test and skips if no
real PostgreSQL test database is configured; a skip is not a green PG receipt.
"""

from __future__ import annotations

import multiprocessing
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.application.rbac_app_service import RbacAppService
from app.db.models.permission import Permission, Role, role_permissions
from app.db.models.user import Session as UserSession
from app.db.models.user import User, WebRefreshTokenUse
from app.security import web_jwt
from app.utils.time import utc_now_naive


def _schema(engine):
    from app.db.db_base import Base

    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            UserSession.__table__,
            Permission.__table__,
            Role.__table__,
            role_permissions,
            WebRefreshTokenUse.__table__,
        ],
    )


def _seed(factory, session_id):
    with factory.begin() as db:
        reader = Permission(code="elt.read", name="read")
        executor = Permission(code="elt.execute", name="execute")
        role = Role(name="tenant:7:worker", is_system=False, permissions=[reader])
        db.add_all([role, executor])
        db.flush()
        role_id = role.id
        user = User(
            username="revocation-fixture-" + session_id,
            password="not-used",
            tenant_id=7,
            role=role.name,
            tier="personal",
            account_tier="personal",
            is_active=True,
        )
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(
            UserSession(
                user_id=user_id,
                session_id=session_id,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    return role_id, user_id


def _worker(url, schema, token, observed, proceed):
    import app.db

    engine = create_engine(
        url, connect_args={"options": "-csearch_path=" + schema}, poolclass=NullPool
    )
    try:
        app.db.HostSessionLocal = sessionmaker(bind=engine)
        observed.put(("before", web_jwt.resolve_user_from_web_jwt(token) is not None))
        if proceed.get(timeout=60) != "check":
            return
        observed.put(("after", web_jwt.resolve_user_from_web_jwt(token) is not None))
    finally:
        engine.dispose()


def test_sqlite_existing_jwt_and_refresh_fail_after_role_revoke(tmp_path, monkeypatch):
    import app.db

    engine = create_engine("sqlite:///" + str(tmp_path / "revocation.db"), poolclass=NullPool)
    try:
        _schema(engine)
        factory = sessionmaker(bind=engine)
        role_id, user_id = _seed(factory, "old-session")
        monkeypatch.setattr(app.db, "HostSessionLocal", factory)
        monkeypatch.setenv("SECRET_KEY", "test-revocation-secret-" * 3)
        monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
        tokens = web_jwt.issue_web_tokens(user_id=user_id, session_id="old-session")
        assert web_jwt.resolve_user_from_web_jwt(tokens["access_token"]).id == user_id
        changed = RbacAppService().update_role(role_id, permissions=["elt.execute"], tenant_id=7)
        assert changed["sessions_revoked"] == 1
        assert web_jwt.resolve_user_from_web_jwt(tokens["access_token"]) is None
        assert web_jwt.refresh_web_access_token(tokens["refresh_token"]) is None
        with factory() as db:
            assert db.query(UserSession).filter_by(user_id=user_id).count() == 0
            role = db.query(Role).filter_by(id=role_id).one()
            assert {p.code for p in role.permissions} == {"elt.execute"}
    finally:
        engine.dispose()


def test_sqlite_disabled_user_rejects_old_signed_access(tmp_path, monkeypatch):
    import app.db

    engine = create_engine("sqlite:///" + str(tmp_path / "disabled.db"), poolclass=NullPool)
    try:
        _schema(engine)
        factory = sessionmaker(bind=engine)
        _, user_id = _seed(factory, "disabled-session")
        monkeypatch.setattr(app.db, "HostSessionLocal", factory)
        monkeypatch.setenv("SECRET_KEY", "test-revocation-secret-" * 3)
        monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
        access = web_jwt.issue_web_tokens(user_id=user_id, session_id="disabled-session")[
            "access_token"
        ]
        assert web_jwt.resolve_user_from_web_jwt(access) is not None
        with factory.begin() as db:
            db.get(User, user_id).is_active = False
        assert web_jwt.resolve_user_from_web_jwt(access) is None
    finally:
        engine.dispose()


def test_postgres_two_processes_observe_same_committed_revocation(monkeypatch):
    import app.db

    url = os.environ.get("XCAGI_TEST_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("No real PostgreSQL DSN; multi-process acceptance remains BLOCKED")
    schema = "rbac_revoke_" + uuid4().hex[:12]
    admin_engine = create_engine(url, poolclass=NullPool)
    engine = None
    worker = None
    try:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
        engine = create_engine(
            url, connect_args={"options": "-csearch_path=" + schema}, poolclass=NullPool
        )
        _schema(engine)
        factory = sessionmaker(bind=engine)
        session_id = "pg-session-" + schema
        role_id, user_id = _seed(factory, session_id)
        monkeypatch.setattr(app.db, "HostSessionLocal", factory)
        monkeypatch.setenv("SECRET_KEY", "test-revocation-secret-" * 3)
        monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
        tokens = web_jwt.issue_web_tokens(user_id=user_id, session_id=session_id)
        context = multiprocessing.get_context("spawn")
        observed, proceed = context.Queue(), context.Queue()
        worker = context.Process(
            target=_worker,
            args=(url, schema, tokens["access_token"], observed, proceed),
        )
        worker.start()
        assert observed.get(timeout=60) == ("before", True)
        changed = RbacAppService().update_role(role_id, permissions=["elt.execute"], tenant_id=7)
        assert changed["sessions_revoked"] == 1
        proceed.put("check")
        assert observed.get(timeout=60) == ("after", False)
        with factory() as db:
            assert db.query(UserSession).filter_by(user_id=user_id).count() == 0
        assert web_jwt.refresh_web_access_token(tokens["refresh_token"]) is None
        worker.join(timeout=15)
        assert worker.exitcode == 0
    finally:
        if worker is not None and worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as conn:
            conn.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
        admin_engine.dispose()
