"""B57: upload, clean, confirm, submit and failure each leave a complete audit row."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.application.elt.audit import note_interrupted, record_elt_audit
from app.application.elt.operation_owner import OperationOwner, fail_operation
from app.db.db_base import Base
from app.db.models.elt import EltRun, EltUpload
from app.infrastructure.tenant_scope import tenant_scope

REQUIRED = ("actor_user_id", "occurred_at", "operation", "outcome", "run_id", "error_code")


def _store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _run(db) -> EltRun:
    upload = EltUpload(
        id="upload-1",
        tenant_id=1,
        owner_user_id=7,
        file_name="入库.csv",
        suffix=".csv",
        size_bytes=12,
        sha256="a" * 64,
        storage_path="/tmp/入库.csv",
    )
    run = EltRun(
        id="run-1",
        tenant_id=1,
        owner_user_id=7,
        upload_id=upload.id,
        target_type="products",
        status="executing",
        stage="executing",
        file_sha256=upload.sha256,
        executed_rows=1,
        operation_kind="execute",
        operation_token="token-1",
        operation_lease_until=datetime.now(UTC) + timedelta(minutes=5),
    )
    db.add(upload)
    db.flush()
    db.add(run)
    db.commit()
    return run


def test_partial_failure_keeps_submit_time_and_exception_audit(tmp_path):
    factory = _store(tmp_path)
    with tenant_scope(1), factory() as db:
        run = _run(db)
        record_elt_audit(
            db,
            actor=7,
            action="elt_submit",
            payload={
                "run_id": run.id,
                "upload_id": run.upload_id,
                "outcome": "partial",
                "executed_rows": 1,
                "error_code": "ELT_MATCH_CHANGED",
            },
        )
        db.commit()
        assert fail_operation(
            db,
            OperationOwner(run.id, 7, 1, "execute", "token-1"),
            code="ELT_MATCH_CHANGED",
            message="产品在预演后已存在",
        )
        saved = db.get(EltRun, run.id)
        assert saved is not None
        assert saved.status == "failed"
        assert saved.executed_at is not None
        rows = db.execute(
            text("SELECT actor, action, created_at, payload FROM ai_action_audit ORDER BY id")
        ).all()
    actions = [row.action for row in rows]
    assert actions == ["elt_submit", "elt_exception"]
    for row in rows:
        body = json.loads(row.payload)
        assert row.actor == "7" and row.created_at
        assert body["actor_user_id"] == 7 and body["occurred_at"] and body["run_id"] == "run-1"
        assert body["outcome"] in {"partial", "failed"}
    failure = json.loads(rows[1].payload)
    assert failure["error_code"] == "ELT_MATCH_CHANGED"
    assert failure["executed_rows"] == 1
    assert failure["executed_at"]


def test_interrupted_partial_run_is_audited_without_looking_successful(tmp_path):
    factory = _store(tmp_path)
    with tenant_scope(1), factory() as db:
        run = _run(db)
        note_interrupted(db, run)
        db.commit()
        saved = db.get(EltRun, run.id)
        assert saved.status == "interrupted"
        assert saved.executed_at is not None
        body = json.loads(
            db.execute(text("SELECT payload FROM ai_action_audit")).scalar()
        )
    assert body["outcome"] == "interrupted"
    assert all(body.get(key) not in (None, "") for key in REQUIRED)
    assert body["executed_rows"] == 1
