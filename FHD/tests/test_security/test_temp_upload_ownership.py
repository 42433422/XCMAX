"""Temporary uploads belong to their authenticated account and tenant."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.facades import session_facade
from app.db.db_base import Base
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes import upload
from app.infrastructure.session import session_manager
from app.middleware.csrf import CSRFMiddleware
from app.utils.time import utc_now_naive


@pytest.fixture
def uploads_http(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    with Session(engine) as db:
        for uid, tenant in ((11, 100), (12, 100), (21, 200), (31, None), (32, None)):
            db.add(
                User(
                    id=uid,
                    username=f"upload-fixture-{uid}",
                    password="test-only",
                    is_active=True,
                    tenant_id=tenant,
                )
            )
            db.add(
                UserSession(
                    user_id=uid,
                    session_id=f"session-{uid}",
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
        db.commit()

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(session_manager, "get_host_db", database)
    monkeypatch.setattr(session_facade, "get_session_service", session_manager.SessionManager)
    monkeypatch.setattr(upload, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.include_router(upload.router)
    try:
        with TestClient(app) as client:
            client.get("/api/upload/config")
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            yield client, tmp_path, engine
    finally:
        engine.dispose()


def _create(client: TestClient, root: Path, owner: int) -> Path:
    client.cookies.set("session_id", f"session-{owner}")
    response = client.post(
        "/api/upload/temp", files={"file": ("document.png", b"synthetic-image", "image/png")}
    )
    assert response.status_code == 200
    payload = response.json()
    path = root / Path(payload["file_path"]).name
    assert payload["file_path"] == str(Path("uploads") / "temp" / path.name)
    assert payload["url"] == f"/uploads/temp/{path.name}"
    assert path.read_bytes() == b"synthetic-image"
    return path


@pytest.mark.parametrize("owner,other", [(11, 12), (11, 21), (31, 32)])
def test_other_account_cannot_delete_even_with_forged_identity_headers(uploads_http, owner, other):
    client, root, _ = uploads_http
    path = _create(client, root, owner)
    client.cookies.set("session_id", f"session-{other}")
    client.headers.update({"X-User-ID": str(owner), "X-Tenant-ID": "100"})
    assert client.delete(f"/api/upload/temp/{path.name}").status_code == 404
    assert path.read_bytes() == b"synthetic-image"
    client.cookies.set("session_id", f"session-{owner}")
    assert client.delete(f"/api/upload/temp/{path.name}").status_code == 200
    assert not path.exists()


def test_account_moved_to_another_tenant_cannot_delete_previous_tenant_upload(uploads_http):
    client, root, engine = uploads_http
    path = _create(client, root, 11)
    with Session(engine) as db:
        db.get(User, 11).tenant_id = 200
        db.commit()
    assert client.delete(f"/api/upload/temp/{path.name}").status_code == 404
    assert path.is_file()
    with Session(engine) as db:
        db.get(User, 11).tenant_id = 100
        db.commit()
    assert client.delete(f"/api/upload/temp/{path.name}").status_code == 200


def test_unowned_legacy_upload_is_preserved(uploads_http):
    client, root, _ = uploads_http
    path = root / "20261119_010000_abcdef12.png"
    path.write_bytes(b"legacy-image")
    client.cookies.set("session_id", "session-11")
    assert client.delete(f"/api/upload/temp/{path.name}").status_code == 404
    assert path.read_bytes() == b"legacy-image"


@pytest.mark.parametrize("state,status", [("anonymous", 401), ("expired", 401), ("disabled", 403)])
def test_invalid_session_cannot_upload_or_delete_existing_file(uploads_http, state, status):
    client, root, engine = uploads_http
    path = _create(client, root, 11)
    if state == "anonymous":
        client.cookies.delete("session_id")
    else:
        with Session(engine) as db:
            if state == "expired":
                db.query(UserSession).filter_by(session_id="session-11").one().expires_at = (
                    utc_now_naive() - timedelta(seconds=1)
                )
            else:
                db.get(User, 11).is_active = False
            db.commit()
    client.headers["X-User-ID"] = "11"
    assert client.delete(f"/api/upload/temp/{path.name}").status_code == status
    assert (
        client.post(
            "/api/upload/temp", files={"file": ("other.png", b"no", "image/png")}
        ).status_code
        == status
    )
    assert path.read_bytes() == b"synthetic-image"
    assert list(root.iterdir()) == [path]
