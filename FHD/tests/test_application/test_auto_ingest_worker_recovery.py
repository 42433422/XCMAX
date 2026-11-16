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
    assert retry["error"] == "ELT_AUTO_INGEST_NOT_PENDING"
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


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt, SystemExit])
def test_acquire_closes_handle_on_error_or_interruption(monkeypatch, tmp_path, failure):
    from pathlib import Path
    from unittest.mock import MagicMock

    handle = MagicMock()
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: handle)
    monkeypatch.setattr(ais.liveness, "_try_lock", Mock(side_effect=failure("injected")))
    with pytest.raises(failure):
        ais.liveness.acquire(tmp_path / "batches.json", "batch")
    handle.close.assert_called_once()


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt, SystemExit])
def test_persist_interruption_releases_guard_without_launch(batch, monkeypatch, failure):
    service = ais.AutoIngestService()
    launch = Mock()
    monkeypatch.setattr(service, "_launch_worker", launch)
    monkeypatch.setattr(ais, "_save_ledger", Mock(side_effect=failure("injected")))
    with pytest.raises(failure):
        service.release_approved_batch(batch_id="batch", tenant_id=1)
    handle = ais.liveness.acquire(ais._ledger_path(1), "batch")
    ais.liveness.release(handle)
    launch.assert_not_called()
    assert ais._load_ledger(1)["batches"]["batch"]["status"] == "awaiting_approval"


def _stale_dispatch_process(root, ready, proceed, result):
    """Real process B pauses after reading pending, before obtaining the OS lock."""
    from pathlib import Path

    ais.get_app_data_dir = lambda: root
    ais.get_request_active_mod_id = lambda: "test-mod"
    acquire = ais.liveness.acquire

    def delayed_acquire(path, batch_id):
        ready.set()
        if not proceed.wait(10):
            raise TimeoutError("test interleave timed out")
        return acquire(path, batch_id)

    ais.liveness.acquire = delayed_acquire
    service = ais.AutoIngestService()

    def replay(_batch):
        with (Path(root) / "effects").open("a") as stream:
            stream.write("replayed\n")

    service._launch_worker = replay
    try:
        result.put(service.release_approved_batch(batch_id="batch", tenant_id=1))
    except EltError as exc:
        result.put({"error": exc.code})


@pytest.mark.parametrize("settled", ["applied", "failed"])
def test_cross_process_stale_pending_never_replays_completed_dispatch(batch, monkeypatch, settled):
    import multiprocessing
    from pathlib import Path

    root = str(ais.get_app_data_dir())
    context = multiprocessing.get_context("spawn")
    ready, proceed, result = context.Event(), context.Event(), context.Queue()
    process = context.Process(target=_stale_dispatch_process, args=(root, ready, proceed, result))
    process.start()
    try:
        assert ready.wait(10)
        service = ais.AutoIngestService()

        def finish(_batch):
            with (Path(root) / "effects").open("a") as stream:
                stream.write("first\n")
            ais._patch_batch(1, "batch", status=settled)

        monkeypatch.setattr(service, "_launch_worker", finish)
        service.release_approved_batch(batch_id="batch", tenant_id=1)
        proceed.set()
        receipt = result.get(timeout=10)
        process.join(10)
        assert process.exitcode == 0
        assert (Path(root) / "effects").read_text() == "first\n"
        assert ais._load_ledger(1)["batches"]["batch"]["status"] == settled
        if settled == "applied":
            assert receipt["already_released"] is True
        else:
            assert receipt["error"] == "ELT_AUTO_INGEST_NOT_PENDING"
        handle = ais.liveness.acquire(ais._ledger_path(1), "batch")
        ais.liveness.release(handle)
    finally:
        proceed.set()
        if process.is_alive():
            process.kill()
            process.join(10)
        result.close()
        result.join_thread()


@pytest.mark.parametrize("field", ["tenant_id", "owner_user_id", "mod_id", "prepared_plan"])
def test_dispatch_rechecks_identity_and_plan_after_guard(batch, monkeypatch, field):
    acquire = ais.liveness.acquire

    def changed(path, batch_id):
        handle = acquire(path, batch_id)
        ledger = ais._load_ledger(1)
        ledger["batches"][batch_id][field] = "changed"
        ais._save_ledger(1, ledger)
        return handle

    monkeypatch.setattr(ais.liveness, "acquire", changed)
    service = ais.AutoIngestService()
    launch = Mock()
    monkeypatch.setattr(service, "_launch_worker", launch)
    with pytest.raises(EltError):
        service.release_approved_batch(batch_id="batch", tenant_id=1)
    launch.assert_not_called()
    handle = acquire(ais._ledger_path(1), "batch")
    ais.liveness.release(handle)


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit])
def test_interrupted_start_cancels_late_worker_without_leaking_guard(batch, monkeypatch, failure):
    service = ais.AutoIngestService()
    run = Mock()
    monkeypatch.setattr(service, "run", run)
    pending = []

    def interrupted(thread):
        pending.append(thread)
        raise failure("before worker claim")

    monkeypatch.setattr(ais.threading.Thread, "start", interrupted)
    with pytest.raises(failure):
        service.release_approved_batch(batch_id="batch", tenant_id=1)
    pending[0].run()  # A late worker must notice the cancelled handoff and do nothing.
    run.assert_not_called()
    assert ais._load_ledger(1)["batches"]["batch"]["error"] == "ELT_WORKER_NOT_STARTED"
    handle = ais.liveness.acquire(ais._ledger_path(1), "batch")
    ais.liveness.release(handle)


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit])
def test_start_interrupted_after_worker_claim_preserves_worker_ownership(
    batch, monkeypatch, failure
):
    from unittest.mock import MagicMock

    from app.db import session

    service = ais.AutoIngestService()
    entered, finish = ais.threading.Event(), ais.threading.Event()
    original_start = ais.threading.Thread.start
    workers = []

    def run(*_args, **_kwargs):
        entered.set()
        assert finish.wait(10)
        ais._patch_batch(1, "batch", status="applied")

    def interrupted(thread):
        workers.append(thread)
        original_start(thread)
        assert entered.wait(10)
        raise failure("after worker claim")

    monkeypatch.setattr(service, "run", run)
    monkeypatch.setattr(session, "get_db", MagicMock())
    monkeypatch.setattr(ais.threading.Thread, "start", interrupted)
    try:
        with pytest.raises(failure):
            service.release_approved_batch(batch_id="batch", tenant_id=1)
        assert ais._load_ledger(1)["batches"]["batch"]["status"] == "running"
        with pytest.raises(OSError):
            ais.liveness.acquire(ais._ledger_path(1), "batch")
    finally:
        finish.set()
        for thread in workers:
            thread.join(10)
    assert ais._load_ledger(1)["batches"]["batch"]["status"] == "applied"
    handle = ais.liveness.acquire(ais._ledger_path(1), "batch")
    ais.liveness.release(handle)


def test_background_entry_uses_worker_guard_and_reports_failed_start(batch, monkeypatch, tmp_path):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"source")
    monkeypatch.setattr(ais, "_resolve_auto_ingest_source", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        ais.threading.Thread, "start", Mock(side_effect=RuntimeError("not started"))
    )
    service = ais.AutoIngestService()
    with pytest.raises(RuntimeError, match="not started"):
        service.start_background(owner_user_id=7, tenant_id=1, source_path=source)
    rows = [row for row in ais._load_ledger(1)["batches"].values() if row["batch_id"] != "batch"]
    assert len(rows) == 1 and rows[0]["worker_protocol"] == 1
    assert rows[0]["error"] == "ELT_WORKER_NOT_STARTED"
    handle = ais.liveness.acquire(ais._ledger_path(1), rows[0]["batch_id"])
    ais.liveness.release(handle)
