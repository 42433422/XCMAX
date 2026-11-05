"""Existing-only serving admission on explicit synthetic, preprovisioned HOST files."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.db.models import Permission, Role, Tenant, User, UserSession, role_permissions
from app.db.models.agent import (
    AgentRunRecord,
    AgentTaskCommandRecord,
    AgentTaskExecutionRecord,
    AgentTaskRecord,
)
from app.db.models.agent_approval import AgentApprovalConsumption
from app.db.models.agent_business_action import AgentBusinessActionRecord
from app.db.models.product_edit_claim import ProductEditClaimRecord
from app.db.models.workflow import WorkflowPlan
from app.desktop_runtime import database_generation_registry as registry


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / "control"
    (root / "config").mkdir(parents=True)
    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    target = tmp_path / "host.sqlite"
    engine = create_engine("sqlite:///" + str(target))
    for model in (
        AgentRunRecord,
        AgentTaskRecord,
        AgentTaskCommandRecord,
        AgentTaskExecutionRecord,
        AgentApprovalConsumption,
        AgentBusinessActionRecord,
        ProductEditClaimRecord,
        WorkflowPlan,
        User,
        UserSession,
        Permission,
        Role,
        Tenant,
    ):
        model.__table__.create(engine)
    role_permissions.create(engine)
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE admission_grants (permission TEXT NOT NULL)")
        db.exec_driver_sql("INSERT INTO admission_grants VALUES ('unchanged')")
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    engine.dispose()  # A clean shutdown need not leave WAL/SHM sidecars behind.
    anchor = registry.owned_host_anchor(target)
    marker = root / "config" / "owned-source-protocol.json"
    anchor.write_text(json.dumps({"version": 2, "control_root": str(root)}))
    marker.write_text(json.dumps({"version": 2, "state": "owned_sources_enrolled"}))
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(root))
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(target))
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE", raising=False)
    # Deliberately different live admission: staging must neither reset nor steal it.
    live = (tmp_path / "other", (str(tmp_path / "other.sqlite"), 7, 9))
    monkeypatch.setattr(registry, "_owned_profile", live)
    return SimpleNamespace(
        root=root,
        target=target,
        anchor=anchor,
        marker=marker,
        base=tmp_path,
        live=live,
        config=SimpleNamespace(
            OWNED_SOURCE_PROFILE="guarded-host-v1", DATABASE_URL="sqlite:///" + str(target)
        ),
    )


def files(prepared):
    """DBMS-managed sidecars are not authority/enrollment files."""
    return {
        str(path.relative_to(prepared.base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in prepared.base.rglob("*")
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def test_clean_shutdown_readiness_is_staged_and_preserves_storage(prepared):
    before = files(prepared)
    assert not Path(str(prepared.target) + "-wal").exists()
    assert not Path(str(prepared.target) + "-shm").exists()
    info = prepared.target.stat()
    expected = (prepared.root, (str(prepared.target), info.st_dev, info.st_ino))
    assert registry.validate_existing_owned_profile(prepared.config) == expected
    assert registry._owned_profile is prepared.live
    assert files(prepared) == before
    # Repeated admission models a fresh startup against a cleanly closed WAL DB.
    assert registry.validate_existing_owned_profile(prepared.config) == expected
    assert files(prepared) == before
    assert not list(prepared.base.rglob("*.lock"))
    with sqlite3.connect(prepared.target.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert db.execute("SELECT * FROM admission_grants").fetchall() == [("unchanged",)]


@pytest.mark.parametrize("missing", ["target", "anchor", "marker"])
def test_missing_authority_never_connects_or_recreates(prepared, monkeypatch, missing):
    getattr(prepared, missing).unlink()
    before = files(prepared)

    def denied(*_args, **_kwargs):
        raise AssertionError("must reject before any engine construction")

    monkeypatch.setattr("sqlalchemy.create_engine", denied)
    with pytest.raises(registry.GenerationObservationError):
        registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live


@pytest.mark.parametrize("selected", ["configured", "effective"])
def test_url_mismatch_never_creates_alternate_database(prepared, monkeypatch, selected):
    alternate = prepared.base / "must-not-exist.sqlite"
    if selected == "configured":
        prepared.config.DATABASE_URL = "sqlite:///" + str(alternate)
    else:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(alternate))
    before = files(prepared)

    def denied(*_args, **_kwargs):
        raise AssertionError("must reject before any engine construction")

    monkeypatch.setattr("sqlalchemy.create_engine", denied)
    with pytest.raises(registry.GenerationObservationError):
        registry.validate_existing_owned_profile(prepared.config)
    assert not alternate.exists()
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live


def test_nonwal_is_rejected_without_mode_or_data_change(prepared):
    with sqlite3.connect(prepared.target) as db:
        assert db.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
    before = files(prepared)
    with pytest.raises(registry.GenerationObservationError):
        registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live
    with sqlite3.connect(prepared.target.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)


@pytest.mark.parametrize("table", ["agent_tasks", "agent_task_commands"])
@pytest.mark.parametrize("corruption", ["missing", "trigger"])
def test_repository_support_requires_exact_preexisting_schema(prepared, table, corruption):
    with sqlite3.connect(prepared.target) as db:
        if corruption == "missing":
            db.execute(f"DROP TABLE {table}")
        else:
            db.execute(f"CREATE TRIGGER extra AFTER INSERT ON {table} BEGIN SELECT 1; END")
    before = files(prepared)
    with pytest.raises(registry.GenerationObservationError):
        registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live


def test_admission_validation_connection_is_physically_readonly(prepared, monkeypatch):
    original = registry._validate_owned_host_schema

    def validate(db):
        original(db)
        raw = db.connection().connection.driver_connection
        raw.execute("PRAGMA query_only=OFF")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            raw.execute("DELETE FROM admission_grants")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            raw.execute("CREATE TABLE forbidden (id INTEGER)")
        raw.execute("PRAGMA query_only=ON")

    monkeypatch.setattr(registry, "_validate_owned_host_schema", validate)
    before = files(prepared)
    registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live


@pytest.mark.parametrize("path", ["target", "anchor", "marker"])
def test_profile_rejects_authority_symlink_without_adopting(prepared, path):
    target = getattr(prepared, path)
    original = target.with_name(target.name + ".original")
    target.rename(original)
    target.symlink_to(original)
    before = files(prepared)
    with pytest.raises(registry.GenerationObservationError):
        registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live


def test_validation_observes_committed_uncheckpointed_wal(prepared):
    # An immutable/nolock connection would miss this schema change. Keep the
    # writer open so SQLite cannot checkpoint its committed WAL on last close.
    with closing(sqlite3.connect(prepared.target)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("DROP TABLE agent_tasks")
        writer.commit()
        assert Path(str(prepared.target) + "-wal").stat().st_size > 0
        before = files(prepared)
        with pytest.raises(registry.GenerationObservationError):
            registry.validate_existing_owned_profile(prepared.config)
        assert files(prepared) == before
        assert registry._owned_profile is prepared.live


@pytest.mark.parametrize(
    "change", ["undeclared", "unsupported", "desktop", "relative-root", "missing-url", "uri"]
)
def test_invalid_server_profile_is_rejected_before_connect(prepared, monkeypatch, change):
    if change == "undeclared":
        prepared.config.OWNED_SOURCE_PROFILE = ""
    elif change == "unsupported":
        monkeypatch.setattr(registry.sys, "platform", "unsupported")
    elif change == "desktop":
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    elif change == "relative-root":
        monkeypatch.setenv("XCAGI_DATA_DIR", "relative-control")
    elif change == "missing-url":
        del prepared.config.DATABASE_URL
    else:
        prepared.config.DATABASE_URL += "?mode=rw"
    before = files(prepared)

    def denied(*_args, **_kwargs):
        raise AssertionError("invalid profile must not connect")

    monkeypatch.setattr("sqlalchemy.create_engine", denied)
    with pytest.raises(registry.GenerationObservationError):
        registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("users", "is_active"),
        ("sessions", "entitled_mod_ids_json"),
        ("permissions", "code"),
        ("roles", "name"),
        ("tenants", "owner_user_id"),
        ("role_permissions", "permission_id"),
    ],
)
@pytest.mark.parametrize("corruption", ["missing-table", "missing-column"])
def test_admission_requires_preexisting_auth_schema_without_repair(
    prepared, table, column, corruption
):
    with closing(sqlite3.connect(prepared.target)) as db:
        if corruption == "missing-table":
            db.execute(f"DROP TABLE {table}")
        else:
            db.execute(f"ALTER TABLE {table} RENAME COLUMN {column} TO offline_missing_column")
        db.commit()
    before = files(prepared)
    with pytest.raises(
        RuntimeError, match="guarded authentication requires existing complete schema"
    ):
        registry.validate_existing_owned_profile(prepared.config)
    assert files(prepared) == before
    assert registry._owned_profile is prepared.live
