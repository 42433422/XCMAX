"""Actual admin surface routes must authenticate before reading private content."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from modstore_server import auth_service, models


@pytest.fixture
def surface_case(tmp_path, monkeypatch):
    from modstore_server import admin_employee_autonomy_helpers  # noqa: F401
    from modstore_server import (
        daily_digest_surface_audit,
        digest_identity,
        release_train,
        xcmax_admin_api,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'surface.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    for table in (models.User.__table__, models.DailyDigestRecord.__table__):
        table.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        db.add_all(
            [
                models.User(
                    id=7,
                    username="synthetic-admin",
                    password_hash="unused",
                    is_admin=True,
                ),
                models.User(
                    id=8,
                    username="synthetic-member",
                    password_hash="unused",
                    is_admin=False,
                ),
            ]
        )
        db.add(
            models.DailyDigestRecord(
                id=1,
                day="synthetic-day",
                subject="private-summary",
                body_text="private-text",
                body_html="private-html",
                recipients_json='["private@example.invalid"]',
            )
        )
    monkeypatch.setattr(auth_service, "get_session_factory", lambda: sessions)
    reads = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: (
            reads.append(statement)
            if statement.lstrip().lower().startswith("select")
            and "daily_digest_records" in statement.lower()
            else None
        ),
    )
    monkeypatch.setattr(models, "get_session_factory", lambda: sessions)
    identity = Mock(return_value={"code": "SYNTH1", "valid": True})
    monkeypatch.setattr(digest_identity, "resolve_digest_identity_for_xcmax", identity)
    audit = AsyncMock(return_value={"ok": True, "results": [], "lane_analysis": {}})
    monkeypatch.setattr(daily_digest_surface_audit, "run_surface_audit_async", audit)
    monkeypatch.setattr(daily_digest_surface_audit, "_save_dir", lambda day: None)
    monkeypatch.setattr(release_train, "snapshot_public", lambda: {"current": "synthetic-version"})
    for key in (
        "XCAGI_MARKET_INTERNAL_API_KEY",
        "MODSTORE_INTERNAL_API_KEY",
        "XCAGI_CS_INTAKE_LINK_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "synthetic-internal-test-key")
    app = FastAPI()
    app.include_router(xcmax_admin_api.router)
    with TestClient(app) as client:
        yield client, reads, identity, audit
    engine.dispose()


PATHS = [
    "/admin/daily-digests",
    "/admin/daily-digests/1",
    "/admin/digest-identity",
    "/admin/surface-audit/lane?refresh=true",
]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("actor,expected", [(None, 401), (8, 403)])
def test_private_surfaces_reject_before_data_or_refresh(surface_case, path, actor, expected):
    client, reads, identity, audit = surface_case
    headers = (
        {}
        if actor is None
        else {
            "Authorization": "Bearer "
            + auth_service.create_access_token(actor, "synthetic", is_admin=False)
        }
    )
    response = client.get("/api/xcmax" + path, headers=headers)
    assert response.status_code == expected, response.text
    assert "private-" not in response.text and "SYNTH1" not in response.text
    assert reads == []
    identity.assert_not_called()
    audit.assert_not_awaited()


@pytest.mark.parametrize("path", PATHS)
def test_current_admin_can_read_or_request_refresh(surface_case, path):
    client, _, _, audit = surface_case
    response = client.get(
        "/api/xcmax" + path,
        headers={
            "Authorization": "Bearer "
            + auth_service.create_access_token(7, "synthetic-admin", is_admin=True)
        },
    )
    assert response.status_code == 200, response.text
    if "refresh" in path:
        audit.assert_awaited_once()


@pytest.mark.parametrize(
    "path,expected",
    [(PATHS[0], 200), (PATHS[1], 200), (PATHS[2], 401), (PATHS[3], 401)],
)
def test_internal_reader_cannot_read_identity_or_trigger_audit(surface_case, path, expected):
    client, _, identity, audit = surface_case
    response = client.get(
        "/api/xcmax" + path,
        headers={"X-Internal-API-Key": "synthetic-internal-test-key"},
    )
    assert response.status_code == expected, response.text
    identity.assert_not_called()
    audit.assert_not_awaited()


def test_public_release_identity_stays_public(surface_case):
    client, _, _, _ = surface_case
    response = client.get("/api/xcmax/release-train")
    assert response.status_code == 200
    assert response.json()["data"]["current"] == "synthetic-version"


@pytest.mark.parametrize("path", PATHS)
def test_forged_bearer_does_not_read_private_surfaces(surface_case, path):
    client, reads, identity, audit = surface_case
    response = client.get(
        "/api/xcmax" + path, headers={"Authorization": "Bearer synthetic-invalid"}
    )
    assert response.status_code == 401
    assert reads == []
    identity.assert_not_called()
    audit.assert_not_awaited()


@pytest.mark.parametrize("key", ["", "wrong-key"])
@pytest.mark.parametrize("path", PATHS[:2])
def test_internal_reader_requires_matching_secret(surface_case, path, key):
    client, reads, _, _ = surface_case
    response = client.get("/api/xcmax" + path, headers={"X-Internal-API-Key": key})
    assert response.status_code == 401
    assert reads == []


def test_cached_surface_audit_is_not_public(surface_case):
    client, _, _, audit = surface_case
    response = client.get("/api/xcmax/admin/surface-audit/lane?refresh=false")
    assert response.status_code == 401
    audit.assert_not_awaited()
