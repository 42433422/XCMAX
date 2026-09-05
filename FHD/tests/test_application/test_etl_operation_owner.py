"""ETL owner fencing on isolated SQLite and dedicated random PostgreSQL schemas."""

from __future__ import annotations

import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, update

from app.application.etl.errors import EtlError
from app.application.etl.operation_owner import (
    bind_owner,
    claim_operation,
    fail_operation,
    finish_operation,
    unbind_owner,
)
from app.application.etl.service import EtlService, mark_interrupted_runs_on_startup
from app.application.etl.targets import get_adapter
from app.db.etl_bootstrap import ensure_sqlite_etl_bootstrap
from app.db.models import Product
from app.db.models.etl import EtlRun, EtlRunRow
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_rollback_compare_swap import import_update
from tests.test_application.test_etl_rollback_compare_swap import store as store
from tests.test_application.test_etl_rollback_field_scope import persist_run


def make_run(store):
    _engine, factory, _ids = store
    receipt = import_update(store, "products", "price")
    with factory() as db:
        run, _rows = persist_run(db, "products", [receipt])
        return run.id


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_active_owner_blocks_other_connections_even_when_status_is_failed(store):
    _engine, factory, _ids = store
    run_id = make_run(store)
    with factory() as db:
        run = db.get(EtlRun, run_id)
        owner = claim_operation(db, run, "rollback", allowed_statuses={"completed"})
        run.status = "failed"
        db.commit()
    with factory() as db:
        with pytest.raises(EtlError) as error:
            claim_operation(db, db.get(EtlRun, run_id), "execute", allowed_statuses={"failed"})
        assert error.value.code == "ETL_RUN_BUSY"
        db.rollback()
    with factory() as db:
        assert db.get(EtlRun, run_id).operation_token == owner.token


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
@pytest.mark.parametrize("write_kind", ["orm", "core"])
def test_expired_worker_cannot_write_after_takeover_or_replace_new_owner_status(store, write_kind):
    _engine, factory, ids = store
    run_id = make_run(store)
    with factory() as first:
        owner = claim_operation(
            first, first.get(EtlRun, run_id), "rollback", allowed_statuses={"completed"}
        )
        first.commit()
        bind_owner(first, owner)
        product = first.get(Product, ids[1])
        with factory() as other:
            other.execute(
                update(EtlRun)
                .where(EtlRun.id == run_id)
                .values(operation_lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            other.commit()
            replacement = claim_operation(
                other, other.get(EtlRun, run_id), "rollback", allowed_statuses={"completed"}
            )
            other.commit()
        with pytest.raises(EtlError) as error:
            if write_kind == "orm":
                product.price = 999
                first.flush()
            else:
                first.execute(update(Product).where(Product.id == product.id).values(price=999))
        assert error.value.code == "ETL_OPERATION_LEASE_LOST"
        assert error.value.status_code == 409
        assert not fail_operation(
            first, owner, code="old_failure", message="must not replace owner"
        )
        unbind_owner(first)
    with factory() as db:
        assert db.get(Product, ids[1]).price == 20
        assert db.get(EtlRun, run_id).operation_token == replacement.token
        assert db.get(EtlRun, run_id).error_code is None


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_owner_finishes_business_write_and_releases_in_one_transaction(store):
    _engine, factory, ids = store
    run_id = make_run(store)
    with factory() as db:
        run = db.get(EtlRun, run_id)
        owner = claim_operation(db, run, "rollback", allowed_statuses={"completed"})
        bind_owner(db, owner)
        db.get(Product, ids[1]).price = 10
        run.rollback_status = "completed"
        finish_operation(db, owner)
        db.commit()
    with factory() as db:
        assert db.get(Product, ids[1]).price == 10
        assert db.get(EtlRun, run_id).operation_token is None
        assert db.get(EtlRun, run_id).rollback_status == "completed"


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_expired_external_batch_is_not_automatically_reclaimed(store):
    _engine, factory, _ids = store
    run_id = make_run(store)
    with factory() as db:
        owner = claim_operation(
            db, db.get(EtlRun, run_id), "batch_execute", allowed_statuses={"completed"}
        )
        db.commit()
        db.execute(
            update(EtlRun)
            .where(EtlRun.id == run_id)
            .values(operation_lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.commit()
    with factory() as db:
        with pytest.raises(EtlError) as error:
            claim_operation(db, db.get(EtlRun, run_id), "execute", allowed_statuses={"completed"})
        assert error.value.code == "ETL_RUN_BUSY"
        db.rollback()
        assert fail_operation(db, owner, code="unknown", message="unknown", outcome_unknown=True)
    with factory() as db:
        run = db.get(EtlRun, run_id)
        assert run.status == "outcome_unknown"
        assert run.error_code == "ETL_OUTCOME_UNKNOWN"
        assert run.operation_token == owner.token


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_startup_does_not_interrupt_another_process_with_a_live_owner(store):
    engine, factory, _ids = store
    run_id = make_run(store)
    with factory() as db:
        run = db.get(EtlRun, run_id)
        claim_operation(db, run, "execute", allowed_statuses={"completed"})
        run.status = "executing"
        db.commit()
    assert mark_interrupted_runs_on_startup(engine) == 0
    with factory() as db:
        assert db.get(EtlRun, run_id).status == "executing"


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_second_rollback_never_runs_adapter_or_overwrites_the_first_result(store, monkeypatch):
    _engine, factory, ids = store
    run_id = make_run(store)
    entered, release = threading.Event(), threading.Event()
    adapter = get_adapter("products")
    calls = []

    def rollback_row(db, **kwargs):
        calls.append(threading.current_thread().name)
        if threading.current_thread().name.startswith("primary-rollback"):
            entered.set()
            assert release.wait(5)
        return adapter.rollback_row(db, **kwargs)

    monkeypatch.setattr(
        "app.application.etl.service_execution.get_adapter",
        lambda _target: SimpleNamespace(rollback_row=rollback_row),
    )

    def primary():
        with tenant_scope(1), factory() as db:
            EtlService(adviser=MagicMock()).rollback(db, run_id=run_id, owner_user_id=1)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="primary-rollback") as executor:
        primary_result = executor.submit(primary)
        try:
            assert entered.wait(5)
            with factory() as db, pytest.raises(EtlError) as error:
                EtlService(adviser=MagicMock()).rollback(db, run_id=run_id, owner_user_id=1)
            assert error.value.code == "ETL_RUN_BUSY"
        finally:
            release.set()
            primary_result.result(timeout=6)
    assert len(calls) == 1 and calls[0].startswith("primary-rollback")
    with factory() as db:
        assert db.get(EtlRun, run_id).rollback_status == "completed"
        assert db.get(Product, ids[1]).price == 10


def _migration():
    path = Path(__file__).parents[2] / "alembic/versions/2026_09_05_etl_operation_lease.py"
    spec = importlib.util.spec_from_file_location("etl_operation_lease_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_real_migration_is_idempotent_and_preserves_existing_rows(store):
    engine, factory, _ids = store
    run_id = make_run(store)
    migration = _migration()
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        migration.upgrade()
        migration.upgrade()
    with factory() as db:
        assert db.get(EtlRun, run_id).status == "completed"
        assert db.get(EtlRun, run_id).operation_token is None


def test_packaged_sqlite_bootstrap_upgrades_old_columns_without_recreating_rows(store):
    engine, factory, _ids = store
    run_id = make_run(store)
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        _migration().downgrade()
    ensure_sqlite_etl_bootstrap(engine, swallow_errors=False)
    ensure_sqlite_etl_bootstrap(engine, swallow_errors=False)
    assert {"operation_kind", "operation_token", "operation_lease_until"} <= {
        column["name"] for column in inspect(engine).get_columns("etl_runs")
    }
    with factory() as db:
        assert db.get(EtlRun, run_id).status == "completed"


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
@pytest.mark.parametrize(
    "action,status", [("execute", "preview_ready"), ("retry", "failed"), ("draft", "preview_ready")]
)
def test_active_rollback_owner_blocks_forward_entry_points(store, action, status):
    _engine, factory, _ids = store
    run_id = make_run(store)
    with factory() as db:
        run = db.get(EtlRun, run_id)
        owner = claim_operation(db, run, "rollback", allowed_statuses={"completed"})
        run.status = status
        db.commit()
    service = EtlService(adviser=MagicMock())
    service._owned_upload = service._owned_upload_record
    with factory() as db, pytest.raises(EtlError) as error:
        if action == "execute":
            service.execute(
                db, run_id=run_id, owner_user_id=1, confirmed=True, valid_rows_only=False
            )
        elif action == "retry":
            service.retry(db, run_id=run_id, owner_user_id=1)
        else:
            service.update_draft(db, run_id=run_id, owner_user_id=1, patch={"field_mappings": []})
    assert error.value.code == "ETL_RUN_BUSY"
    with factory() as db:
        assert db.get(EtlRun, run_id).operation_token == owner.token
        assert db.get(EtlRun, run_id).status == status


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_duplicate_batch_dispatch_token_activates_only_one_worker(store, monkeypatch):
    _engine, factory, _ids = store
    run_id = make_run(store)
    with factory() as db:
        run = db.get(EtlRun, run_id)
        owner = claim_operation(db, run, "execute_queue", allowed_statuses={"completed"})
        run.status = "executing"
        db.commit()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def execute_batch(rows, _context):
        list(rows)
        calls.append(threading.current_thread().name)
        if threading.current_thread().name == "primary-batch":
            entered.set()
            assert release.wait(5)
        return {"executed": 0, "receipt": {"test": True}}

    monkeypatch.setattr(
        "app.application.etl.service_execution.get_adapter",
        lambda _target: SimpleNamespace(execute_batch=execute_batch),
    )
    monkeypatch.setattr("app.application.etl.service_execution.new_session", factory)
    service = EtlService(adviser=MagicMock())
    service._owned_upload = service._owned_upload_record

    def primary():
        with tenant_scope(1):
            service._execute_worker(run_id, 1, False, operation_token=owner.token)

    thread = threading.Thread(target=primary, name="primary-batch", daemon=True)
    thread.start()
    try:
        assert entered.wait(5)
        service._execute_worker(run_id, 1, False, operation_token=owner.token)
        assert calls == ["primary-batch"]
    finally:
        release.set()
        thread.join(6)
    assert not thread.is_alive()
    with factory() as db:
        assert db.get(EtlRun, run_id).status == "completed"
        assert db.get(EtlRun, run_id).operation_token is None


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
@pytest.mark.parametrize("last_row_committed", [False, True])
def test_crashed_rollback_resumes_only_remaining_rows_in_reverse_order(store, last_row_committed):
    _engine, factory, ids = store
    first = import_update(store, "products", "price")
    receipts = [first]
    adapter = get_adapter("products")
    if not last_row_committed:
        with factory() as db:
            data = {
                "unit": "并发回滚客户",
                "name": "并发回滚产品",
                "model_number": "CAS-1",
                "price": "30",
            }
            preview = adapter.preview(db, data, allowed_update_fields={"price"}, context={})
            result = adapter.execute_row(
                db,
                data,
                action="update",
                match_ref=preview.match_ref,
                allowed_update_fields={"price"},
                context={},
            )
            receipts.append(
                {
                    "match_ref": result["match_ref"],
                    "before": preview.before,
                    "after": result["after"],
                }
            )
            db.commit()
    with factory() as db:
        run, rows = persist_run(db, "products", receipts)
        run_id = run.id
        owner = claim_operation(db, run, "rollback", allowed_statuses={"completed"})
        bind_owner(db, owner)
        run.rollback_status = "running"
        adapter.rollback_row(db, **receipts[-1], context={})
        rows[-1].execution_status = "rolled_back"
        db.commit()
        unbind_owner(db)
    with factory() as db:
        db.execute(
            update(EtlRun)
            .where(EtlRun.id == run_id)
            .values(operation_lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.get(Product, ids[1]).description = "崩溃后人工备注"
        db.commit()
    with factory() as db:
        result = EtlService(adviser=MagicMock()).rollback(db, run_id=run_id, owner_user_id=1)
        assert result["rollback_status"] == "completed"
    with factory() as db:
        assert db.get(Product, ids[1]).price == 10
        assert db.get(Product, ids[1]).description == "崩溃后人工备注"
        assert {row.execution_status for row in db.query(EtlRunRow).all()} == {"rolled_back"}
        assert db.get(EtlRun, run_id).operation_token is None
