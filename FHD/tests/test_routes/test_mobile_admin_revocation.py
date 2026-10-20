"""Live host-session authority must override historical mobile admin claims."""

from datetime import timedelta

import pytest
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import Session, User
from app.fastapi_routes.mobile_api import get_mobile_user
from app.security.mobile_jwt import issue_mobile_tokens, refresh_mobile_access_token
from app.utils.time import utc_now_naive

pytestmark = pytest.mark.release_gate


@pytest.fixture
def admin_session(tmp_path, monkeypatch):
    import app.db as database

    engine = create_engine(f"sqlite:///{tmp_path / 'identity.sqlite3'}")
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    # All non-management lookups in the old implementation use this factory.
    monkeypatch.setattr("app.db.session.SessionLocal", sessions)
    monkeypatch.setenv("SECRET_KEY", "synthetic-mobile-revocation-test-key-not-a-secret")
    with sessions.begin() as db:
        db.add(
            User(
                id=72,
                username="other-synthetic-user",
                password="unused",
                role="user",
                is_active=True,
            )
        )
        db.add(
            User(
                id=71,
                username="synthetic-admin",
                password="unused",
                role="admin",
                tier="admin",
                is_active=True,
            )
        )
        db.add(
            Session(
                session_id="synthetic-admin-session",
                user_id=71,
                account_kind="admin",
                market_is_admin=True,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    yield sessions
    engine.dispose()


def _tokens(kind="admin", sid="synthetic-admin-session", uid=71):
    return issue_mobile_tokens(
        user_id=uid, session_id=sid, account_kind=kind, username="synthetic-admin"
    )


def _request(token):
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


def _revoke(sessions, state):
    with sessions.begin() as db:
        user = db.get(User, 71)
        session = db.query(Session).filter_by(session_id="synthetic-admin-session").one()
        if state == "deleted-user":
            db.delete(user)
        elif state == "disabled":
            user.is_active = False
        elif state == "demoted":
            user.role, user.tier = "user", "enterprise"
        elif state == "market-only":
            user.role, user.tier = "user", "admin"
        elif state == "deleted-session":
            db.delete(session)
        elif state == "expired":
            session.expires_at = utc_now_naive() - timedelta(seconds=1)
        elif state == "session-demoted":
            session.account_kind = "enterprise"
        elif state == "mismatched-user":
            session.user_id = 72


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["admin", "admin_portal", " Admin "])
@pytest.mark.parametrize(
    "state",
    [
        "deleted-user",
        "disabled",
        "demoted",
        "deleted-session",
        "expired",
        "mismatched-user",
        "session-demoted",
        "market-only",
    ],
)
async def test_old_admin_access_and_refresh_fail_after_revocation(admin_session, kind, state):
    tokens = _tokens(kind)
    _revoke(admin_session, state)
    user = await get_mobile_user(
        _request(tokens["access_token"]), authorization="Bearer " + tokens["access_token"]
    )
    assert user is None
    assert refresh_mobile_access_token(tokens["refresh_token"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["admin", "admin_portal", " Admin "])
async def test_current_admin_session_preserves_access_and_refresh(admin_session, kind):
    tokens = _tokens(kind)
    user = await get_mobile_user(
        _request(tokens["access_token"]), authorization="Bearer " + tokens["access_token"]
    )
    assert user.id == 71 and user.role == "admin" and user.is_active
    refreshed = refresh_mobile_access_token(tokens["refresh_token"])
    assert refreshed and refreshed["access_token"]
    assert refresh_mobile_access_token(tokens["refresh_token"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["admin", "admin_portal", " Admin "])
async def test_admin_relay_without_revocable_session_is_rejected(admin_session, kind):
    tokens = _tokens(kind, sid="mobile-relay-synthetic")
    assert (
        await get_mobile_user(
            _request(tokens["access_token"]), authorization="Bearer " + tokens["access_token"]
        )
        is None
    )
    assert refresh_mobile_access_token(tokens["refresh_token"]) is None


@pytest.fixture
def mobile_client(admin_session, monkeypatch):
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes import mobile_api_extensions as extension

    service = Mock()
    service.invoke.return_value = {"accepted": True}
    monkeypatch.setattr(extension, "CodexSuperEmployeeService", lambda: service)
    # Business-only fake: no factory credential or external worker is created.
    monkeypatch.setattr(extension, "factory_context", lambda **kw: kw["base"])
    app = FastAPI()
    from app.fastapi_routes.mobile_api import router

    app.include_router(router)
    with TestClient(app) as client:
        yield client, service


@pytest.mark.parametrize("auth_kind", ["bearer", "cookie", "session-header"])
@pytest.mark.parametrize(
    "state", ["valid", "disabled", "demoted", "deleted-session", "expired", "session-demoted"]
)
def test_actual_management_routes_require_current_session(
    admin_session, mobile_client, auth_kind, state
):
    client, service = mobile_client
    tokens = _tokens()
    if state != "valid":
        _revoke(admin_session, state)
    headers = (
        {"Authorization": "Bearer " + tokens["access_token"]}
        if auth_kind == "bearer"
        else (
            {"Cookie": "session_id=synthetic-admin-session"}
            if auth_kind == "cookie"
            else {"X-Session-ID": "synthetic-admin-session"}
        )
    )
    get = client.get("/api/mobile/v1/admin/features", headers=headers)
    post = client.post(
        "/api/mobile/v1/admin/codex-super-employee/messages",
        headers=headers,
        json={"message": "synthetic boundary check"},
    )
    if state == "valid":
        assert get.status_code == post.status_code == 200, (get.text, post.text)
        service.invoke.assert_called_once()
    else:
        assert get.status_code in {401, 403}, get.text
        assert post.status_code in {401, 403}, post.text
        service.invoke.assert_not_called()


def test_enterprise_claim_cannot_use_old_admin_session_metadata(admin_session, mobile_client):
    client, service = mobile_client
    tokens = _tokens("enterprise")
    _revoke(admin_session, "expired")
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    response = client.post(
        "/api/mobile/v1/admin/codex-super-employee/messages",
        headers=headers,
        json={"message": "synthetic"},
    )
    assert response.status_code in {401, 403}
    service.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_admin_db_failure_never_reconstructs_user_or_refreshes(admin_session, monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import Mock

    from sqlalchemy.exc import OperationalError

    from app.security import mobile_jwt

    @contextmanager
    def unavailable():
        raise OperationalError("synthetic unavailable", {}, None)
        yield  # pragma: no cover

    tokens = _tokens()
    monkeypatch.setattr("app.db.session.get_host_db", unavailable)
    consume = Mock()
    monkeypatch.setattr(mobile_jwt, "_mark_refresh_jti_used", consume)
    assert (
        await get_mobile_user(
            _request(tokens["access_token"]), authorization="Bearer " + tokens["access_token"]
        )
        is None
    )
    assert refresh_mobile_access_token(tokens["refresh_token"]) is None
    consume.assert_not_called()


@pytest.mark.parametrize("state", ["disabled", "demoted", "expired", "deleted-session"])
def test_refresh_rejection_does_not_consume_jti(admin_session, monkeypatch, state):
    from unittest.mock import Mock

    from app.security import mobile_jwt

    tokens = _tokens()
    _revoke(admin_session, state)
    consume = Mock()
    monkeypatch.setattr(mobile_jwt, "_mark_refresh_jti_used", consume)
    assert refresh_mobile_access_token(tokens["refresh_token"]) is None
    consume.assert_not_called()


@pytest.mark.parametrize("state", ["valid", "demoted", "expired"])
def test_enterprise_claim_never_becomes_admin_via_session_meta(admin_session, mobile_client, state):
    client, service = mobile_client
    if state != "valid":
        _revoke(admin_session, state)
    response = client.get(
        "/api/mobile/v1/admin/features",
        headers={"Authorization": "Bearer " + _tokens("enterprise")["access_token"]},
    )
    assert response.status_code in {401, 403}
    service.invoke.assert_not_called()


@pytest.mark.parametrize(
    "kind,state,expected",
    [
        ("admin", "valid", 200),
        ("admin", "disabled", 401),
        ("enterprise", "valid", 403),
        ("enterprise", "expired", 403),
    ],
)
def test_ai_group_management_gate_does_not_trust_old_meta(
    admin_session, mobile_client, monkeypatch, kind, state, expected
):
    from unittest.mock import Mock

    from app.fastapi_routes import mobile_api_extensions as extension

    client, _ = mobile_client
    groups = Mock()
    groups.return_value.list_groups.return_value = []
    monkeypatch.setattr(extension, "AiGroupChatService", groups)
    if state != "valid":
        _revoke(admin_session, state)
    response = client.get(
        "/api/mobile/v1/ai-groups",
        headers={"Authorization": "Bearer " + _tokens(kind)["access_token"]},
    )
    assert response.status_code == expected, response.text
    if expected == 200:
        groups.assert_called_once_with(mode="admin")
    else:
        groups.assert_not_called()


def test_enterprise_relay_stays_enterprise_not_admin(admin_session, mobile_client, monkeypatch):
    from unittest.mock import Mock

    from app.fastapi_routes import mobile_api_extensions as extension

    client, service = mobile_client
    groups = Mock()
    groups.return_value.list_groups.return_value = []
    monkeypatch.setattr(extension, "AiGroupChatService", groups)
    headers = {
        "Authorization": "Bearer "
        + _tokens("enterprise", "mobile-relay-synthetic", 72)["access_token"]
    }
    assert client.get("/api/mobile/v1/ai-groups", headers=headers).status_code == 200
    groups.assert_called_once_with(mode="enterprise")
    assert client.get("/api/mobile/v1/admin/features", headers=headers).status_code == 403
    service.invoke.assert_not_called()


def test_disabled_cookie_cannot_validate_or_read_admin_identity(admin_session, mobile_client):
    client, service = mobile_client
    _revoke(admin_session, "disabled")
    headers = {"Cookie": "session_id=synthetic-admin-session"}
    for path in ("/api/mobile/v1/me", "/api/mobile/v1/auth/session/validate"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401, response.text
    service.invoke.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("uid", [True, 71.9, None, "invalid", 0, -1])
async def test_malformed_admin_identity_is_not_normalized_to_authority(admin_session, uid):
    tokens = _tokens(uid=uid)
    assert (
        await get_mobile_user(
            _request(tokens["access_token"]), authorization="Bearer " + tokens["access_token"]
        )
        is None
    )
    assert refresh_mobile_access_token(tokens["refresh_token"]) is None


@pytest.mark.asyncio
async def test_admin_refresh_token_cannot_be_used_as_access(admin_session):
    token = _tokens()["refresh_token"]
    assert await get_mobile_user(_request(token), authorization="Bearer " + token) is None


@pytest.mark.parametrize("role", ["admin", "super_admin", "owner"])
def test_current_management_role_and_portal_session_are_supported(
    admin_session, mobile_client, role
):
    with admin_session.begin() as db:
        db.get(User, 71).role = role
        db.query(Session).filter_by(
            session_id="synthetic-admin-session"
        ).one().account_kind = "admin_portal"
    client, _ = mobile_client
    token = _tokens("admin_portal")["access_token"]
    response = client.get(
        "/api/mobile/v1/admin/features",
        headers={
            "Authorization": "Bearer " + token,
            "X-Session-ID": "untrusted-other-session",
            "Cookie": "session_id=untrusted-other-session",
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["typ", "user_id", "session_id"])
async def test_incomplete_signed_admin_claims_are_rejected(admin_session, missing):
    import jwt

    from app.security import mobile_jwt

    payload = mobile_jwt.verify_mobile_jwt(_tokens()["access_token"])
    payload.pop(missing)
    token = jwt.encode(payload, mobile_jwt._secret_key(), algorithm="HS256")
    assert await get_mobile_user(_request(token), authorization="Bearer " + token) is None
