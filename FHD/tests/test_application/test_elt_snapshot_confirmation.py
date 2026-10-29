"""Snapshot replay keeps exact preview approval after temporary originals disappear."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.application.etl.errors import EtlError
from app.application.etl.service_support import dump_json, load_json
from app.db.models.etl import EtlRun, EtlUpload
from tests.test_application.test_etl_preview_confirmation import assert_unwritten, execute
from tests.test_application.test_etl_preview_task_boundaries import preview_store as preview_store
from tests.test_application.test_etl_preview_task_boundaries import ready_preview, snapshot


def expire_original(store, run_id, *, cleared=False):
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        upload = db.get(EtlUpload, run.upload_id)
        Path(upload.storage_path).unlink()
        upload.expires_at = datetime.now(UTC) - timedelta(days=1)
        if cleared:
            upload.storage_path = ""
        db.commit()


@pytest.mark.parametrize("cleared", [False, True])
def test_reviewed_snapshot_executes_after_original_cleanup(preview_store, monkeypatch, cleared):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    expire_original(store, run_id, cleared=cleared)
    with pytest.raises(EtlError) as error:
        execute(store, run_id, None)
    assert error.value.code == "ETL_PREVIEW_CONFIRMATION_REQUIRED"
    assert_unwritten(store, run_id)
    execute(store, run_id, reviewed)
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, run_id)["summary"]["executed"] == 2


@pytest.mark.parametrize("proof", ["expiry", "headers", "missing", "digest", "expired"])
def test_changed_snapshot_proof_never_reuses_old_approval(preview_store, monkeypatch, proof):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    expire_original(store, run_id)
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        details = load_json(run.summary_json, {})
        manifest = details["source_snapshot"]
        if proof == "expiry":
            manifest["expires_at"] = (
                datetime.fromisoformat(manifest["expires_at"]) - timedelta(hours=1)
            ).isoformat()
        elif proof == "headers":
            manifest["headers"] = ["changed header"]
        elif proof == "missing":
            details.pop("source_snapshot")
        elif proof == "digest":
            manifest["sha256"] = "0" * 64
        else:
            manifest["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        run.summary_json = dump_json(details)
        db.commit()
    with pytest.raises(EtlError):
        execute(store, run_id, reviewed)
    assert_unwritten(store, run_id)


def test_worker_rechecks_snapshot_proof_after_approval(preview_store, monkeypatch):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    expire_original(store, run_id)
    queued = Mock()
    monkeypatch.setattr(store.service, "_submit_execution", queued)
    execute(store, run_id, reviewed)
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        details = load_json(run.summary_json, {})
        details["source_snapshot"]["headers"] = ["changed while queued"]
        run.summary_json = dump_json(details)
        db.commit()
    store.service._execute_worker(run_id, 7, False, **queued.call_args.kwargs)
    assert assert_unwritten(store, run_id, status="failed")["error_code"] == "ETL_PREVIEW_CHANGED"


def test_unreadable_original_is_not_treated_as_deleted(preview_store, monkeypatch):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    original_open = Path.open
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        location = db.get(EtlUpload, run.upload_id).storage_path

    def deny(path, *args, **kwargs):
        if str(path) == location:
            raise PermissionError("synthetic denied original")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(EtlError) as error:
        execute(store, run_id, reviewed)
    assert error.value.code == "ETL_PREVIEW_CHANGED"
    assert_unwritten(store, run_id)


def test_replay_from_expired_original_requires_its_own_reviewed_revision(
    preview_store, monkeypatch
):
    store = preview_store
    source_id = ready_preview(store, monkeypatch)
    source_revision = snapshot(store, source_id)["preview_revision"]
    expire_original(store, source_id, cleared=True)
    with store.factory() as db:
        replay = store.service.replay(db, run_id=source_id, owner_user_id=7)
    store.executor.futures[-1].result(timeout=10)
    replayed = snapshot(store, replay["id"])
    assert replayed["status"] == "preview_ready"
    assert replayed["preview_revision"] != source_revision
    with pytest.raises(EtlError) as error:
        execute(store, replay["id"], source_revision)
    assert error.value.code == "ETL_PREVIEW_CHANGED"
    assert_unwritten(store, replay["id"])
    execute(store, replay["id"], replayed["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, replay["id"])["summary"]["executed"] == 2
