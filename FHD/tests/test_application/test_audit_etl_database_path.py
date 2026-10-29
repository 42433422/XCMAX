"""Actual ETL parser/snapshot/SQL/export and lease tests on isolated SQLite.

These do not exercise HTTP authentication, PostgreSQL or an installed desktop.
Only the data directory is configured; product functions and SQL are not mocked.
"""

import csv
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.etl.errors import EtlConflict
from app.application.etl.operation_owner import (
    bind_owner,
    claim_operation,
    recover_stale_owner,
)
from app.application.etl.parsers import parse_file
from app.application.etl.service_source import SourceServiceMixin
from app.application.etl.service_support import dump_json, load_json
from app.application.etl.targets import get_adapter
from app.application.etl.transforms import apply_mapping
from app.db.models.etl import EtlRun, EtlRunRow, EtlTemplate, EtlTemplateVersion, EtlUpload
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "private-data"))
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.sqlite'}", connect_args={"timeout": 10})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for model in (EtlUpload, EtlTemplate, EtlTemplateVersion, EtlRun, EtlRunRow):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def seed_snapshot(factory, tmp_path):
    path = tmp_path / "input.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["code", "zero", "flag", "note"])
        writer.writerow(["SKU", "0", "false", "中文"])
        writer.writerow(["ITEM", "0", "false", "=1+1"])
    dataset = parse_file(path, target_type="export_csv")
    assert len(dataset.rows) == 2
    upload_id, run_id = str(uuid4()), str(uuid4())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with tenant_scope(101), factory() as db:
        db.add(EtlUpload(id=upload_id, tenant_id=101, owner_user_id=201,
                         file_name=path.name, suffix=".csv", size_bytes=path.stat().st_size,
                         sha256=digest, storage_path=str(path)))
        db.commit()
        run = EtlRun(id=run_id, tenant_id=101, owner_user_id=201, upload_id=upload_id,
                     target_type="export_csv", status="preview_ready", file_sha256=digest,
                     draft_json="{}", summary_json="{}")
        db.add(run)
        db.commit()
        SourceServiceMixin()._persist_source_snapshot(db, run, dataset)
    return run_id


def test_csv_snapshot_mapping_database_and_real_export(database, tmp_path):
    run_id = seed_snapshot(database, tmp_path)
    mappings = [
        {"source": "zero", "target": "zero", "transforms": [{"op": "cast", "type": "int"}]},
        {"source": "flag", "target": "flag", "transforms": [{"op": "cast", "type": "bool"}]},
        {"source": "zero", "target": "split_zero", "transforms": [
            {"op": "cast", "type": "int"}, {"op": "split"}]},
        {"target": "label", "transforms": [
            {"op": "concat", "fields": ["code", "zero", "flag"], "separator": "/"}]},
        {"source": "note", "target": "note"},
    ]
    with tenant_scope(101), database() as db:
        run = db.get(EtlRun, run_id)
        restored = SourceServiceMixin()._load_source_snapshot(db, run)
        assert restored is not None
        rows = db.query(EtlRunRow).filter_by(run_id=run_id).order_by(EtlRunRow.id).all()
        for row, source in zip(rows, restored.rows, strict=True):
            row.normalized_json = dump_json(apply_mapping(source.values, mappings))
        db.commit()
    with tenant_scope(101), database() as db:
        stored = [load_json(row.normalized_json, {}) for row in
                  db.query(EtlRunRow).filter_by(run_id=run_id).order_by(EtlRunRow.id)]
        assert [row["zero"] for row in stored] == [0, 0]
        assert all(row["flag"] is False and row["split_zero"] == "0" for row in stored)
        result = get_adapter("export_csv").execute_batch(stored, {"run_id": run_id, "row_count": 2})
    assert result["executed"] == 2
    output = tmp_path / "private-data/etl/exports" / result["receipt"]["file_name"]
    with output.open(encoding="utf-8-sig", newline="") as stream:
        exported = list(csv.DictReader(stream))
    assert [row["label"] for row in exported] == ["SKU/0/False", "ITEM/0/False"]
    assert [row["note"] for row in exported] == ["中文", "'=1+1"]


def test_snapshot_rejects_other_tenant(database, tmp_path):
    run_id = seed_snapshot(database, tmp_path)
    with tenant_scope(101), database() as db:
        run = db.get(EtlRun, run_id)
    with tenant_scope(102), database() as db, pytest.raises(EtlConflict):
        SourceServiceMixin()._load_source_snapshot(db, run)


@pytest.mark.parametrize("tamper", ["owner", "payload", "expiry"])
def test_snapshot_integrity_and_ownership_survive_reopen(database, tmp_path, tamper):
    run_id = seed_snapshot(database, tmp_path)
    with tenant_scope(101), database() as db:
        run = db.get(EtlRun, run_id)
        row = db.query(EtlRunRow).filter_by(run_id=run_id).first()
        if tamper == "owner":
            row.owner_user_id = 999
        elif tamper == "payload":
            row.source_json = '{"zero": 99}'
        else:
            summary = load_json(run.summary_json, {})
            summary["source_snapshot"]["expires_at"] = "2000-01-01T00:00:00+00:00"
            run.summary_json = dump_json(summary)
        db.commit()
    with tenant_scope(101), database() as db, pytest.raises(EtlConflict):
        SourceServiceMixin()._load_source_snapshot(db, db.get(EtlRun, run_id))


def test_two_real_database_sessions_only_one_claims_execution(database, tmp_path):
    run_id = seed_snapshot(database, tmp_path)
    barrier = Barrier(2)

    def claim():
        with tenant_scope(101), database() as db:
            run = db.get(EtlRun, run_id)
            barrier.wait(timeout=10)
            try:
                owner = claim_operation(db, run, "execute", allowed_statuses={"preview_ready"})
                db.commit()
                return "claimed", owner.token
            except EtlConflict as exc:
                db.rollback()
                return "rejected", exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(state for state, _ in results) == ["claimed", "rejected"]
    assert next(detail for state, detail in results if state == "rejected") == "ETL_RUN_BUSY"


@pytest.mark.parametrize("kind", ["execute", "batch_execute"])
def test_expired_owners_cannot_repeat_or_overwrite_work(database, tmp_path, kind):
    run_id = seed_snapshot(database, tmp_path)
    with tenant_scope(101), database() as db:
        run = db.get(EtlRun, run_id)
        owner = claim_operation(db, run, kind, allowed_statuses={"preview_ready"})
        db.commit()
        db.refresh(run)
        run.operation_lease_until = datetime(2000, 1, 1)
        db.commit()
        assert recover_stale_owner(db, run) is True
        if kind == "batch_execute":
            assert run.status == "outcome_unknown"
            assert run.operation_token == owner.token
            with pytest.raises(EtlConflict):
                claim_operation(db, run, "execute", allowed_statuses={"outcome_unknown"})
            db.rollback()
        else:
            assert run.status == "interrupted" and run.operation_token is None
            replacement = claim_operation(db, run, "execute", allowed_statuses={"interrupted"})
            db.commit()
            assert replacement.token != owner.token
    with tenant_scope(101), database() as db:
        run = db.get(EtlRun, run_id)
        bind_owner(db, owner)
        run.executed_rows = 999
        with pytest.raises(EtlConflict):
            db.commit()
        db.rollback()
    with tenant_scope(101), database() as db:
        assert db.get(EtlRun, run_id).executed_rows == 0
