"""Interrupted approval dispatch never silently replays a business write."""

from unittest.mock import Mock

import pytest

from app.application.elt import auto_ingest_service as ais
from app.application.elt.errors import EltError


@pytest.fixture
def batch(monkeypatch, tmp_path):
    monkeypatch.setattr(ais, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "test-mod")
    row = {
        "batch_id": "batch",
        "tenant_id": 1,
        "owner_user_id": 7,
        "mod_id": "test-mod",
        "status": "awaiting_approval",
        "business": {},
        "knowledge": {},
    }
    ais._save_ledger(1, {"batches": {"batch": row}})
    return row


def test_start_failure_is_not_running_and_cannot_replay(batch, monkeypatch):
    service = ais.AutoIngestService()
    monkeypatch.setattr(
        ais.threading.Thread, "start", Mock(side_effect=RuntimeError("start failed"))
    )
    with pytest.raises(RuntimeError, match="start failed"):
        service.release_approved_batch(batch_id="batch", tenant_id=1)
    saved = service.get_batch(tenant_id=1, batch_id="batch", owner_user_id=7)
    assert saved["status"] == "failed"
    assert saved["error"] == "ELT_WORKER_NOT_STARTED"
    with pytest.raises(EltError):
        service.release_approved_batch(batch_id="batch", tenant_id=1)


def test_dead_worker_without_business_receipt_becomes_unknown(batch, monkeypatch):
    batch.update(
        status="running", worker_protocol=1, knowledge={"action": "new", "match_ref": "kept"}
    )
    ais._save_ledger(1, {"batches": {"batch": batch}})
    service = ais.AutoIngestService()
    launch = Mock(side_effect=AssertionError("must not replay"))
    monkeypatch.setattr(service, "_launch_worker", launch)
    receipt = service.get_batch(tenant_id=1, batch_id="batch", owner_user_id=7)
    assert receipt["status"] == "failed"
    assert receipt["business_progress"]["stage"] == "outcome_unknown"
    assert receipt["knowledge"] == batch["knowledge"]
    with pytest.raises(EltError):
        service.release_approved_batch(batch_id="batch", tenant_id=1)
    from app.fastapi_routes.domains.misc.helpers import _dispatch_tool_for_approval
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setattr(ais, "get_auto_ingest_service", lambda: service)
    with tenant_scope(1):
        retry = _dispatch_tool_for_approval(
            tool_id="data_docking", action="auto_ingest", params={"batch_id": "batch"}
        )
    assert retry["success"] is False
    assert retry["error"] == "ETL_AUTO_INGEST_NOT_PENDING"
    launch.assert_not_called()


def test_active_worker_and_legacy_records_are_not_declared_dead(batch):
    service = ais.AutoIngestService()
    batch.update(status="running", worker_protocol=1)
    ais._save_ledger(1, {"batches": {"batch": batch}})
    handle = ais.liveness.acquire(ais._ledger_path(1), "batch")
    try:
        assert (
            service.get_progress(tenant_id=1, batch_id="batch", owner_user_id=7)["status"]
            == "running"
        )
    finally:
        ais.liveness.release(handle)
    batch.pop("worker_protocol")
    ais._save_ledger(1, {"batches": {"batch": batch}})
    assert (
        service.get_progress(tenant_id=1, batch_id="batch", owner_user_id=7)["status"] == "running"
    )


def test_recovery_does_not_cross_owner_mod_or_tenant(batch, monkeypatch):
    batch.update(status="running", worker_protocol=1)
    ais._save_ledger(1, {"batches": {"batch": batch}})
    service = ais.AutoIngestService()
    with pytest.raises(EltError):
        service.get_batch(tenant_id=1, batch_id="batch", owner_user_id=8)
    assert service.get_batch(tenant_id=2, batch_id="batch", owner_user_id=7) is None
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "different")
    assert service.get_batch(tenant_id=1, batch_id="batch", owner_user_id=7) is None
    assert ais._load_ledger(1)["batches"]["batch"]["status"] == "running"


def test_process_exit_releases_worker_ownership(batch):
    import os
    import subprocess
    import sys

    code = """
import sys, time
from pathlib import Path
from app.application.elt.auto_ingest_liveness import acquire
handle = acquire(Path(sys.argv[1]), 'batch')
print('locked', flush=True)
time.sleep(60)
"""
    batch.update(status="running", worker_protocol=1)
    ais._save_ledger(1, {"batches": {"batch": batch}})
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(ais._ledger_path(1))],
        stdout=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        service = ais.AutoIngestService()
        assert (
            service.get_progress(tenant_id=1, batch_id="batch", owner_user_id=7)["status"]
            == "running"
        )
        child.kill()
        child.wait(timeout=10)
        assert (
            service.get_progress(tenant_id=1, batch_id="batch", owner_user_id=7)["status"]
            == "failed"
        )
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdout.close()


def test_interrupted_worker_reconciles_existing_business_receipt(batch, monkeypatch):
    from unittest.mock import MagicMock

    from app.application.elt import service
    from app.db import session

    batch.update(
        status="running", worker_protocol=1, business={"run_id": "run"}, knowledge={"action": "new"}
    )
    ais._save_ledger(1, {"batches": {"batch": batch}})
    engine = MagicMock()
    engine.get_run.return_value = {"status": "completed", "summary": {"new": 1}}
    monkeypatch.setattr(service, "get_elt_service", lambda: engine)
    monkeypatch.setattr(session, "get_db", MagicMock())
    result = ais.AutoIngestService().get_batch(tenant_id=1, batch_id="batch", owner_user_id=7)
    assert result["status"] == "applied"
    engine.execute.assert_not_called()
    assert engine.get_run.call_args.kwargs == {"run_id": "run", "owner_user_id": 7}
