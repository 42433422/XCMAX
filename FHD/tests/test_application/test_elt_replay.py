"""Replays start a fresh preview, preserving source evidence and tenant ownership."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.elt import service_preview
from app.application.elt.adviser import EltRowAdviser
from app.application.elt.errors import EltError
from app.application.elt.parser_types import ParsedDataset, ParsedRow
from app.application.elt.service import EltService
from app.application.elt.service_support import dump_json, load_json
from app.db.db_base import Base
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.db.models.purchase_unit import PurchaseUnit
from app.fastapi_routes import elt as api
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def replay_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    service = EltService(adviser=EltRowAdviser())
    monkeypatch.setattr(service_preview, "new_session", factory)
    monkeypatch.setattr(
        service,
        "_submit_preview",
        lambda run_id, _tenant, owner: service._preview_worker(run_id, owner),
    )
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    with tenant_scope(1), factory() as db:
        upload = EltUpload(
            id="original-upload",
            tenant_id=1,
            owner_user_id=7,
            file_name="replay.csv",
            suffix=".csv",
            size_bytes=1,
            sha256="a" * 64,
            storage_path=str(tmp_path / "removed-original.csv"),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        source = EltRun(
            id="source",
            tenant_id=1,
            owner_user_id=7,
            upload_id=upload.id,
            target_type="customers",
            status="completed",
            stage="completed",
            file_sha256=upload.sha256,
            executed_rows=1,
            receipt_json=dump_json({"executed": 1}),
            confirmed_at=datetime.now(UTC),
            draft_json=dump_json(
                {
                    "field_mappings": [
                        {"source": "客户", "target": "customer_name", "transforms": []}
                    ],
                    "validation_rules": [],
                    "match_keys": ["customer_name"],
                    "allowed_update_fields": [],
                    "action_rules": {"duplicate": "skip"},
                    "ocr_confirmed": True,
                }
            ),
        )
        db.add(upload)
        db.flush()
        db.add(source)
        db.flush()
        service._persist_source_snapshot(
            db,
            source,
            ParsedDataset(
                headers=["客户"],
                rows=[ParsedRow("sheet", 2, {"客户": "重放客户"})],
                source_features={"kind": "table"},
            ),
        )
        source_row = db.query(EltRunRow).filter(EltRunRow.run_id == source.id).one()
        source_row.normalized_json = dump_json({"customer_name": "旧转换结果"})
        source_row.execution_status = "success"
        source_row.after_json = dump_json({"id": 123})
        db.commit()
        yield SimpleNamespace(db=db, service=service, factory=factory, source=source)
    engine.dispose()


def test_replay_retransforms_without_original_and_requires_fresh_confirmation(replay_store):
    store = replay_store
    result = store.service.replay(store.db, run_id="source", owner_user_id=7)
    assert result["id"] != "source" and result["status"] == "preview_ready"
    assert result["details"]["replay_of"] == "source"
    assert result["details"]["source_run_id"] == "source"
    assert result["receipt"] == {} and result["summary"]["executed"] == 0
    assert result["draft"]["ocr_confirmed"] is False
    run = store.db.get(EltRun, result["id"])
    assert run.confirmed_at is None and run.executed_at is None
    row = store.db.query(EltRunRow).filter(EltRunRow.run_id == run.id).one()
    assert load_json(row.normalized_json, {}) == {"customer_name": "重放客户"}
    assert row.execution_status is None and load_json(row.after_json, {}) != {"id": 123}
    assert store.db.query(PurchaseUnit).count() == 0
    original = store.db.query(EltRunRow).filter(EltRunRow.run_id == "source").one()
    assert original.execution_status == "success"
    assert load_json(original.normalized_json, {}) == {"customer_name": "旧转换结果"}
    with pytest.raises(EltError, match="显式确认"):
        store.service.execute(
            store.db, run_id=run.id, owner_user_id=7, confirmed=False, valid_rows_only=False
        )


@pytest.mark.parametrize("damage", ["row", "missing_row", "expired", "legacy"])
def test_replay_rejects_unavailable_or_changed_evidence(replay_store, damage):
    store = replay_store
    row = store.db.query(EltRunRow).filter(EltRunRow.run_id == "source").one()
    if damage == "row":
        row.source_json = dump_json({"客户": "被篡改客户"})
    elif damage == "missing_row":
        store.db.delete(row)
    elif damage == "expired":
        store.source.created_at = datetime.now(UTC) - timedelta(days=91)
    else:
        store.source.summary_json = "{}"
    store.db.commit()
    with pytest.raises(EltError) as error:
        store.service.replay(store.db, run_id="source", owner_user_id=7)
    assert error.value.code in {"ELT_SOURCE_SNAPSHOT_INVALID", "ELT_SOURCE_SNAPSHOT_REQUIRED"}
    assert store.db.query(EltRun).count() == 1


@pytest.mark.parametrize("owner,tenant", [(8, 1), (7, 2)])
def test_replay_cannot_read_another_owners_or_tenants_source(replay_store, owner, tenant):
    with tenant_scope(tenant), pytest.raises(EltError) as error:
        replay_store.service.replay(replay_store.db, run_id="source", owner_user_id=owner)
    assert error.value.code == "ELT_NOT_FOUND"


def test_read_only_companion_cannot_be_promoted_by_replay(replay_store):
    store = replay_store
    draft = load_json(store.source.draft_json, {})
    draft["linked_preview"] = {"read_only": True, "parent_run_id": "parent"}
    store.source.draft_json = dump_json(draft)
    store.db.commit()
    with pytest.raises(EltError) as error:
        store.service.replay(store.db, run_id="source", owner_user_id=7)
    assert error.value.code == "ELT_REPLAY_PREVIEW_ONLY"
    assert store.db.query(EltRun).count() == 1


@pytest.mark.parametrize("target", ["knowledge", "attendance"])
def test_original_dependent_targets_cannot_replay_a_missing_original(replay_store, target):
    store = replay_store
    dataset = store.service._load_source_snapshot(store.db, store.source)
    store.source.summary_json = "{}"
    store.source.target_type = target
    store.db.query(EltRunRow).filter(EltRunRow.run_id == "source").delete(
        synchronize_session="fetch"
    )
    store.service._persist_source_snapshot(store.db, store.source, dataset)
    with pytest.raises(EltError) as error:
        store.service.replay(store.db, run_id="source", owner_user_id=7)
    assert error.value.code == "ELT_UPLOAD_EXPIRED"
    assert store.db.query(EltRun).count() == 1


def test_repeated_replay_preserves_original_lineage(replay_store):
    store = replay_store
    first = store.service.replay(store.db, run_id="source", owner_user_id=7)
    second = store.service.replay(store.db, run_id=first["id"], owner_user_id=7)
    assert second["details"]["replay_of"] == first["id"]
    assert second["details"]["source_run_id"] == "source"
    assert second["summary"]["executed"] == 0
    assert store.db.query(PurchaseUnit).count() == 0


def test_replay_submission_failure_keeps_retryable_source_snapshot(replay_store, monkeypatch):
    store = replay_store
    monkeypatch.setattr(
        store.service, "_submit_preview", Mock(side_effect=RuntimeError("queue closed"))
    )
    with pytest.raises(RuntimeError, match="queue closed"):
        store.service.replay(store.db, run_id="source", owner_user_id=7)
    run = store.db.query(EltRun).filter(EltRun.id != "source").one()
    assert run.status == "failed" and run.error_code == "ELT_INTERNAL_ERROR"
    assert store.service._load_source_snapshot(store.db, run).rows[0].values == {"客户": "重放客户"}
    assert store.source.status == "completed"


def test_replay_route_uses_execute_permission_and_returns_accepted(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    replay = Mock(return_value={"id": "new-run", "status": "queued"})
    monkeypatch.setattr(api, "get_elt_service", lambda: SimpleNamespace(replay=replay))
    app.dependency_overrides[api._feature_gate] = lambda: None
    app.dependency_overrides[api._execute] = lambda: SimpleNamespace(id=7)
    app.dependency_overrides[api.get_db_dependency] = lambda: "owned-db"
    client = TestClient(app)
    response = client.post("/api/elt/runs/source/replay")
    assert response.status_code == 202 and response.json()["data"]["id"] == "new-run"
    replay.assert_called_once_with("owned-db", run_id="source", owner_user_id=7)

    def denied():
        raise HTTPException(status_code=403, detail="etl.execute required")

    app.dependency_overrides[api._execute] = denied
    replay.reset_mock()
    assert client.post("/api/elt/runs/source/replay").status_code == 403
    replay.assert_not_called()


def test_replay_chain_cannot_extend_original_snapshot_retention(replay_store, monkeypatch):
    from app.application.elt import service_source

    store = replay_store
    original_time = datetime.now(UTC) - timedelta(days=89)
    store.source.created_at = original_time
    summary = load_json(store.source.summary_json, {})
    expiry = (original_time + timedelta(days=90)).isoformat()
    summary["source_snapshot"]["expires_at"] = expiry
    store.source.summary_json = dump_json(summary)
    store.db.commit()
    first = store.service.replay(store.db, run_id="source", owner_user_id=7)
    second = store.service.replay(store.db, run_id=first["id"], owner_user_id=7)
    assert first["details"]["source_snapshot"]["expires_at"] == expiry
    assert second["details"]["source_snapshot"]["expires_at"] == expiry
    monkeypatch.setattr(service_source, "utcnow", lambda: datetime.now(UTC) + timedelta(days=2))
    before = store.db.query(EltRun).count()
    for run_id in ("source", first["id"], second["id"]):
        with pytest.raises(EltError) as error:
            store.service.replay(store.db, run_id=run_id, owner_user_id=7)
        assert error.value.code == "ELT_SOURCE_SNAPSHOT_INVALID"
    assert store.db.query(EltRun).count() == before
    assert store.db.query(PurchaseUnit).count() == 0


@pytest.mark.parametrize(
    "expiry", [None, "not-a-time", "2030-01-01T00:00:00", "2100-01-01T00:00:00+00:00"]
)
def test_replay_rejects_missing_or_invalid_retention_proof(replay_store, expiry):
    store = replay_store
    summary = load_json(store.source.summary_json, {})
    summary["source_snapshot"]["expires_at"] = expiry
    store.source.summary_json = dump_json(summary)
    store.db.commit()
    with pytest.raises(EltError) as error:
        store.service.replay(store.db, run_id="source", owner_user_id=7)
    assert error.value.code == "ELT_SOURCE_SNAPSHOT_INVALID"
    assert store.db.query(EltRun).count() == 1


@pytest.mark.parametrize("blocked", ["active_owner", "outcome_unknown"])
def test_replay_does_not_reissue_active_or_uncertain_writes(replay_store, blocked):
    store = replay_store
    if blocked == "active_owner":
        store.source.operation_token = "active-worker"
    else:
        store.source.status = "outcome_unknown"
    store.db.commit()
    with pytest.raises(EltError) as error:
        store.service.replay(store.db, run_id="source", owner_user_id=7)
    assert error.value.code == "ELT_RUN_BUSY"
    assert store.db.query(EltRun).count() == 1
    assert store.db.query(PurchaseUnit).count() == 0
