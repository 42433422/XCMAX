"""EmployeeChangeRequest API + apply。"""

from __future__ import annotations

import os
import types
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _reset_sqlalchemy_globals() -> None:
    import modstore_server.models as m

    if getattr(m, "_engine", None) is not None:
        m._engine.dispose()
    m._engine = None
    m._SessionFactory = None


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    _reset_sqlalchemy_globals()
    db = tmp_path / "cr_api.db"
    monkeypatch.setenv("MODSTORE_DB_PATH", str(db))
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_AUTO_APPROVE_ENABLED", "0")
    monkeypatch.setenv("MODSTORE_JWT_SECRET", "pytest-default-secret-at-least-32-characters")
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "1")

    from modstore_server.api.deps import require_admin
    from modstore_server.app import app
    from modstore_server.models import User, get_session_factory, init_db

    init_db(db)
    sf = get_session_factory(db)
    uname = f"adm_{uuid.uuid4().hex[:12]}"
    with sf() as s:
        s.add(User(username=uname, email=f"{uname}@t.t", password_hash="x", is_admin=True))
        s.commit()
    with sf() as s:
        row = s.query(User).filter(User.username == uname).first()
        uid = int(row.id) if row else 1

    admin = types.SimpleNamespace(id=uid, username=uname, is_admin=True, email=f"{uname}@t.t")
    app.dependency_overrides[require_admin] = lambda: admin
    yield TestClient(app), tmp_path
    app.dependency_overrides.pop(require_admin, None)


def test_change_request_approve_applies_file(admin_client):
    client, tmp_path = admin_client
    rel = "MODstore_deploy/modstore_server/api/_pytest_cr/note.txt"
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)

    from modstore_server.employee_change_request_service import defer_write_as_change_request

    cid = defer_write_as_change_request(
        "modstore-backend-api", str(tmp_path), rel, "approved-content"
    )
    r = client.post(f"/api/admin/change-requests/{cid}/approve")
    assert r.status_code == 200, r.text
    assert target.read_text(encoding="utf-8") == "approved-content"


def test_change_request_reject(admin_client):
    client, tmp_path = admin_client
    ws = str(tmp_path / "ws2")
    Path(ws).mkdir(parents=True, exist_ok=True)

    from modstore_server.employee_change_request_service import defer_write_as_change_request
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    db_path = os.environ.get("MODSTORE_DB_PATH", "")
    cid = defer_write_as_change_request("x", ws, "nope.txt", "x")
    r = client.post(
        f"/api/admin/change-requests/{cid}/reject",
        json={"reason": "no thanks"},
    )
    assert r.status_code == 200, r.text
    sf = get_session_factory()
    with sf() as s:
        row = s.get(EmployeeChangeRequest, cid)
        assert row is not None
        assert row.status == "rejected"
