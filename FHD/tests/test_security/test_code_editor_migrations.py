"""Forward proposal-schema upgrades preserve authorization and uncertain claims."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models.local_file import CodeEditProposal
from app.db.models.user import User
from app.fastapi_routes import code_editor
from app.utils.time import utc_now_naive
from tests.test_security.test_code_editor_authorization import (
    _apply,
    _assert_receipt,
    _diff,
    _legacy_proposal_table,
    _p2,
    _stage,
)
from tests.test_security.test_code_editor_authorization import (
    editor_http as editor_http,
)


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
    from sqlalchemy import inspect, text

    url = f"sqlite:///{tmp_path / 'legacy.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, account_tier VARCHAR(32))"))
        db.execute(text("INSERT INTO users VALUES (1, 'ultra')"))
        db.execute(text("CREATE TABLE retained_fixture (value TEXT NOT NULL)"))
        db.execute(text("INSERT INTO retained_fixture VALUES ('kept<A&B>')"))
    _upgrade_proposals("2026_11_21_enterprise_cognition", starting_revision)
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
            == "2026_11_24_trial_session"
        )
    engine.dispose()


def _upgrade_proposal_schema(monkeypatch, engine):
    from alembic.config import Config

    from alembic import command

    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.stamp(config, "2026_11_24_code_edit_proposals")
    command.upgrade(config, "head")
    command.upgrade(config, "head")


def _leave_partial_proposal_scope(connection, edit_id, workspace):
    from sqlalchemy import text

    connection.execute(text("ALTER TABLE code_edit_proposals ADD COLUMN scope_json TEXT"))
    connection.execute(
        text("UPDATE code_edit_proposals SET scope_json=:scope WHERE edit_id=:edit_id"),
        {
            "edit_id": edit_id,
            "scope": json.dumps(
                {"user_id": 1, "tenant_id": 10, "workspace_root": str(workspace)}, sort_keys=True
            ),
        },
    )


@pytest.mark.parametrize("editor_http", ["legacy_proposals"], indirect=True)
@pytest.mark.parametrize("partial_scope", [False, True])
def test_forward_upgrade_preserves_legacy_scope_payload_and_nonreplayable_states(
    editor_http, monkeypatch, partial_scope
):
    from sqlalchemy import inspect, select

    client, root, engine = editor_http
    workspace = root / "旧工作区"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    (workspace / "note.txt").write_text("private fixture\n", encoding="utf-8")
    payload = json.dumps(
        {
            "path": str(workspace / "note.txt"),
            "rel": "note.txt",
            "old": "private fixture\n",
            "new": "原文 <A&B>\n",
            "unified_diff": "原文 <A&B>\n",
            "is_new_file": False,
            "old_sha256": code_editor._sha256_text("private fixture\n"),
        },
        ensure_ascii=False,
        indent=2,
    )
    legacy = _legacy_proposal_table(engine)
    created_at = utc_now_naive()
    states = ("pending", "applying", "applied", "unknown", "failed")
    with engine.begin() as db:
        db.execute(
            legacy.insert(),
            [
                {
                    "edit_id": f"legacy-{state}",
                    "owner_user_id": 1,
                    "tenant_id": 10,
                    "workspace_root": str(workspace),
                    "payload_json": payload,
                    "apply_state": state,
                    "created_at": created_at,
                }
                for state in states
            ]
            + [
                {
                    "edit_id": "legacy-no-tenant",
                    "owner_user_id": 2,
                    "tenant_id": None,
                    "workspace_root": str(workspace),
                    "payload_json": payload,
                    "apply_state": "pending",
                    "created_at": created_at,
                }
            ],
        )
        if partial_scope:
            _leave_partial_proposal_scope(db, "legacy-pending", workspace)
    _upgrade_proposal_schema(monkeypatch, engine)
    with Session(engine) as db:
        for state in states:
            row = db.get(CodeEditProposal, f"legacy-{state}")
            assert row.state == state and row.payload_json == payload and row.user_id == 1
            assert row.scope_json == json.dumps(
                {"user_id": 1, "tenant_id": 10, "workspace_root": str(workspace)}, sort_keys=True
            )
        assert (
            json.loads(db.get(CodeEditProposal, "legacy-no-tenant").scope_json)["tenant_id"] is None
        )
    import sqlalchemy as sa

    migrated = sa.Table("code_edit_proposals", sa.MetaData(), autoload_with=engine)
    columns = {
        column["name"]: column for column in inspect(engine).get_columns("code_edit_proposals")
    }
    assert columns["edit_id"]["type"].length == 64
    assert columns["user_id"]["nullable"] is False
    assert columns["state"]["nullable"] is False and columns["state"]["default"] is None
    assert columns["scope_json"]["nullable"] is False
    assert columns["workspace_root"]["nullable"] is True
    assert columns["created_at"]["nullable"] is True
    with engine.connect() as db:
        assert db.execute(select(migrated.c.created_at)).scalars().all() == [created_at] * 6
    assert inspect(engine).get_foreign_keys("code_edit_proposals")[0]["constrained_columns"] == [
        "user_id"
    ]
    assert inspect(engine).get_indexes("code_edit_proposals")[0]["column_names"] == [
        "user_id",
        "tenant_id",
    ]
    _p2(client)
    for owner in (2, 3):
        client.headers["X-Session-ID"] = f"editor-session-{owner}"
        assert client.get("/api/code-editor/diff/legacy-pending").status_code == 404
    client.headers["X-Session-ID"] = "editor-session-1"
    for state in ("applying", "unknown", "failed"):
        assert client.post(f"/api/code-editor/apply/legacy-{state}").status_code == 409
    assert client.post("/api/code-editor/apply/legacy-applied").status_code == 404
    assert (workspace / "note.txt").read_text() == "private fixture\n"
    assert client.get("/api/code-editor/diff/legacy-pending").status_code == 200
    assert client.post("/api/code-editor/apply/legacy-pending").status_code == 200
    assert (workspace / "note.txt").read_text() == "原文 <A&B>\n"
    fresh = client.post(
        "/api/code-editor/edit", json={"path": "note.txt", "new_content": "new draft"}
    )
    assert fresh.status_code == 200, fresh.text
    assert client.post(f"/api/code-editor/apply/{fresh.json()['edit_id']}").status_code == 200


@pytest.mark.parametrize("editor_http", ["legacy_proposals"], indirect=True)
@pytest.mark.parametrize("failure_kind", ["ambiguous_tenant", "empty_workspace", "after_batch"])
@pytest.mark.parametrize("partial_scope", [False, True])
def test_forward_upgrade_rejects_ambiguous_scope_without_touching_originals(
    editor_http, monkeypatch, failure_kind, partial_scope
):
    from contextlib import contextmanager

    import sqlalchemy as sa
    from alembic.operations import Operations
    from sqlalchemy import select, text

    _, root, engine = editor_http
    legacy = _legacy_proposal_table(engine)
    invalid = {
        "ambiguous_tenant": {"tenant_id": "ambiguous"},
        "empty_workspace": {"workspace_root": ""},
        "after_batch": {},
    }[failure_kind]
    rows = [
        {
            "edit_id": f"legacy-{number}",
            "owner_user_id": 1,
            "tenant_id": 10,
            "workspace_root": str(root),
            "payload_json": '{"original":"原文"}',
            "apply_state": "unknown",
            "created_at": utc_now_naive(),
            **(invalid if number else {}),
        }
        for number in (0, 1)
    ]
    with engine.begin() as db:
        db.execute(legacy.insert(), rows)
        if partial_scope:
            _leave_partial_proposal_scope(db, "legacy-0", root)
        original = sa.Table("code_edit_proposals", sa.MetaData(), autoload_with=db)
        before = db.execute(select(original)).all()
        schema = db.execute(
            text("SELECT sql FROM sqlite_master WHERE tbl_name='code_edit_proposals' ORDER BY name")
        ).all()
    expected = "cannot safely migrate code proposal"
    if failure_kind == "after_batch":
        original_batch = Operations.batch_alter_table

        @contextmanager
        def interrupted_batch(*args, **kwargs):
            with original_batch(*args, **kwargs) as batch:
                yield batch
            raise RuntimeError("interrupted after real batch DDL")

        monkeypatch.setattr(Operations, "batch_alter_table", interrupted_batch)
        expected = "interrupted after real batch DDL"
    with pytest.raises(RuntimeError, match=expected):
        _upgrade_proposal_schema(monkeypatch, engine)
    with engine.connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE tbl_name='code_edit_proposals' ORDER BY name"
                )
            ).all()
            == schema
        )
        assert db.execute(select(original)).all() == before
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "2026_11_24_merge_account_edit"
        )


def test_forward_upgrade_preserves_existing_current_shape_and_claims(editor_http, monkeypatch):
    from sqlalchemy import inspect, select

    _, root, engine = editor_http
    with Session(engine) as db:
        for state in ("pending", "applying", "applied", "unknown"):
            db.add(
                CodeEditProposal(
                    edit_id=f"current-{state}",
                    user_id=1,
                    scope_json=json.dumps(
                        {"user_id": 1, "tenant_id": 10, "workspace_root": str(root)}, sort_keys=True
                    ),
                    payload_json='{ "original": "原文 <A&B>" }',
                    state=state,
                )
            )
        db.commit()
    with engine.connect() as db:
        before = db.execute(select(CodeEditProposal.__table__)).all()
    columns = {col["name"] for col in inspect(engine).get_columns("code_edit_proposals")}
    _upgrade_proposal_schema(monkeypatch, engine)
    with engine.connect() as db:
        assert db.execute(select(CodeEditProposal.__table__)).all() == before
    assert {col["name"] for col in inspect(engine).get_columns("code_edit_proposals")} == columns


@pytest.mark.parametrize("editor_http", ["legacy_proposals"], indirect=True)
def test_empty_legacy_upgrade_accepts_current_orm_proposals(editor_http, monkeypatch):
    client, _, engine = editor_http
    _upgrade_proposal_schema(monkeypatch, engine)
    client.headers["X-Session-ID"] = "editor-session-1"
    created = client.post(
        "/api/code-editor/edit", json={"path": "note.txt", "new_content": "new proposal"}
    )
    assert created.status_code == 200, created.text
    edit_id = created.json()["edit_id"]
    assert client.get(f"/api/code-editor/diff/{edit_id}").status_code == 200
    _p2(client)
    assert client.post(f"/api/code-editor/apply/{edit_id}").status_code == 200


def _upgrade_proposals(starting_revision, *intermediate):
    from alembic.config import Config

    from alembic import command

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.stamp(config, starting_revision)
    for revision in (*intermediate, "head", "head"):
        command.upgrade(config, revision)
    return config


@pytest.mark.parametrize("legacy_schema", [True, False])
def test_forward_proposal_scope_migration_keeps_payload_claims_and_ownership(
    editor_http, legacy_schema
):
    import sqlite3
    from contextlib import closing

    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    client, root, engine = editor_http
    proposed = "原文 <value> &lt; &amp; 'quoted' \\literal\n"
    client.headers["X-Session-ID"] = "editor-session-1"
    ids = {}
    for state in ("pending", "applying", "applied", "unknown"):
        ids[state] = _stage(client, proposed)
    consumed_id = _stage(client)
    with engine.begin() as db:
        for state, edit_id in ids.items():
            db.execute(
                text("UPDATE code_edit_proposals SET state=:state WHERE edit_id=:edit_id"),
                {"state": state, "edit_id": edit_id},
            )
        db.execute(
            text("DELETE FROM code_edit_proposals WHERE edit_id=:edit_id"),
            {"edit_id": consumed_id},
        )
        columns = "edit_id, user_id, scope_json, payload_json, state"
        before = {
            row["edit_id"]: dict(row)
            for row in db.execute(text(f"SELECT {columns} FROM code_edit_proposals")).mappings()
        }
        if legacy_schema:
            CodeEditProposal.__table__.drop(db)
            db.execute(
                text(
                    "CREATE TABLE code_edit_proposals (edit_id VARCHAR(40) NOT NULL, "
                    "owner_user_id INTEGER NOT NULL, "
                    "tenant_id INTEGER, workspace_root TEXT NOT NULL, payload_json TEXT NOT NULL, "
                    "apply_state VARCHAR(16) NOT NULL DEFAULT 'pending', created_at DATETIME NOT NULL, "
                    "PRIMARY KEY (edit_id), "
                    "FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE)"
                )
            )
            db.execute(
                text(
                    "CREATE INDEX ix_code_edit_proposals_owner "
                    "ON code_edit_proposals(owner_user_id, tenant_id)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO code_edit_proposals VALUES "
                    "(:edit_id, :user_id, 10, :workspace, :payload_json, :state, :created_at)"
                ),
                [
                    {
                        **row,
                        "workspace": str(root.resolve()),
                        "created_at": "2026-11-23 00:00:00",
                    }
                    for row in before.values()
                ],
            )
        original_schema = db.execute(
            text("SELECT sql FROM sqlite_master WHERE name='code_edit_proposals'")
        ).scalar_one()
    config = _upgrade_proposals("2026_11_24_code_edit_proposals")
    with closing(sqlite3.connect(engine.url.database)) as db:
        db.row_factory = sqlite3.Row
        after = {
            row["edit_id"]: dict(row)
            for row in db.execute(f"SELECT {columns} FROM code_edit_proposals")
        }
        assert after == before
        assert consumed_id not in after
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        if legacy_schema:
            retained = db.execute(
                "SELECT tenant_id, workspace_root, created_at FROM code_edit_proposals"
            ).fetchall()
            assert [tuple(row) for row in retained] == [
                (10, str(root.resolve()), "2026-11-23 00:00:00")
            ] * 4
        else:
            assert (
                db.execute(
                    "SELECT sql FROM sqlite_master WHERE name='code_edit_proposals'"
                ).fetchone()[0]
                == original_schema
            )
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "2026_11_24_trial_session"
        )
    assert ScriptDirectory.from_config(config).get_heads() == ["2026_11_24_trial_session"]
    _p2(client)
    client.headers["X-Session-ID"] = "editor-session-2"
    _diff(client, ids["pending"], 404)
    client.headers["X-Session-ID"] = "editor-session-1"
    for state in ("applying", "unknown", "applied"):
        _assert_receipt(client, engine, ids[state], state, legacy=True)
        _apply(client, ids[state], 404 if state == "applied" else 409)
    _diff(client, consumed_id, 404)
    _apply(client, consumed_id, 404)
    assert (root / "note.txt").read_text() == "private fixture\n"
    _apply(client, ids["pending"])
    assert (root / "note.txt").read_bytes() == proposed.encode("utf-8")
    _assert_receipt(client, engine, ids["pending"], "applied", proposed)
    _apply(client, ids["pending"], 404)
    # The migrated schema also accepts new ORM inserts and retains owner deletion.
    fresh_id = _stage(client)
    with engine.begin() as db:
        db.execute(text("DELETE FROM users WHERE id=1"))
    with closing(sqlite3.connect(engine.url.database)) as db:
        assert db.execute("SELECT count(*) FROM code_edit_proposals").fetchone() == (0,)
    _diff(client, fresh_id, 401)
