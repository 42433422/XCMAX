"""SQL ownership: distinct attempts, live leases, fencing, and migration."""

from __future__ import annotations

import importlib.util
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from alembic.migration import MigrationContext
from alembic.operations import Operations
from modstore_server import models
from modstore_server import node_coordinator as nc


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'claims.sqlite'}", connect_args={"timeout": 10}
    )
    models.IncidentEvent.__table__.create(engine)
    models.IncidentClaim.__table__.create(engine)
    sf = sessionmaker(bind=engine)
    with sf() as db:
        db.add(models.IncidentEvent(id=42, event_type="on_error", source="test"))
        db.commit()
    monkeypatch.setattr(nc, "get_session_factory", lambda: sf)
    yield sf
    engine.dispose()


def _claim_process(url, barrier, queue):
    engine = sa.create_engine(url, connect_args={"timeout": 10})
    sf = sessionmaker(bind=engine)
    nc.get_session_factory = lambda: sf
    barrier.wait(timeout=15)
    queue.put(nc.claim_incident_for_node(42))
    engine.dispose()


def test_same_pid_threads_cannot_reenter(factory):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(nc.claim_incident_for_node, [42, 42]))
    assert sum(r["claimed"] for r in results) == 1
    winner = next(r for r in results if r["claimed"])
    assert winner["owner_token"]
    assert nc.release_incident_claim(42)["released"] is False
    assert nc.release_incident_claim(42, owner_token=winner["owner_token"])["released"]


@pytest.mark.parametrize("preceding_test_root", [None, "FHD"])
def test_two_processes_have_one_effective_owner(factory, monkeypatch, preceding_test_root):
    modstore_root = Path(__file__).resolve().parents[1]
    if preceding_test_root:
        # Integrated runs collect FHD tests too; both projects have a tests package.
        monkeypatch.syspath_prepend(str(modstore_root.parents[1] / preceding_test_root))
    # spawn imports the target's module afresh using the parent's sys.path snapshot.
    # Anchor it to this project instead of whichever tests package was collected last.
    monkeypatch.syspath_prepend(str(modstore_root))
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    url = str(factory.kw["bind"].url)
    processes = [ctx.Process(target=_claim_process, args=(url, barrier, queue)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert sum(r["claimed"] for r in results) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
        queue.join_thread()


def test_long_task_renews_beyond_thirty_minutes(factory, monkeypatch):
    now = [datetime(2026, 10, 20)]
    monkeypatch.setattr(nc, "_database_time", lambda session: now[0])
    claim = nc.claim_incident_for_node(42, ttl_seconds=900)
    for _ in range(5):
        now[0] += timedelta(seconds=600)
        assert nc.renew_incident_claim(42, claim["owner_token"], ttl_seconds=900)
        assert nc.claim_incident_for_node(42)["claimed"] is False


def test_old_token_cannot_release_renew_or_commit_after_takeover(factory):
    with nc.incident_claim_scope(42) as old:
        with factory() as db:
            db.query(models.IncidentClaim).update({"lease_until": datetime(2000, 1, 1)})
            db.commit()
        new = nc.claim_incident_for_node(42)
        assert new["claimed"] and new["generation"] > old["generation"]
        assert nc.release_incident_claim(42, owner_token=old["owner_token"])["released"] is False
        assert nc.renew_incident_claim(42, old["owner_token"]) is False
        with pytest.raises(nc.IncidentClaimLost):
            nc.assert_incident_claim(42)
    with factory() as db:
        assert db.get(models.IncidentClaim, 42).owner_token == new["owner_token"]


def test_explicit_nested_scope_retains_token(factory):
    with nc.incident_claim_scope(42) as outer:
        with nc.incident_claim_scope(42) as inner:
            assert inner["owner_token"] == outer["owner_token"]
            with factory() as db:
                nc.assert_incident_claim(42, session=db)
                db.commit()
    assert nc.current_claim() is None


def test_unavailable_database_fails_closed(monkeypatch, tmp_path):
    def unavailable():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(nc, "get_session_factory", unavailable)
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    assert nc.claim_incident_for_node(42)["claimed"] is False
    with pytest.raises(nc.IncidentClaimLost):
        with nc.incident_claim_scope(42):
            pytest.fail("must not execute")
    assert not list(tmp_path.iterdir())


def test_existing_database_migration_preserves_events_and_is_idempotent():
    path = Path(__file__).parents[1] / "alembic/versions/20261020_incident_ownership.py"
    spec = importlib.util.spec_from_file_location("incident_ownership_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE incident_events (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO incident_events VALUES (42)")
        conn.exec_driver_sql("CREATE TABLE event_outbox (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO event_outbox VALUES (7)")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
            migration.downgrade()
        assert conn.exec_driver_sql("SELECT id FROM incident_events").scalar_one() == 42
        assert conn.exec_driver_sql(
            "SELECT id, claim_token, claim_until FROM event_outbox"
        ).one() == (7, "", None)
        assert {"incident_claims", "incident_inbox"} <= set(sa.inspect(conn).get_table_names())
    engine.dispose()
