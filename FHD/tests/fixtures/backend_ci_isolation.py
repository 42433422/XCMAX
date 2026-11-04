"""Explicit test-owned database and bounded upstream throttling handling."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError

import pytest


@pytest.fixture
def isolated_login_host_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as host_db
    from app.db.db_base import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'login.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(host_db, "HostSessionLocal", sessionmaker(bind=engine))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def trusted_actor(tmp_path, monkeypatch):
    """Opt-in real host sessions, role grants and Principal binding for tool tests."""
    import json
    import uuid
    from datetime import timedelta
    from types import SimpleNamespace

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request

    from app import db as host_db
    from app.db.db_base import Base
    from app.db.models.permission import DEFAULT_ROLES, Permission, Role
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.domain.shared_services.session_service import SessionService
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.utils.time import utc_now_naive

    engine = create_engine(f"sqlite:///{tmp_path / 'trusted-actors.sqlite'}")
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(host_db, "HostSessionLocal", factory)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service", SessionService
    )

    def create(
        *, user_id=None, tenant_id=7, role="user", tier="enterprise", mod_id="", permissions=None
    ):
        session_id = uuid.uuid4().hex
        codes = (
            permissions
            if permissions is not None
            else next((r["permissions"] for r in DEFAULT_ROLES if r["name"] == role), [])
        )
        with factory.begin() as db:
            role_row = db.query(Role).filter_by(name=role).first()
            if role_row is None:
                role_row = Role(name=role)
                db.add(role_row)
                for code in codes:
                    permission = db.query(Permission).filter_by(code=code).first()
                    if permission is None:
                        permission = Permission(code=code, name=code)
                        db.add(permission)
                    role_row.permissions.append(permission)
            user = db.get(User, user_id) if user_id is not None else None
            if user is None:
                user = User(
                    username=f"actor-{session_id}",
                    password="unused",
                    tenant_id=tenant_id,
                    role=role,
                    tier=tier,
                )
                if user_id is not None:
                    user.id = user_id
                db.add(user)
                db.flush()
            user_id_value = user.id
            row = UserSession(
                session_id=session_id,
                user_id=user_id_value,
                expires_at=utc_now_naive() + timedelta(hours=1),
                entitled_mod_ids_json=json.dumps([mod_id] if mod_id else []),
            )
            db.add(row)
            db.flush()
            session_row_id = row.id
        headers = {"X-Session-ID": session_id}
        if mod_id:
            headers["X-XCAGI-Active-Mod-Id"] = mod_id
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/tools/execute",
                "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        return SimpleNamespace(
            principal=principal,
            context=authenticated_runtime_context({}, principal),
            headers=headers,
            request=request,
            factory=factory,
            user_id=user_id_value,
            tenant_id=tenant_id,
            session_id=session_id,
            session_row_id=session_row_id,
        )

    try:
        yield create
    finally:
        engine.dispose()


def retry_throttled_fetch(fetch, *, sleep=time.sleep):
    """Retry only 429, honor Retry-After, and still fail when retries exhaust."""

    def wrapped(path):
        for attempt in range(3):
            try:
                return fetch(path)
            except HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                raw = exc.headers.get("Retry-After", "") if exc.headers else ""
                try:
                    delay = float(raw)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
                    except (TypeError, ValueError):
                        delay = 15 * (attempt + 1)
                if delay > 120:
                    raise
                sleep(max(0, delay))
        raise AssertionError("Unreachable retry state")

    return wrapped
