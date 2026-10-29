"""Real generic stores/restores cannot expose or rewind catalog authority.

Reserved rows below are retention sentinels, not fabricated valid catalog claims.
These guards do not implement cross-database reconciliation or authorize effects.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

from app.application.workflow.plan_store import (
    CATALOG_HEAD_PREFIX,
    CATALOG_OPERATION_PREFIX,
    CATALOG_RECEIPT_PREFIX,
    WorkflowPlanStore,
)
from app.application.workflow.workflow_types import PlanGraph
from app.db.models.workflow import WorkflowPlan
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_owned_mixed_source_substrate import enrolled
from tests.test_application.test_owned_mixed_source_substrate import host as host

PREFIXES = (CATALOG_OPERATION_PREFIX, CATALOG_HEAD_PREFIX, CATALOG_RECEIPT_PREFIX)


@pytest.fixture
def plans(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plans.sqlite'}")
    WorkflowPlan.__table__.create(engine)
    factory = sessionmaker(engine)
    try:
        yield WorkflowPlanStore(factory), engine
    finally:
        engine.dispose()


def raw_rows(engine):
    with engine.connect() as db:
        return [
            tuple(row) for row in db.exec_driver_sql("SELECT * FROM workflow_plans ORDER BY id")
        ]


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("variant", ["canonical", "spaced-upper", "unicode"])
def test_real_generic_store_cannot_create_mutate_read_or_list_authority(plans, prefix, variant):
    store, engine = plans
    key = prefix + "original"
    if variant == "spaced-upper":
        key = "  " + key.upper() + "  "
    elif variant == "unicode":
        key = "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in key)
    # Test preexisting opaque authority, deliberately not parseable as a PlanGraph.
    with engine.begin() as db:
        db.execute(
            insert(WorkflowPlan.__table__),
            {
                "plan_id": key,
                "user_id": "u",
                "session_id": "s",
                "intent": "catalog_products_v1",
                "plan_json": "private-sentinel",
                "runtime_context": "opaque-head",
                "status": "pending_awaiting",
            },
        )
    before = raw_rows(engine)
    for require_commit in (False, True):
        with pytest.raises(ValueError, match="protected catalog"):
            store.save(
                plan=PlanGraph(key, "ordinary"), user_id="other", require_commit=require_commit
            )
    with pytest.raises(ValueError, match="protected catalog"):
        store.update_status(key, "cancelled", "erase original")
    assert store.load(key) is None
    assert store.load_plan(key) is None
    assert store.list_active("u", limit=1, session_id="s") == []
    assert raw_rows(engine) == before
    with pytest.raises(ValueError):
        store.save(plan=PlanGraph(key + "-new", "ordinary"))
    assert raw_rows(engine) == before


def test_ordinary_workflow_retains_save_update_load_hydration_and_visible_limit(plans):
    store, engine = plans
    for prefix in PREFIXES:
        with engine.begin() as db:
            db.execute(
                insert(WorkflowPlan.__table__),
                {
                    "plan_id": prefix + "opaque",
                    "updated_at": datetime(2099, 1, 1),
                    "user_id": "u",
                    "session_id": "s",
                    "plan_json": "private",
                    "status": "pending_awaiting",
                },
            )
    plan = PlanGraph("wp-ordinary", "ordinary")
    assert (
        store.save(
            plan=plan, user_id="u", session_id="s", status="pending_awaiting", require_commit=True
        )
        == plan.plan_id
    )
    assert store.load_plan(plan.plan_id).intent == "ordinary"
    assert [row["plan_id"] for row in store.list_active("u", 1, session_id="s")] == [plan.plan_id]
    assert store.list_active("foreign", 1, session_id="s") == []
    store.update_status(plan.plan_id, "cancelled", "user cancelled")
    assert store.load(plan.plan_id)["status"] == "cancelled"
    assert store.list_active("u", 1, session_id="s") == []


def add_authority(engine):
    from app.db.models.agent_business_action import AgentBusinessActionRecord
    from app.db.models.product_edit_claim import ProductEditClaimRecord

    with engine.begin() as db:
        db.execute(
            insert(AgentBusinessActionRecord.__table__),
            {
                "action_key": "key",
                "tenant_id": "7",
                "mod_id": "mod",
                "business_action_id": "original",
                "tool_id": "catalog_products_v1",
                "action": "append_price",
                "user_id": "1",
                "fingerprint": "fingerprint",
                "owner": "owner",
                "run_id": "run",
                "state": "unknown",
                "receipt_json": '{"retained":"original"}',
                "created_at": "now",
                "updated_at": "now",
            },
        )
        db.execute(
            insert(ProductEditClaimRecord.__table__),
            {
                "resource_key": "resource",
                "operation_key": "operation",
                "tenant_id": "7",
                "user_id": "1",
                "mod_id": "mod",
                "product_id": "1",
                "request_digest": "digest",
                "run_id": "run",
                "created_at": "now",
            },
        )
        for prefix in PREFIXES:
            db.execute(
                insert(WorkflowPlan.__table__),
                {
                    "plan_id": prefix + "original",
                    "user_id": "1",
                    "intent": "catalog_products_v1",
                    "plan_json": '{"retained":"original"}',
                    "runtime_context": "{}",
                    "status": "pending",
                },
            )


def evidence(path):
    with sqlite3.connect(path) as db:
        return {
            table: db.execute("SELECT * FROM " + table).fetchall()
            for table in ("agent_business_actions", "agent_product_edit_claims", "workflow_plans")
        }


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_unenrolled_real_restore_restores_business_but_retains_all_authority(
    tmp_path, monkeypatch, journal_mode
):
    from app.db.models.agent_business_action import AgentBusinessActionRecord
    from app.db.models.product_edit_claim import ProductEditClaimRecord
    from app.desktop_runtime import database_generation_registry as g
    from app.domain.shared_services.database_service import DatabaseService

    monkeypatch.setattr(g, "_owned_profile", None)
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE", raising=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "control"))
    path, backup = tmp_path / "host.sqlite", tmp_path / "backup.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA journal_mode=" + journal_mode).scalar() == journal_mode
    for model in (WorkflowPlan, AgentBusinessActionRecord, ProductEditClaimRecord):
        model.__table__.create(engine)
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE business_values(value TEXT)")
        db.exec_driver_sql("INSERT INTO business_values VALUES ('before')")
    service = DatabaseService()
    monkeypatch.setattr(service, "_get_db_path", lambda: str(path))
    assert service._hot_backup(str(path), str(backup))
    add_authority(engine)
    with engine.begin() as db:
        db.exec_driver_sql("UPDATE business_values SET value='after'")
    before = evidence(path)
    result = service.restore_database(str(backup))
    assert result["success"] is True
    assert evidence(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM business_values").fetchall() == [("before",)]
    engine.dispose()


@pytest.mark.parametrize("fault", ["enrolled", "missing-marker", "changed-root"])
def test_real_restore_refuses_enrolled_or_lost_authority_without_mutation(
    host, monkeypatch, tmp_path, fault
):
    from app.desktop_runtime import database_generation_registry as g
    from app.domain.shared_services.database_service import DatabaseService

    service = DatabaseService()
    path = Path(host.engine.url.database)
    backup = tmp_path / "older-host.sqlite"
    monkeypatch.setattr(service, "_get_db_path", lambda: str(path))
    assert service._hot_backup(str(path), str(backup))
    factory = enrolled(host)
    add_authority(host.engine)
    before, source_before = evidence(path), factory.target.read_bytes()
    root = g._owned_profile[0]
    if fault == "missing-marker":
        marker = root / "config" / "owned-source-protocol.json"
        marker.rename(marker.with_suffix(".preserved"))
    elif fault == "changed-root":
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "different-control"))
    # Simulate restart: durable anchor/marker, not in-memory readiness, must fence.
    monkeypatch.setattr(g, "_owned_profile", None)
    result = service.restore_database(str(backup))
    assert result["success"] is False
    assert evidence(path) == before
    assert factory.target.read_bytes() == source_before
    factory.engine.dispose()


def test_corrupt_catalog_authority_aborts_whole_run_cleanup(host):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository

    add_authority(host.engine)
    path = Path(host.engine.url.database)
    before = evidence(path)
    repository = SQLAlchemyAgentRunRepository(session_factory=host.actor.factory, auto_create=False)
    run = AgentRun(user_id=str(host.actor.user_id), message="ordinary synthetic run")
    repository.save(run)
    assert repository.get(run.run_id) is not None

    def entire_host():
        with sqlite3.connect(path) as db:
            tables = [
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ]
            return {
                name: db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall()
                for name in tables
            }

    # add_authority creates unsigned sentinel operations, orphan run/ledger IDs,
    # and a source-only receipt incorrectly in HOST. This is corrupt authority,
    # not a valid cancelled/paused operation; cleanup must abort atomically.
    whole_before = entire_host()
    with pytest.raises(ValueError, match="unexpected catalog receipt in host authority"):
        repository.clear()
    assert repository.get(run.run_id) is not None
    assert entire_host() == whole_before
    assert evidence(path) == before


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
@pytest.mark.parametrize(
    "fault",
    [
        "interval-writer",
        "staging-write",
        "backup-error",
        "active-reader",
        "active-writer",
        "mode-switch",
    ],
)
def test_actual_restore_lock_version_failure_and_release(
    tmp_path, monkeypatch, journal_mode, fault
):
    from contextlib import closing

    from app.db.models.agent_business_action import AgentBusinessActionRecord
    from app.db.models.product_edit_claim import ProductEditClaimRecord
    from app.desktop_runtime import database_generation_registry as g
    from app.domain.shared_services.database_service import DatabaseService

    monkeypatch.setattr(g, "_owned_profile", None)
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE", raising=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "control"))
    path, backup = tmp_path / "host.sqlite", tmp_path / "backup.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA journal_mode=" + journal_mode).scalar() == journal_mode
    for model in (WorkflowPlan, AgentBusinessActionRecord, ProductEditClaimRecord):
        model.__table__.create(engine)
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE business_values(value TEXT)")
        db.exec_driver_sql("INSERT INTO business_values VALUES ('snapshot')")
    service = DatabaseService()
    monkeypatch.setattr(service, "_get_db_path", lambda: str(path))
    assert service._hot_backup(str(path), str(backup))
    add_authority(engine)
    with engine.begin() as db:
        db.exec_driver_sql("UPDATE business_values SET value='live'")
    before = evidence(path)
    engine.dispose()  # no test-pool connection falsely supplies lock contention
    original_connect = sqlite3.connect
    events = []

    class ObservedConnection(sqlite3.Connection):
        """Real DBAPI with narrow contention/failure injection, no returned-data stubs."""

        exclusive = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if sql == "BEGIN EXCLUSIVE":
                self.exclusive = True
            return result

        def commit(self):
            super().commit()
            if self.exclusive and fault == "interval-writer":
                assert not self.in_transaction
                with closing(original_connect(path, timeout=0)) as external:
                    with pytest.raises(sqlite3.OperationalError, match="locked"):
                        external.execute("UPDATE business_values SET value='intruder'")
                events.append("writer-denied-before-copy")

        def backup(self, destination, **kwargs):
            if self.synthetic_path.endswith("staged.db") and (
                fault == "backup-error" or (fault == "interval-writer" and journal_mode == "wal")
            ):
                previous = kwargs.get("progress")

                def fail(status, remaining, total):
                    if previous:
                        previous(status, remaining, total)
                    if fault == "interval-writer":
                        if not events and status == sqlite3.SQLITE_OK:
                            with closing(original_connect(path, timeout=0)) as external:
                                with pytest.raises(sqlite3.OperationalError, match="locked"):
                                    external.execute("UPDATE business_values SET value='intruder'")
                            events.append("writer-denied-before-copy")
                    else:
                        events.append("native-page")
                        if len(events) == 2:
                            raise sqlite3.OperationalError("injected native backup failure")

                kwargs["progress"] = fail
            return super().backup(destination, **kwargs)

    def observed_connect(*args, **kwargs):
        connection = original_connect(*args, factory=ObservedConnection, **kwargs)
        connection.synthetic_path = str(args[0])
        return connection

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    changed_mode = []
    if fault in {"staging-write", "mode-switch"}:
        original_stage = service._stage_restore

        def concurrent_stage(source, current, staged):
            result = original_stage(source, current, staged)
            with closing(original_connect(path, timeout=0)) as external:
                if fault == "staging-write":
                    external.execute("UPDATE business_values SET value='concurrent'")
                    external.commit()
                else:
                    requested = "wal" if journal_mode == "delete" else "delete"
                    try:
                        observed = external.execute("PRAGMA journal_mode=" + requested).fetchone()[
                            0
                        ]
                    except sqlite3.OperationalError as exc:
                        assert "locked" in str(exc)
                        observed = journal_mode
                    changed_mode.append(observed)
            return result

        monkeypatch.setattr(service, "_stage_restore", concurrent_stage)
    reader = (
        original_connect(path, timeout=0) if fault in {"active-reader", "active-writer"} else None
    )
    try:
        if reader:
            reader.execute("BEGIN IMMEDIATE" if fault == "active-writer" else "BEGIN")
            reader.execute("SELECT * FROM business_values").fetchall()
        result = service.restore_database(str(backup))
    finally:
        if reader:
            reader.rollback()
            reader.close()
    succeeds = (
        fault == "interval-writer"
        or (fault == "active-reader" and journal_mode == "wal")
        or (fault == "mode-switch" and changed_mode == [journal_mode])
    )
    assert result["success"] is succeeds
    assert evidence(path) == before
    with closing(original_connect(path, timeout=0)) as db:
        expected = "snapshot" if succeeds else "concurrent" if fault == "staging-write" else "live"
        assert db.execute("SELECT value FROM business_values").fetchall() == [(expected,)]
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == (
            changed_mode[0] if changed_mode else journal_mode
        )
        db.execute("UPDATE business_values SET value='lock-released'")
        db.commit()
    if fault == "interval-writer":
        assert events == ["writer-denied-before-copy"]
    if fault == "backup-error":
        assert events == ["native-page", "native-page"]


@pytest.mark.parametrize("variant", ["canonical", "spaced-upper", "unicode"])
def test_actual_enrolled_knowledge_control_is_not_a_generic_workflow(host, variant):
    from app.application.dataset_rag.owned_store import _CONTROL
    from app.application.workflow.plan_store import OWNED_KNOWLEDGE_CONTROL_KEY

    factory = enrolled(host)
    assert _CONTROL == OWNED_KNOWLEDGE_CONTROL_KEY
    store = WorkflowPlanStore(factory.raw_sessions)
    before, json_before = raw_rows(factory.engine), factory.knowledge.path.read_bytes()
    key = _CONTROL
    if variant == "spaced-upper":
        key = "  " + key.upper() + "  "
    elif variant == "unicode":
        key = "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in key)
    with pytest.raises(ValueError):
        store.save(plan=PlanGraph(key, "ordinary"), user_id="host", require_commit=True)
    with pytest.raises(ValueError):
        store.update_status(key, "cancelled")
    assert store.load(key) is None and store.load_plan(key) is None
    assert store.list_active("host") == []
    assert raw_rows(factory.engine) == before
    assert factory.knowledge.path.read_bytes() == json_before
    with factory.guard():
        assert factory.knowledge.validate()["store_id"] == factory.binding["knowledge_store_id"]
    factory.engine.dispose()


def test_knowledge_exact_key_and_normalized_aliases_filtered_before_visible_limit(plans):
    from app.application.workflow.plan_store import OWNED_KNOWLEDGE_CONTROL_KEY

    store, engine = plans
    key = OWNED_KNOWLEDGE_CONTROL_KEY
    variants = [key, " " + key.upper() + " ", "".join(chr(ord(c) + 0xFEE0) for c in key)]
    with engine.begin() as db:
        for item in variants:
            db.execute(
                insert(WorkflowPlan.__table__),
                {
                    "plan_id": item,
                    "user_id": "host",
                    "intent": key,
                    "plan_json": "private opaque authority",
                    "status": "pending_awaiting",
                    "updated_at": datetime(2099, 1, 1),
                },
            )
    ordinary = key + "-ordinary"  # Exact real key, not an invented broad prefix.
    store.save(plan=PlanGraph(ordinary, "ordinary"), user_id="host", status="pending_awaiting")
    assert store.load_plan(ordinary).plan_id == ordinary
    assert [row["plan_id"] for row in store.list_active("host", limit=1)] == [ordinary]
