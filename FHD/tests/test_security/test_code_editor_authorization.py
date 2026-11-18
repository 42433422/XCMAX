"""Workspace proposals require a live session and remain bound to their owner."""

from contextlib import contextmanager
from datetime import timedelta

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
from app.fastapi_routes import code_editor
from app.infrastructure.session import session_manager
from app.middleware.csrf import CSRFMiddleware
from app.middleware.industry_context import IndustryContextMiddleware
from app.utils.time import utc_now_naive


@pytest.fixture
def editor_http(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    with Session(engine) as db:
        for uid, tenant, active in ((1, 10, True), (2, 10, True), (3, 20, True), (4, 10, False)):
            db.add(
                User(
                    id=uid,
                    username=f"editor-fixture-{uid}",
                    password="test-only",
                    tenant_id=tenant,
                    tier="enterprise",
                    is_active=active,
                )
            )
            db.add(
                UserSession(
                    user_id=uid,
                    session_id=f"editor-session-{uid}",
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
        db.add(
            UserSession(
                user_id=1,
                session_id="editor-session-expired",
                expires_at=utc_now_naive() - timedelta(hours=1),
            )
        )
        db.commit()

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(session_manager, "get_host_db", database)
    monkeypatch.setattr(session_facade, "get_session_service", session_manager.SessionManager)
    monkeypatch.setattr(code_editor, "_EDIT_STORE", {})
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("FHD_AI_ELEVATED_TOKEN", "editor-fixture-p2")
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    (tmp_path / "note.txt").write_text("private fixture\n", encoding="utf-8")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(code_editor.router)
    try:
        with TestClient(app) as client:
            assert client.get("/api/code-editor/status").status_code == 200
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            yield client, tmp_path, engine
    finally:
        engine.dispose()


def _p2(client):
    client.headers.update({"X-XCAGI-AI-Tier": "p2", "X-XCAGI-Elevated-Token": "editor-fixture-p2"})


def _stage(client):
    client.headers["X-Session-ID"] = "editor-session-1"
    response = client.post(
        "/api/code-editor/edit", json={"path": "note.txt", "new_content": "approved fixture\n"}
    )
    assert response.status_code == 200
    return response.json()["edit_id"]


@pytest.mark.parametrize(
    "identity,status", [(None, 401), ("forged", 401), ("expired", 401), (4, 403)]
)
def test_file_routes_require_active_session_even_with_p2(editor_http, identity, status):
    client, root, _ = editor_http
    if identity is not None:
        client.headers["X-Session-ID"] = f"editor-session-{identity}"
    client.headers["X-User-ID"] = "1"
    client.headers["X-Tenant-ID"] = "10"
    _p2(client)
    for method, path, body in (
        ("POST", "/analyze", {"path": "note.txt"}),
        ("POST", "/edit", {"path": "new/file.txt", "new_content": "x", "create_if_missing": True}),
        ("GET", "/diff/unknown", None),
        ("POST", "/apply/unknown", {}),
        ("POST", "/draft", {"path": "note.txt", "instruction": "change"}),
    ):
        response = client.request(method, "/api/code-editor" + path, json=body)
        assert response.status_code == status, (path, response.status_code)
    assert not (root / "new").exists()
    assert code_editor._EDIT_STORE == {}
    assert (root / "note.txt").read_text() == "private fixture\n"


@pytest.mark.parametrize("other_user", [2, 3])
def test_proposal_cannot_be_read_or_applied_by_another_account(editor_http, other_user):
    client, root, _ = editor_http
    edit_id = _stage(client)
    client.headers["X-Session-ID"] = f"editor-session-{other_user}"
    _p2(client)
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 404
    assert (root / "note.txt").read_text() == "private fixture\n"
    client.headers["X-Session-ID"] = "editor-session-1"
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 200
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 200
    assert (root / "note.txt").read_text() == "approved fixture\n"


def test_proposal_does_not_follow_owner_into_another_tenant(editor_http):
    client, root, engine = editor_http
    edit_id = _stage(client)
    with Session(engine) as db:
        db.get(User, 1).tenant_id = 30
        db.commit()
    _p2(client)
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 404
    assert (root / "note.txt").read_text() == "private fixture\n"


def test_proposal_does_not_follow_a_reconfigured_workspace(editor_http, monkeypatch):
    client, root, _ = editor_http
    edit_id = _stage(client)
    replacement = root / "replacement"
    replacement.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(replacement))
    _p2(client)
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 404
    assert (root / "note.txt").read_text() == "private fixture\n"


def test_owner_still_needs_p2_and_disk_content_must_match(editor_http):
    client, root, _ = editor_http
    edit_id = _stage(client)
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 403
    (root / "note.txt").write_text("independent change\n", encoding="utf-8")
    _p2(client)
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 409
    assert (root / "note.txt").read_text() == "independent change\n"


def test_apply_revalidates_the_staged_path(editor_http):
    client, root, _ = editor_http
    edit_id = _stage(client)
    outside = root.parent / "outside-editor-fixture.txt"
    outside.write_text("private fixture\n", encoding="utf-8")
    path = root / "note.txt"
    path.unlink()
    path.symlink_to(outside)
    _p2(client)
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 400
    assert outside.read_text() == "private fixture\n"
