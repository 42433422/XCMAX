"""A PAT must not become an unrestricted login or administrator identity."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import auth_service
from modstore_server.models import DeveloperToken, User


@pytest.fixture
def pat_case(tmp_path, monkeypatch):
    from modstore_server import (
        browser_handoff_api,
        customer_issue_api,
        developer_api,
        market_catalog_api,
        production_line_api,
    )
    from modstore_server.api import catalog, config, market_routes

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pat.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    User.__table__.create(engine)
    DeveloperToken.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    for module in (
        "modstore_server.auth_service",
        "modstore_server.application.auth",
        "modstore_server.infrastructure.db",
    ):
        monkeypatch.setattr(module + ".get_session_factory", lambda: sessions)
    with sessions.begin() as db:
        db.add_all(
            [
                User(
                    id=7,
                    username="synthetic-admin",
                    password_hash="unused",
                    is_admin=True,
                ),
                User(
                    id=8,
                    username="synthetic-member",
                    password_hash="unused",
                    is_admin=False,
                ),
            ]
        )
    save = Mock()
    monkeypatch.setattr(config.library_paths, "save_config", save)
    monkeypatch.setattr(config, "get_config", lambda: {"ok": True})
    handoff = Mock(return_value={"code": "synthetic-not-a-live-code"})
    monkeypatch.setattr(browser_handoff_api, "issue_code", handoff)
    app = FastAPI()
    for router in (
        config.router,
        catalog.router,
        developer_api.router,
        production_line_api.router,
    ):
        app.include_router(router)
    app.include_router(market_routes.router)
    app.include_router(market_catalog_api.router, prefix="/api")
    app.include_router(browser_handoff_api.router, prefix="/api")
    app.include_router(customer_issue_api.router, prefix="/api/customer-service")
    with TestClient(app) as client:
        yield client, sessions, save, handoff
    engine.dispose()


def _pat(sessions, scopes, *, state="valid", uid=7):
    raw, prefix, digest = auth_service.generate_pat()
    with sessions.begin() as db:
        row = DeveloperToken(
            user_id=uid,
            name="synthetic",
            token_prefix=prefix,
            token_hash=digest,
            scopes_json=json.dumps(scopes),
        )
        if state == "revoked":
            row.revoked_at = datetime.now(UTC)
        elif state == "expired":
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        elif state == "deleted-user":
            db.get(User, uid).deleted_at = datetime.now(UTC)
        db.add(row)
    return raw


@pytest.mark.parametrize(
    "scopes",
    [
        [],
        ["workflow:read"],
        ["catalog:read"],
        ["workflow:execute"],
        ["employee:execute"],
        ["webhook:manage"],
        ["llm:use"],
        ["mod:sync"],
    ],
)
def test_pat_cannot_write_admin_config_or_issue_credentials(pat_case, scopes):
    client, sessions, save, handoff = pat_case
    headers = {"Authorization": "Bearer " + _pat(sessions, scopes)}
    response = client.put(
        "/api/config",
        headers=headers,
        json={"xcagi_backend_url": "http://test.invalid"},
    )
    assert response.status_code == 403, response.text
    save.assert_not_called()
    token = client.post(
        "/api/developer/tokens",
        headers=headers,
        json={"name": "must-not-exist", "scopes": ["employee:execute"]},
    )
    assert token.status_code == 403, token.text
    login = client.post(
        "/api/auth/browser-handoff",
        headers=headers,
        json={"target": "/wallet", "purpose": "wallet"},
    )
    assert login.status_code == 403, login.text
    handoff.assert_not_called()
    with sessions() as db:
        assert db.query(DeveloperToken).count() == 1


@pytest.mark.parametrize("state", ["revoked", "expired", "deleted-user"])
def test_invalid_pat_stays_unauthenticated(pat_case, state):
    client, sessions, save, _ = pat_case
    response = client.put(
        "/api/config",
        headers={"Authorization": "Bearer " + _pat(sessions, ["mod:sync"], state=state)},
        json={},
    )
    assert response.status_code == 401
    save.assert_not_called()


@pytest.mark.parametrize("uid,expected", [(7, 200), (8, 403)])
def test_jwt_user_authority_is_unchanged(pat_case, uid, expected):
    client, _, save, _ = pat_case
    token = auth_service.create_access_token(uid, "synthetic", is_admin=uid == 7)
    response = client.put("/api/config", headers={"Authorization": "Bearer " + token}, json={})
    assert response.status_code == expected, response.text
    assert save.call_count == (1 if expected == 200 else 0)


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/api/admin/production-line/stop", "POST", {}),
        (
            "/api/customer-service/issues/pending-runtime?host_sha=" + "a" * 40,
            "GET",
            None,
        ),
        (
            "/api/mods/synthetic/file",
            "PUT",
            {"path": "synthetic.txt", "content": "must-not-write"},
        ),
    ],
)
def test_pat_rejection_covers_direct_admin_and_alternate_user_dependencies(
    pat_case, path, method, body, monkeypatch
):
    from modstore_server import customer_issue_shared_release, production_line_orchestrator

    forbidden = [
        Mock(side_effect=AssertionError("protected business action reached")) for _ in range(3)
    ]
    monkeypatch.setattr(
        production_line_orchestrator, "get_production_line_orchestrator", forbidden[0]
    )
    from modstore_server.api import catalog

    monkeypatch.setattr(catalog, "write_text_under_mod", forbidden[1])
    monkeypatch.setattr(customer_issue_shared_release, "bind_shared_release", forbidden[2])
    client, sessions, _, _ = pat_case
    response = client.request(
        method,
        path,
        headers={"Authorization": "Bearer " + _pat(sessions, ["workflow:read"])},
        json=body,
    )
    assert response.status_code == 403, response.text
    for action in forbidden:
        action.assert_not_called()


@pytest.mark.parametrize("optional", ["auth_deps", "market_shared", "market_routes"])
def test_optional_user_does_not_downgrade_pat_scope_denial(pat_case, optional):
    from fastapi import HTTPException

    from modstore_server.api import market_routes
    from modstore_server.api.auth_deps import get_optional_user
    from modstore_server.market_shared import _optional_current_user

    _get_optional_user = market_routes._get_optional_user

    _, sessions, _, _ = pat_case
    fn = {
        "auth_deps": get_optional_user,
        "market_shared": _optional_current_user,
        "market_routes": _get_optional_user,
    }[optional]
    assert fn(None) is None
    with pytest.raises(HTTPException) as error:
        fn("Bearer " + _pat(sessions, ["catalog:read"]))
    assert error.value.status_code == 403


@pytest.mark.parametrize("bearer_prefix", ["Bearer ", "Bearer  "])
@pytest.mark.parametrize("cookie", [False, True])
@pytest.mark.parametrize("scopes,expected", [(["mod:sync"], 200), (["catalog:read"], 403)])
def test_scoped_mod_sync_pat_keeps_scope_and_csrf_boundaries(
    pat_case, monkeypatch, tmp_path, cookie, scopes, expected, bearer_prefix
):
    from modstore_server import app as app_module
    from modstore_server import mod_sync_catalog_api as sync
    from modstore_server.api.csrf import CSRFMiddleware

    _, sessions, _, _ = pat_case
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.setattr(app_module, "_cfg", lambda: None)
    monkeypatch.setattr(sync, "resolved_xcagi", lambda config: tmp_path)
    monkeypatch.setattr(sync, "_lib", lambda: tmp_path)
    deploy = Mock(return_value=["synthetic"])
    monkeypatch.setattr(sync, "deploy_to_xcagi", deploy)
    app = FastAPI()
    app.include_router(sync.router)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        if cookie:
            client.cookies.set("csrf_token", "synthetic-cookie")
        response = client.post(
            "/v1/mod-sync/push",
            json={"mod_ids": ["synthetic"]},
            headers={"Authorization": bearer_prefix + _pat(sessions, scopes)},
        )
    assert response.status_code == expected, response.text
    assert deploy.call_count == (1 if expected == 200 else 0)
    if expected == 403:
        assert "mod:sync" in response.text


def test_pat_identity_preserves_scopes_without_generic_user_access(pat_case):
    from modstore_server.application.auth import AuthApplicationService, ScopeAuthorizationError

    _, sessions, _, _ = pat_case
    token = _pat(sessions, ["mod:sync"])
    identity = auth_service.resolve_pat_identity(token)
    assert identity.user.id == 7 and identity.scopes == ("mod:sync",)
    with pytest.raises(ScopeAuthorizationError):
        AuthApplicationService().current_user_from_authorization("Bearer " + token)


@pytest.mark.parametrize("path", ["/api/mods", "/api/auth/me", "/api/market/catalog"])
def test_real_optional_routes_deny_scoped_pat_instead_of_anonymous(pat_case, path):
    client, sessions, _, _ = pat_case
    response = client.get(
        path, headers={"Authorization": "Bearer " + _pat(sessions, ["catalog:read"])}
    )
    assert response.status_code == 403, response.text


def test_invalid_scope_json_cannot_grant_generic_permissions(pat_case):
    client, sessions, save, _ = pat_case
    token = _pat(sessions, [])
    with sessions.begin() as db:
        db.query(DeveloperToken).one().scopes_json = "not-valid-json"
    response = client.put("/api/config", json={}, headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403
    save.assert_not_called()


@pytest.mark.parametrize("owned", [True, False])
def test_mod_sync_member_pat_cannot_write_shared_host_even_when_owned(
    pat_case, monkeypatch, tmp_path, owned
):
    from modstore_server import app as app_module
    from modstore_server import mod_sync_catalog_api as sync

    _, sessions, _, _ = pat_case
    monkeypatch.setattr(app_module, "_cfg", lambda: None)
    monkeypatch.setattr(sync, "resolved_xcagi", lambda config: tmp_path)
    monkeypatch.setattr(sync, "_lib", lambda: tmp_path)
    monkeypatch.setattr(
        sync,
        "user_owns_mod",
        lambda uid, mid: uid == 8 and mid == "synthetic" and owned,
    )
    deploy = Mock(return_value=["synthetic"])
    monkeypatch.setattr(sync, "deploy_to_xcagi", deploy)
    app = FastAPI()
    app.include_router(sync.router)
    with TestClient(app) as client:
        response = client.post(
            "/v1/mod-sync/push",
            json={"mod_ids": ["synthetic"]},
            headers={"Authorization": "Bearer " + _pat(sessions, ["mod:sync"], uid=8)},
        )
    assert response.status_code == 403, response.text
    deploy.assert_not_called()


def test_jwt_can_still_manage_credentials_and_request_handoff(pat_case):
    client, sessions, _, handoff = pat_case
    token = auth_service.create_access_token(7, "synthetic-admin", is_admin=True)
    headers = {"Authorization": "Bearer " + token}
    response = client.post(
        "/api/developer/tokens",
        headers=headers,
        json={"name": "synthetic-positive", "scopes": ["mod:sync"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["scopes"] == ["mod:sync"]
    with sessions() as db:
        assert db.query(DeveloperToken).count() == 1
    response = client.post(
        "/api/auth/browser-handoff",
        headers=headers,
        json={"target": "/wallet", "purpose": "wallet"},
    )
    assert response.status_code == 200
    handoff.assert_called_once_with(7, "/wallet", "wallet")
