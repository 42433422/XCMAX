"""Workspace proposals require a live session and remain bound to their owner."""

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.facades import session_facade
from app.db.db_base import Base
from app.db.models.local_file import CodeEditProposal
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
            db.commit()

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


def _editor_worker(
    root, database_url, edit_id, session_id, method, results, barrier=None, written=None
):
    """Each spawn imports the production router and reloads the real SQL session."""
    import os

    os.environ["DATABASE_URL"] = database_url
    os.environ["WORKSPACE_ROOT"] = root
    os.environ["FHD_AI_ELEVATED_TOKEN"] = "editor-fixture-p2"
    os.environ.pop("XCAGI_DESKTOP_MODE", None)
    if written is not None:
        publish = code_editor._publish_edit

        def pause_after_effect(path, *args, **kwargs):
            result = publish(path, *args, **kwargs)
            written.set()
            barrier.wait(timeout=30)
            return result

        code_editor._publish_edit = pause_after_effect
    app = FastAPI()
    app.include_router(code_editor.router)
    headers = {
        "X-Session-ID": session_id,
        "X-XCAGI-AI-Tier": "p2",
        "X-XCAGI-Elevated-Token": "editor-fixture-p2",
    }
    if barrier is not None and written is None:
        barrier.wait(timeout=30)
    with TestClient(app) as client:
        endpoint = "diff" if method == "GET" else "apply"
        response = client.request(method, f"/api/code-editor/{endpoint}/{edit_id}", headers=headers)
        results.put((response.status_code, response.json()))


def _worker_response(spawn_context, root, engine, edit_id, *, owner=1, method="GET"):
    results = spawn_context.Queue()
    worker = spawn_context.Process(
        target=_editor_worker,
        args=(str(root), str(engine.url), edit_id, f"editor-session-{owner}", method, results),
    )
    worker.start()
    try:
        response = results.get(timeout=40)
        worker.join(timeout=10)
        assert worker.exitcode == 0
        return response
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)


def test_proposal_survives_worker_restart_and_preserves_owner(editor_http, spawn_context):
    client, root, engine = editor_http
    edit_id = _stage(client)
    for owner in (2, 3):
        assert _worker_response(spawn_context, root, engine, edit_id, owner=owner)[0] == 404
    status, body = _worker_response(spawn_context, root, engine, edit_id)
    assert status == 200
    assert "approved fixture" in body["unified_diff"]
    assert _worker_response(spawn_context, root, engine, edit_id, method="POST")[0] == 200
    assert (root / "note.txt").read_text() == "approved fixture\n"
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404
    with Session(engine) as db:
        assert db.get(CodeEditProposal, edit_id).state == "applied"


@pytest.mark.parametrize("mode", ["existing", "new", "same_proposal"])
def test_concurrent_process_apply_preserves_original_version(editor_http, spawn_context, mode):
    client, root, engine = editor_http
    client.headers["X-Session-ID"] = "editor-session-1"
    path = "new.txt" if mode == "new" else "note.txt"
    proposals = []
    for content in ("first worker\n", "second worker\n"):
        response = client.post(
            "/api/code-editor/edit",
            json={"path": path, "new_content": content, "create_if_missing": mode == "new"},
        )
        assert response.status_code == 200
        proposals.append(response.json()["edit_id"])
    if mode == "same_proposal":
        proposals[1] = proposals[0]
    results = spawn_context.Queue()
    barrier = spawn_context.Barrier(2)
    workers = [
        spawn_context.Process(
            target=_editor_worker,
            args=(
                str(root),
                str(engine.url),
                edit_id,
                "editor-session-1",
                "POST",
                results,
                barrier,
            ),
        )
        for edit_id in proposals
    ]
    try:
        for worker in workers:
            worker.start()
        outcomes = [results.get(timeout=40), results.get(timeout=40)]
        for worker in workers:
            worker.join(timeout=10)
            assert worker.exitcode == 0
        assert sorted(status for status, _ in outcomes) == [
            200,
            404 if mode == "same_proposal" else 409,
        ]
        assert (root / path).read_text() in {"first worker\n", "second worker\n"}
        with Session(engine) as db:
            rows = db.query(CodeEditProposal).filter(CodeEditProposal.edit_id.in_(proposals)).all()
            assert sum(row.state == "applied" for row in rows) == 1
            assert sum(row.state == "pending" for row in rows) == (mode != "same_proposal")
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=10)


def test_process_death_after_write_keeps_original_claim_blocked(editor_http, spawn_context):
    client, root, engine = editor_http
    edit_id = _stage(client)
    results, written, hold = spawn_context.Queue(), spawn_context.Event(), spawn_context.Barrier(2)
    worker = spawn_context.Process(
        target=_editor_worker,
        args=(
            str(root),
            str(engine.url),
            edit_id,
            "editor-session-1",
            "POST",
            results,
            hold,
            written,
        ),
    )
    worker.start()
    try:
        assert written.wait(timeout=40)
        worker.terminate()
        worker.join(timeout=10)
        assert worker.exitcode is not None and worker.exitcode != 0
        assert (root / "note.txt").read_text() == "approved fixture\n"
        # Even restoring the original bytes cannot turn an uncertain write into
        # a new attempt: the committed claim, rather than content alone, fences it.
        (root / "note.txt").write_text("private fixture\n")
        status, body = _worker_response(spawn_context, root, engine, edit_id, method="POST")
        assert status == 409 and "verification" in body["detail"]
        assert (root / "note.txt").read_text() == "private fixture\n"
        with Session(engine) as db:
            assert db.get(CodeEditProposal, edit_id).state == "applying"
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)


def test_proposal_migration_preserves_claims_on_rollback(tmp_path):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    migration_path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_24_code_edit_proposals.py"
    )
    spec = importlib.util.spec_from_file_location("code_edit_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                connection.execute(
                    User.__table__.insert(),
                    {"id": 1, "username": "original-owner", "password": "fixture-only"},
                )
                for state in ("pending", "applying", "applied"):
                    connection.execute(
                        CodeEditProposal.__table__.insert(),
                        {
                            "edit_id": f"edit_{state}",
                            "user_id": 1,
                            "scope_json": "{}",
                            "payload_json": "{}",
                            "state": state,
                        },
                    )
                migration.downgrade()
                migration.upgrade()
                assert {
                    row.edit_id: row.state
                    for row in connection.execute(CodeEditProposal.__table__.select())
                } == {f"edit_{state}": state for state in ("pending", "applying", "applied")}
                assert (
                    inspect(connection).get_foreign_keys("code_edit_proposals")[0]["referred_table"]
                    == "users"
                )
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
    client, root, engine = editor_http
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
    with Session(engine) as db:
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


def test_installed_http_stack_preserves_code_bytes_and_sql_scope(editor_http, monkeypatch):
    import hashlib
    import json

    from app.config import TestingConfig
    from app.fastapi_app import factory

    _, root, engine = editor_http
    original = "title = '<原文> &lt; &amp; \"quoted\"'\n"
    proposed = (
        "if total < limit and name == '<script>literal()</script>':\n"
        '    print("A&B \\"quoted\\" \'single\' &lt; &amp; \\\\literal\\\\")\n'
    )
    (root / "note.txt").write_text(original, encoding="utf-8")
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "0")
    monkeypatch.setattr(factory, "_app_singleton", None)
    app = factory.create_fastapi_app(TestingConfig, enable_cors=False, enable_docs=False)
    with TestClient(app) as client:
        client.cookies.set("csrf_token", "editor-input-integrity")
        client.headers["X-CSRF-Token"] = "editor-input-integrity"
        raw = json.dumps({"path": "note.txt", "new_content": proposed}, ensure_ascii=False)
        assert (
            client.post(
                "/api/code-editor/edit", content=raw, headers={"Content-Type": "application/json"}
            ).status_code
            == 401
        )
        client.headers["X-Session-ID"] = "editor-session-1"
        response = client.post(
            "/api/code-editor/edit", content=raw, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200, response.text
        edit_id = response.json()["edit_id"]
        with Session(engine) as db:
            row = db.get(CodeEditProposal, edit_id)
            payload = json.loads(row.payload_json)
            assert payload["new"] == proposed
            assert payload["old_sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
            assert row.user_id == 1
            assert json.loads(row.scope_json) == {
                "user_id": 1,
                "tenant_id": 10,
                "workspace_root": str(root.resolve()),
            }
        assert client.post(f"/api/code-editor/apply/{edit_id}").status_code == 403
        _p2(client)
        client.headers["X-Session-ID"] = "editor-session-2"
        assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404
        assert client.post(f"/api/code-editor/apply/{edit_id}").status_code == 404
        assert (root / "note.txt").read_bytes() == original.encode("utf-8")
        client.headers["X-Session-ID"] = "editor-session-1"
        assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 200
        assert client.post(f"/api/code-editor/apply/{edit_id}").status_code == 200
        assert (root / "note.txt").read_bytes() == proposed.encode("utf-8")
        assert client.post(f"/api/code-editor/apply/{edit_id}").status_code == 404


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
        assert db.get(CodeEditProposal, edit_id).state == "applying"
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
        assert db.get(CodeEditProposal, edit_id).state == ("applied" if committed else "applying")
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


@pytest.mark.parametrize("restore_prior_snapshot", [False, True])
def test_deleting_the_owner_also_removes_saved_proposal_content(
    editor_http, monkeypatch, restore_prior_snapshot
):
    import sqlite3
    from contextlib import closing

    from sqlalchemy import delete

    from app.domain.shared_services.database_service import DatabaseService

    client, root, engine = editor_http
    edit_id = _stage(client)
    if restore_prior_snapshot:
        service = DatabaseService()
        backups = root / "backups"
        backups.mkdir()
        monkeypatch.setattr(service, "_get_backup_dir", lambda: str(backups))
        snapshot = service.backup_database()
        assert snapshot["success"] is True, snapshot
        with closing(sqlite3.connect(snapshot["file_path"])) as backup:
            assert backup.execute(
                "SELECT state FROM code_edit_proposals WHERE edit_id = ?", (edit_id,)
            ).fetchone() == ("pending",)
    with Session(engine) as db:
        assert db.get(CodeEditProposal, edit_id) is not None
        db.execute(delete(User).where(User.id == 1))
        db.commit()
    with Session(engine) as db:
        assert db.get(User, 1) is None
        assert db.get(CodeEditProposal, edit_id) is None
    if restore_prior_snapshot:
        restored = service.restore_database(snapshot["file_path"])
        assert restored["success"] is True, restored
        with Session(engine) as db:
            assert db.get(User, 1) is not None
            assert db.get(CodeEditProposal, edit_id) is None
        # Restoring the earlier account/session must not restore the deleted
        # proposal bytes or allow its formerly pending edit ID to publish.
        _p2(client)
        assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 404
        assert client.post(f"/api/code-editor/apply/{edit_id}", json={}).status_code == 404
        assert (root / "note.txt").read_text() == "private fixture\n"


@pytest.mark.parametrize(
    "starting_revision",
    [
        "2026_11_21_enterprise_cognition",
        "2026_11_24_account_license",
        "2026_11_24_code_edit_proposals",
    ],
)
def test_code_editor_proposal_upgrade_keeps_existing_data_and_is_idempotent(
    tmp_path, monkeypatch, starting_revision
):
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import inspect, text

    from alembic import command

    url = f"sqlite:///{tmp_path / 'legacy.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, account_tier VARCHAR(32))"))
        db.execute(text("INSERT INTO users VALUES (1, 'ultra')"))
        db.execute(text("CREATE TABLE retained_fixture (value TEXT NOT NULL)"))
        db.execute(text("INSERT INTO retained_fixture VALUES ('kept<A&B>')"))
    command.stamp(config, "2026_11_21_enterprise_cognition")
    command.upgrade(config, starting_revision)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as db:
        assert db.execute(text("SELECT value FROM retained_fixture")).scalar_one() == "kept<A&B>"
        assert "code_edit_proposals" in inspect(db).get_table_names()
        assert db.execute(
            text(
                "SELECT account_tier, account_license_plan_id, account_license_expires_at FROM users"
            )
        ).all() == [("ultra", None, None)]
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "2026_11_24_merge_account_edit"
        )
    engine.dispose()
