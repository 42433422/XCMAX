"""Workspace proposals require a live session and remain bound to their owner."""

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.facades import session_facade
from app.db.db_base import Base
from app.db.models.code_edit import CodeEditProposal
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes import code_editor
from app.infrastructure.session import session_manager
from app.middleware.csrf import CSRFMiddleware
from app.middleware.industry_context import IndustryContextMiddleware
from app.utils.time import utc_now_naive


@pytest.fixture
def editor_http(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'editor.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(
        engine, tables=[User.__table__, UserSession.__table__, CodeEditProposal.__table__]
    )
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
    with Session(editor_http[2]) as db:
        assert db.query(CodeEditProposal).count() == 0
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


_PROCESS_REQUEST = r"""
import json, sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.fastapi_routes.code_editor import router
from app.middleware.csrf import CSRFMiddleware
from app.middleware.industry_context import IndustryContextMiddleware

requests = json.loads(sys.argv[1])
app = FastAPI()
app.add_middleware(CSRFMiddleware)
app.add_middleware(IndustryContextMiddleware)
app.include_router(router)
with TestClient(app) as client:
    client.get('/api/code-editor/status')
    client.headers.update({
        'X-CSRF-Token': client.cookies['csrf_token'],
        'X-XCAGI-AI-Tier': 'p2',
        'X-XCAGI-Elevated-Token': 'editor-fixture-p2',
    })
    results = []
    for method, path, body, owner in requests:
        client.headers['X-Session-ID'] = f'editor-session-{owner}'
        response = client.request(method, '/api/code-editor' + path, json=body)
        results.append({'status': response.status_code, 'body': response.json()})
    print(json.dumps(results))
"""


def _process_requests(*requests):
    result = subprocess.run(
        [sys.executable, "-c", _PROCESS_REQUEST, json.dumps(requests)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_proposal_survives_creator_exit_and_is_consumed_in_another_process(editor_http):
    _, root, _ = editor_http
    content = "synthetic<A&B>\nprint('你好 & welcome')\n"
    (created,) = _process_requests(
        ("POST", "/edit", {"path": "note.txt", "new_content": content}, 1)
    )
    assert created["status"] == 200
    edit_id = created["body"]["edit_id"]
    readback, foreign_user, foreign_tenant, applied, consumed, replay = _process_requests(
        ("GET", f"/diff/{edit_id}", None, 1),
        ("GET", f"/diff/{edit_id}", None, 2),
        ("POST", f"/apply/{edit_id}", {}, 3),
        ("POST", f"/apply/{edit_id}", {}, 1),
        ("GET", f"/diff/{edit_id}", None, 1),
        ("POST", f"/apply/{edit_id}", {}, 1),
    )
    assert readback["status"] == 200
    assert readback["body"]["unified_diff"] == created["body"]["unified_diff"]
    assert foreign_user["status"] == foreign_tenant["status"] == 404
    assert applied["status"] == 200
    assert (root / "note.txt").read_text(encoding="utf-8") == content
    assert consumed["status"] == replay["status"] == 404


def test_staging_failure_retains_retryable_proposal_and_original_bytes(editor_http, monkeypatch):
    client, root, _ = editor_http
    edit_id = _stage(client)
    _p2(client)
    with monkeypatch.context() as patch:

        def unavailable(*_args):
            raise OSError("synthetic publication failure")

        patch.setattr(code_editor.os, "fsync", unavailable)
        with pytest.raises(OSError, match="synthetic publication failure"):
            client.post(f"/api/code-editor/apply/{edit_id}", json={})
    assert (root / "note.txt").read_text() == "private fixture\n"
    assert list(root.glob(".code-edit-*")) == []
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 200
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 200


@pytest.mark.parametrize("published", [False, True])
def test_publication_exception_keeps_durable_claim_for_review(editor_http, monkeypatch, published):
    client, root, engine = editor_http
    edit_id = _stage(client)
    _p2(client)
    attempts = []
    replace = code_editor.os.replace

    def unknown_publication(source, destination):
        attempts.append(True)
        if published:
            replace(source, destination)
        raise OSError("synthetic uncertain publication")

    with monkeypatch.context() as patch:
        patch.setattr(code_editor.os, "replace", unknown_publication)
        with pytest.raises(OSError, match="synthetic uncertain publication"):
            client.post(f"/api/code-editor/apply/{edit_id}", json={})
    with Session(engine) as db:
        assert db.get(CodeEditProposal, edit_id).apply_state == "applying"
    # Even the original bytes, either unchanged or restored by a later operation,
    # cannot prove the previous edit did not publish.
    (root / "note.txt").write_text("private fixture\n")
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 200
    with monkeypatch.context() as patch:
        patch.setattr(code_editor.os, "replace", unknown_publication)
        assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 409
    assert attempts == [True]
    assert list(root.glob(".code-edit-*")) == []
    assert (root / "note.txt").read_text() == "private fixture\n"


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("restore_old", [False, True])
def test_uncertain_commit_never_republishes_the_file(
    editor_http, monkeypatch, committed, restore_old
):
    client, root, engine = editor_http
    edit_id = _stage(client)
    _p2(client)
    writes = []
    publish, commit = code_editor._publish_edit, Session.commit

    def observed_publication(*args, **kwargs):
        publish(*args, **kwargs)
        writes.append(True)

    def uncertain_commit(db):
        if writes:
            if committed:
                commit(db)
            raise OSError("synthetic commit confirmation failure")
        commit(db)

    with monkeypatch.context() as patch:
        patch.setattr(code_editor, "_publish_edit", observed_publication)
        patch.setattr(Session, "commit", uncertain_commit)
        with pytest.raises(OSError, match="synthetic commit confirmation failure"):
            client.post(f"/api/code-editor/apply/{edit_id}", json={})
    with Session(engine) as db:
        assert (db.get(CodeEditProposal, edit_id) is None) is committed
    assert (root / "note.txt").read_text() == "approved fixture\n"
    if restore_old:
        # A later legitimate rollback must not reactivate the uncertain old edit ID.
        (root / "note.txt").write_text("private fixture\n")
    with monkeypatch.context() as patch:
        patch.setattr(code_editor, "_publish_edit", observed_publication)
        retry = client.post(f"/api/code-editor/apply/{edit_id}", json={})
    assert retry.status_code == (404 if committed else 409)
    assert writes == [True]
    assert (root / "note.txt").read_text() == (
        "private fixture\n" if restore_old else "approved fixture\n"
    )


def test_noop_proposal_consumes_without_touching_file(editor_http):
    client, root, _ = editor_http
    client.headers["X-Session-ID"] = "editor-session-1"
    before = (root / "note.txt").stat().st_mtime_ns
    proposed = client.post(
        "/api/code-editor/edit", json={"path": "note.txt", "new_content": "private fixture\n"}
    )
    _p2(client)
    edit_id = proposed.json()["edit_id"]
    assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 200
    assert (root / "note.txt").stat().st_mtime_ns == before
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404


def test_competing_processes_cannot_publish_two_proposals_for_the_same_file(editor_http):
    client, root, _ = editor_http
    ids = [_stage(client), _stage(client)]
    # Pause the first publication, leaving a real overlap for the other HTTP worker.
    script = _PROCESS_REQUEST.replace(
        "from app.fastapi_routes.code_editor import router",
        """from pathlib import Path
import time
from app.fastapi_routes import code_editor
router = code_editor.router
publish = code_editor._publish_edit
def slow_publish(*args, **kwargs):
    with (Path(sys.argv[2]) / 'published').open('a') as audit:
        audit.write('write\\n')
    time.sleep(0.5)
    return publish(*args, **kwargs)
code_editor._publish_edit = slow_publish
(Path(sys.argv[2]) / ('ready-' + sys.argv[3])).touch()
while not (Path(sys.argv[2]) / 'go').exists():
    time.sleep(0.02)
""",
    )
    workers = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                json.dumps([("POST", f"/apply/{edit_id}", {}, 1)]),
                str(root),
                str(index),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        for index, edit_id in enumerate(ids)
    ]
    try:
        deadline = time.monotonic() + 60
        while not all((root / f"ready-{index}").exists() for index in range(2)):
            assert time.monotonic() < deadline, "HTTP workers did not reach the start barrier"
            time.sleep(0.05)
        (root / "go").touch()
        results = []
        for worker in workers:
            output, error = worker.communicate(timeout=60)
            assert worker.returncode == 0, error
            results.append(json.loads(output.strip().splitlines()[-1])[0]["status"])
        assert sorted(results) == [200, 409]
        assert (root / "published").read_text() == "write\n"
        assert (root / "note.txt").read_text() == "approved fixture\n"
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate()


def test_deleting_the_owner_also_removes_saved_proposal_content(editor_http):
    from sqlalchemy import delete

    client, _, engine = editor_http
    edit_id = _stage(client)
    with Session(engine) as db:
        assert db.get(CodeEditProposal, edit_id) is not None
        db.execute(delete(User).where(User.id == 1))
        db.commit()
    with Session(engine) as db:
        assert db.get(CodeEditProposal, edit_id) is None


def test_code_editor_proposal_upgrade_keeps_existing_data_and_is_idempotent(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import inspect, text

    from alembic import command

    url = f"sqlite:///{tmp_path / 'legacy.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with engine.begin() as db:
        db.execute(text("CREATE TABLE retained_fixture (value TEXT NOT NULL)"))
        db.execute(text("INSERT INTO retained_fixture VALUES ('kept<A&B>')"))
    command.stamp(config, "2026_11_21_enterprise_cognition")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as db:
        assert db.execute(text("SELECT value FROM retained_fixture")).scalar_one() == "kept<A&B>"
        assert "code_edit_proposals" in inspect(db).get_table_names()
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "2026_11_24_code_edit_proposals"
        )
    engine.dispose()
