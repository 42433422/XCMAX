"""Proposal migrations retain ownership, claim outcomes and existing data."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.models.local_file import CodeEditProposal
from app.db.models.user import User
from tests.test_security.test_code_editor_authorization import (
    _apply,
    _assert_receipt,
    _diff,
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
