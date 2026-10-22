"""Caller authorization precedes local, remote and service-account fallback."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import Session, User
from app.fastapi_routes import xcmax_admin
from app.utils.time import utc_now_naive

pytestmark = pytest.mark.release_gate


@pytest.fixture
def digest_client(tmp_path, monkeypatch):
    import app.db as database
    from app.fastapi_routes import aibiz_terminal_api

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    with sessions.begin() as db:
        for uid, kind in ((7, "admin"), (8, "enterprise")):
            db.add(
                User(id=uid, username=f"synthetic-{uid}", password="unused", role=kind, tier=kind)
            )
            db.add(
                Session(
                    session_id=f"synthetic-session-{uid}",
                    user_id=uid,
                    account_kind=kind,
                    market_is_admin=kind == "admin",
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
    from app.application import digest_email_app_service as digest

    payload = {"success": True, "data": [{"id": 1, "subject": "synthetic-private"}]}
    local = AsyncMock(return_value=payload)
    for name in (
        "list_daily_digests_local",
        "get_daily_digest_local",
        "get_daily_digest_artifacts_local",
        "action_items_stats_local",
        "list_action_items_local",
    ):
        monkeypatch.setattr(digest, name, local)
    proxy = AsyncMock(return_value=payload)
    remote = AsyncMock(return_value=payload)
    monkeypatch.setattr(xcmax_admin, "_market_admin_proxy", proxy)
    monkeypatch.setattr(xcmax_admin, "_fetch_remote_xcmax_daily_digests", remote)
    from app.application.aibiz_surface_images import png_http_response

    async def synthetic_audit(*args, **kwargs):
        if "view" in kwargs:
            return png_http_response(b"synthetic-png", view=kwargs["view"])
        return {"synthetic": True}

    audit = AsyncMock(side_effect=synthetic_audit)
    for name in ("build_terminal_payload", "fetch_surface_page_payload", "serve_surface_image"):
        monkeypatch.setattr(aibiz_terminal_api, name, audit)
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    app.include_router(aibiz_terminal_api.router)
    with TestClient(app) as client:
        yield client, local, proxy, remote, audit
    engine.dispose()


@pytest.mark.parametrize("local_preferred", [False, True])
@pytest.mark.parametrize("uid,expected", [(None, 401), (8, 403)])
@pytest.mark.parametrize(
    "suffix",
    [
        "/daily-digests",
        "/daily-digests/1",
        "/daily-digests/1/artifacts",
        "/action-items",
        "/action-items/stats",
    ],
)
def test_digest_read_rejects_before_service_credentials(
    digest_client, monkeypatch, local_preferred, uid, expected, suffix
):
    client, local, proxy, remote, _ = digest_client
    monkeypatch.setattr(
        "app.application.modstore_local_client.prefer_local_modstore", lambda: local_preferred
    )
    headers = {} if uid is None else {"Cookie": f"session_id=synthetic-session-{uid}"}
    response = client.get("/api/xcmax/admin" + suffix, headers=headers)
    assert response.status_code == expected, response.text
    for action in (local, proxy, remote):
        action.assert_not_awaited()


@pytest.mark.parametrize("status", [401, 403])
def test_upstream_denial_cannot_fall_back_to_internal_key(digest_client, monkeypatch, status):
    client, _, proxy, remote, _ = digest_client
    monkeypatch.setattr(
        "app.application.modstore_local_client.prefer_local_modstore", lambda: False
    )
    proxy.return_value = JSONResponse({"denied": True}, status_code=status)
    response = client.get(
        "/api/xcmax/admin/daily-digests", headers={"Cookie": "session_id=synthetic-session-7"}
    )
    assert response.status_code == status
    assert response.json() == {"denied": True}
    remote.assert_not_awaited()


@pytest.mark.parametrize("local_preferred", [False, True])
def test_admin_digest_normal_path_still_works(digest_client, monkeypatch, local_preferred):
    client, local, proxy, _, _ = digest_client
    monkeypatch.setattr(
        "app.application.modstore_local_client.prefer_local_modstore", lambda: local_preferred
    )
    response = client.get(
        "/api/xcmax/admin/daily-digests", headers={"Cookie": "session_id=synthetic-session-7"}
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["subject"] == "synthetic-private"
    assert (local if local_preferred else proxy).await_count == 1


@pytest.mark.parametrize(
    "suffix",
    [
        "/web-terminal?refresh=true",
        "/desk-terminal?refresh=true",
        "/app-terminal?refresh=true",
        "/surface-image",
        "/surface-page",
    ],
)
@pytest.mark.parametrize("uid,expected", [(None, 401), (8, 403)])
def test_audit_routes_reject_before_service_account_or_local_audit(
    digest_client, suffix, uid, expected
):
    client, _, _, _, audit = digest_client
    headers = {} if uid is None else {"Cookie": f"session_id=synthetic-session-{uid}"}
    response = client.get("/api/xcmax/aibiz" + suffix, headers=headers)
    assert response.status_code == expected, response.text
    audit.assert_not_awaited()


def test_admin_audit_route_retains_access(digest_client):
    client, _, _, _, audit = digest_client
    response = client.get(
        "/api/xcmax/aibiz/web-terminal", headers={"Cookie": "session_id=synthetic-session-7"}
    )
    assert response.status_code == 200
    audit.assert_awaited_once()


def test_desktop_cannot_use_admin_session_for_platform_audit(digest_client, monkeypatch):
    client, _, _, _, audit = digest_client
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    response = client.get(
        "/api/xcmax/aibiz/web-terminal", headers={"Cookie": "session_id=synthetic-session-7"}
    )
    assert response.status_code == 403
    audit.assert_not_awaited()


@pytest.mark.parametrize("view", ["", "thumb", "viewport", "full"])
def test_authenticated_audit_images_are_never_publicly_cached(digest_client, view):
    client, _, _, _, audit = digest_client
    response = client.get(
        "/api/xcmax/aibiz/surface-image",
        params={"view": view},
        headers={"Cookie": "session_id=synthetic-session-7"},
    )
    assert response.status_code == 200
    assert response.content == b"synthetic-png"
    assert response.headers["cache-control"] == "private, no-store"
    audit.assert_awaited_once()
