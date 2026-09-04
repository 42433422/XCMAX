"""EmployeeChangeRequest API + apply。"""

from __future__ import annotations

import types
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TEST_JWT_SECRET = "jwt-test-secret-" + ("x" * 32)


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
    monkeypatch.setenv("MODSTORE_JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "1")

    from modstore_server.api.deps import require_admin
    from modstore_server.app import app
    from modstore_server.models import User, get_session_factory, init_db

    init_db(db)
    sf = get_session_factory(db)
    uname = f"adm_{uuid.uuid4().hex[:12]}"
    with sf() as s:
        s.add(
            User(username=uname, email=f"{uname}@t.t", password_hash="x", is_admin=True)
        )
        s.commit()
    with sf() as s:
        row = s.query(User).filter(User.username == uname).first()
        uid = int(row.id) if row else 1

    admin = types.SimpleNamespace(
        id=uid, username=uname, is_admin=True, email=f"{uname}@t.t"
    )
    app.dependency_overrides[require_admin] = lambda: admin
    yield TestClient(app), tmp_path
    app.dependency_overrides.pop(require_admin, None)


def test_change_request_approve_applies_file(admin_client):
    client, tmp_path = admin_client
    rel = "MODstore_deploy/modstore_server/api/_pytest_cr/note.txt"
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)

    from modstore_server.employee_change_request_service import (
        defer_write_as_change_request,
    )

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

    from modstore_server.employee_change_request_service import (
        defer_write_as_change_request,
    )
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

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


def test_high_risk_change_request_waits_for_human_through_autonomy_ssot(
    admin_client, tmp_path, monkeypatch
):
    _client, workspace = admin_client
    monkeypatch.setenv("MODSTORE_AUTO_APPROVE_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_AUTO_APPROVE_REQUIRE_CI", "0")
    monkeypatch.setenv("MODSTORE_CR_NARROW_CI_ENABLED", "0")
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "auto_approve")
    monkeypatch.setenv(
        "XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "autonomy.sqlite3")
    )
    monkeypatch.setenv(
        "XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "autonomy.jsonl")
    )

    from modstore_server.employee_change_request_service import (
        defer_write_as_change_request,
    )
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    target = workspace / ".env.production"
    cid = defer_write_as_change_request(
        "autonomy-code-writer",
        str(workspace),
        ".env.production",
        "SAFE_TEST_VALUE=1\n",
    )

    assert not target.exists()
    with get_session_factory()() as session:
        row = session.get(EmployeeChangeRequest, cid)
        assert row is not None
        assert row.risk_level == "high"
        assert row.status == "pending"

    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()
    from app.domain.autonomy.audit_log import list_autonomy_audit

    audit_rows = list_autonomy_audit(action_id=f"change-request:{cid}:apply")
    assert audit_rows and audit_rows[0]["action"] == "code_write"
    audit = audit_rows[0]
    assert audit["decision"] == "require_human"
    assert audit["approver"] is None
