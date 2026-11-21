"""Offline login reuses successful local sign-in evidence and password security."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application import auth_app_service, enterprise_login_flow
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.domain.app_pure.account_security import totp_now
from app.infrastructure.session import session_manager
from app.utils.security.password_hash import generate_password_hash
from app.utils.time import utc_now_naive


@pytest.fixture
def offline_auth(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'offline.sqlite3'}")
    User.__table__.create(engine)
    UserSession.__table__.create(engine)

    @contextmanager
    def database():
        with Session(engine, expire_on_commit=False) as db:
            yield db
            db.commit()

    with database() as db:
        db.add(
            User(
                id=71,
                username="cached-user",
                password=generate_password_hash("typed-password"),
                last_login=utc_now_naive() - timedelta(days=1),
                mfa_enabled=True,
                totp_secret="JBSWY3DPEHPK3PXP",
            )
        )
    monkeypatch.setattr(auth_app_service, "get_db", database)
    monkeypatch.setattr(session_manager, "get_host_db", database)
    monkeypatch.setattr("app.db.init_db.ensure_runtime_auth_bootstrap", lambda **_kw: None)
    monkeypatch.setattr(enterprise_login_flow, "_is_desktop_runtime", lambda: True)
    finalize = AsyncMock(side_effect=lambda **kw: kw["result"])
    monkeypatch.setattr(enterprise_login_flow, "finalize_enterprise_login", finalize)
    try:
        yield auth_app_service.AuthApplicationService(), database, finalize
    finally:
        engine.dispose()


async def offline_login(service, password="typed-password"):
    return await enterprise_login_flow.run_offline_login(
        username="cached-user", password=password, auth_app_service=service, sku="enterprise"
    )


@pytest.mark.asyncio
async def test_offline_login_cannot_establish_its_own_first_login_evidence(offline_auth):
    service, database, finalize = offline_auth
    with database() as db:
        db.get(User, 71).last_login = None
    for _ in range(2):
        result, error = await offline_login(service)
        assert result is None and error is not None
        assert b"OFFLINE_AUTH_FAILED" in error.body
    with database() as db:
        assert db.get(User, 71).last_login is None
        assert db.query(UserSession).count() == 0
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_mfa_user_can_login_offline_but_password_is_checked_each_time(offline_auth):
    service, database, finalize = offline_auth
    assert service.login("cached-user", "typed-password")["mfa_required"] is True
    result, error = await offline_login(service)
    assert error is None and result["success"] is True
    assert finalize.await_args.kwargs["market_result"] is None
    assert finalize.await_args.kwargs["skip_market_sync"] is True
    denied, error = await offline_login(service, "wrong-password")
    assert denied is None and error is not None
    with database() as db:
        assert db.query(UserSession).count() == 1
        assert db.get(User, 71).failed_login_attempts == 1


@pytest.mark.asyncio
async def test_first_authenticated_login_makes_account_eligible_offline(offline_auth):
    service, database, _finalize = offline_auth
    with database() as db:
        db.get(User, 71).last_login = None
    result = service.login("cached-user", "typed-password", totp_code=totp_now("JBSWY3DPEHPK3PXP"))
    assert result["success"] is True
    result, error = await offline_login(service)
    assert error is None and result["success"] is True
    with database() as db:
        assert db.query(UserSession).count() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["disabled", "locked", "admin_role", "admin_tier"])
async def test_offline_login_rejects_blocked_accounts_before_session_creation(
    offline_auth, blocked
):
    service, database, finalize = offline_auth
    with database() as db:
        user = db.get(User, 71)
        previous_login = user.last_login
        if blocked == "disabled":
            user.is_active = False
        elif blocked == "locked":
            user.locked_until = utc_now_naive() + timedelta(minutes=5)
        elif blocked == "admin_role":
            user.role = "admin"
        else:
            user.tier = "admin"
    result, error = await offline_login(service)
    assert result is None and error is not None
    if blocked.startswith("admin"):
        assert b"ADMIN_DESKTOP_FORBIDDEN" in error.body
    with database() as db:
        assert db.query(UserSession).count() == 0
        assert db.get(User, 71).last_login == previous_login
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_offline_login_is_unavailable_on_server(offline_auth, monkeypatch):
    service, database, finalize = offline_auth
    monkeypatch.setattr(enterprise_login_flow, "_is_desktop_runtime", lambda: False)
    result, error = await offline_login(service)
    assert result is None and error.status_code == 403
    with database() as db:
        assert db.query(UserSession).count() == 0
    finalize.assert_not_awaited()
