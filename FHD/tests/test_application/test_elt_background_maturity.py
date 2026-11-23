"""Original ETL entry points keep bounded resources and durable execution fences."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psutil
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import db as runtime_db
from app.application.agent_orchestrator import tool_process
from app.application.elt import service as service_module
from app.application.elt import service_background as background
from app.application.elt import service_draft, service_execution, service_preview, service_uploads
from app.application.elt.errors import EltConflict, EltError
from app.application.elt.operation_owner import OWNED_EXECUTE, activate_operation, claim_operation
from app.application.elt.service import EltService, mark_interrupted_runs_on_startup
from app.db.db_base import Base
from app.db.models import PurchaseUnit
from app.db.models.elt import EltRun, EltUpload
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


class HeldExecutor:
    def __init__(self):
        self.futures = []

    def submit(self, *_args, **_kwargs):
        future = Future()
        self.futures.append(future)
        return future


class ObservedExecutor(ThreadPoolExecutor):
    def __init__(self):
        super().__init__(max_workers=4)
        self.futures = []

    def submit(self, fn, /, *args, **kwargs):
        future = super().submit(fn, *args, **kwargs)
        self.futures.append(future)
        return future


class ScopedEltService(EltService):
    def __init__(self):
        assert get_request_active_mod_id() == "reviewed-mod"
        assert current_tenant_id() == 1
        super().__init__()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'business.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELT_MAX_IN_FLIGHT", "4")
    monkeypatch.setenv("ELT_TENANT_MAX_IN_FLIGHT", "2")
    monkeypatch.setenv("ELT_EXECUTION_RESERVED", "1")
    monkeypatch.setenv("ELT_BACKGROUND_TIMEOUT_SECONDS", "90")
    monkeypatch.setattr(runtime_db, "HostSessionLocal", factory)
    monkeypatch.setattr(service_uploads, "get_app_data_dir", lambda: str(tmp_path))
    for module in (service_preview, service_execution, service_draft):
        monkeypatch.setattr(module, "new_session", factory)
    assert not background._ADMITTED
    store = SimpleNamespace(factory=factory, engine=engine, service=EltService(), root=tmp_path)
    yield store
    # Test-only disposal after the real process supervisor has completed. A real
    # unverified slot is deliberately retained until the backend is restarted.
    with background.SUBMITTED_LOCK:
        background._ADMITTED.clear()
        background.SUBMITTED.clear()
    engine.dispose()


def seed(store, *, tenant=1, kind="preview"):
    run_id, upload_id = str(uuid4()), str(uuid4())
    with tenant_scope(tenant), store.factory.begin() as db:
        db.add(
            EltUpload(
                id=upload_id,
                tenant_id=tenant,
                owner_user_id=7,
                file_name="source.csv",
                suffix=".csv",
                size_bytes=1,
                sha256="a" * 64,
                storage_path=str(store.root / "source.csv"),
            )
        )
        db.flush()
        status = (
            "executing" if kind == "execute" else "previewing" if kind == "revalidate" else "queued"
        )
        db.add(
            EltRun(
                id=run_id,
                tenant_id=tenant,
                owner_user_id=7,
                upload_id=upload_id,
                target_type="customers",
                file_sha256="a" * 64,
                status=status,
                stage=status,
            )
        )
    return run_id


def submit(store, run_id, *, tenant=1, kind="preview", token=None):
    if kind == "execute":
        store.service._submit_execution(run_id, tenant, 7, False, operation_token=token)
    elif kind == "revalidate":
        store.service._submit_revalidation(run_id, tenant, 7, operation_token=token)
    else:
        store.service._submit_preview(run_id, tenant, 7, operation_token=token)


def use_executor(monkeypatch, executor):
    for module in (service_preview, service_execution, service_draft):
        monkeypatch.setattr(module, "EXECUTOR", executor)


def assert_not_started(store, run_id, tenant=1):
    with tenant_scope(tenant), store.factory() as db:
        run = db.get(EltRun, run_id)
        assert (run.status, run.error_code, run.operation_token) == (
            "failed",
            "ELT_BACKGROUND_NOT_STARTED",
            None,
        )
        audits = db.execute(
            text("SELECT payload FROM ai_action_audit WHERE action='elt_exception'")
        )
        assert any(
            (body := json.loads(row[0])).get("run_id") == run_id
            and body["outcome"] == "not_started"
            for row in audits
        )
    assert run_id not in background.SUBMITTED


def test_original_entries_bound_total_tenant_and_preserve_execution_capacity(storage, monkeypatch):
    executor = HeldExecutor()
    use_executor(monkeypatch, executor)
    try:
        for _ in range(2):
            submit(storage, seed(storage))
        rejected = seed(storage)
        with pytest.raises(EltError, match="容量已满"):
            submit(storage, rejected)
        assert_not_started(storage, rejected)
        submit(storage, seed(storage, tenant=2), tenant=2)
        preview = seed(storage, tenant=3)
        with pytest.raises(EltError, match="容量已满"):
            submit(storage, preview, tenant=3)
        assert_not_started(storage, preview, 3)
        execute = seed(storage, tenant=3, kind="execute")
        submit(storage, execute, tenant=3, kind="execute")
        rejected = seed(storage, tenant=4, kind="execute")
        with pytest.raises(EltError, match="容量已满"):
            submit(storage, rejected, tenant=4, kind="execute")
        assert_not_started(storage, rejected, 4)
        assert len(executor.futures) == len(background._ADMITTED) == 4
    finally:
        for future in executor.futures:
            future.cancel()
    assert not background._ADMITTED


@pytest.mark.parametrize("kind", ["preview", "revalidate", "execute"])
def test_original_submission_failure_clears_only_its_reservation(storage, monkeypatch, kind):
    class ClosedExecutor:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("executor closed")

    use_executor(monkeypatch, ClosedExecutor())
    run_id = seed(storage, kind=kind)
    with pytest.raises(RuntimeError, match="executor closed"):
        submit(storage, run_id, kind=kind)
    assert_not_started(storage, run_id)
    assert not background._ADMITTED


def test_durable_dispatch_claim_and_old_callback_cannot_replace_new_owner(storage, monkeypatch):
    executor = HeldExecutor()
    use_executor(monkeypatch, executor)
    run_id = seed(storage)
    submit(storage, run_id)
    old = background._ADMITTED[run_id]
    submit(storage, run_id)
    submit(storage, run_id, token=old.owner.token)
    assert len(executor.futures) == 1
    # Another server has no process-local registration; it must still lose the DB CAS.
    with background.SUBMITTED_LOCK:
        background._ADMITTED.pop(run_id)
    with pytest.raises(EltConflict):
        submit(storage, run_id, token=old.owner.token)
    replacement = replace(old, owner=replace(old.owner, token=str(uuid4())))
    with background.SUBMITTED_LOCK:
        background._ADMITTED[run_id] = replacement
    background._release(old)
    assert background._ADMITTED[run_id] is replacement
    assert run_id in background.SUBMITTED
    with storage.factory() as db:
        assert db.get(EltRun, run_id).operation_token == old.owner.token
    executor.futures[0].cancel()


def test_original_preview_revalidation_and_confirmed_execution_cross_spawn(storage, monkeypatch):
    monkeypatch.setattr(service_module, "EltService", ScopedEltService)
    token = set_request_active_mod_id("reviewed-mod")
    try:
        _review_and_execute(storage, monkeypatch)
    finally:
        reset_request_active_mod_id(token)


def _review_and_execute(storage, monkeypatch):
    with ObservedExecutor() as executor, tenant_scope(1):
        use_executor(monkeypatch, executor)
        with storage.factory() as db:
            upload = storage.service.save_upload(
                db,
                owner_user_id=7,
                file_name="customers.csv",
                content_type="text/csv",
                stream=BytesIO("客户名称,电话\n测试客户,13000000001\n".encode()),
            )
            db.commit()
            created = storage.service.create_preview(
                db, owner_user_id=7, upload_id=upload["upload_id"], target_type="customers"
            )
        executor.futures[-1].result(timeout=100)
        with storage.factory() as db:
            preview = storage.service.get_run(db, run_id=created["id"], owner_user_id=7)
            assert preview["status"] == "preview_ready", preview["error"]
            draft = preview["draft"]
            draft["field_mappings"] = [
                {"source": "客户名称", "target": "customer_name", "confirmed": True}
            ]
            storage.service.update_draft(db, run_id=created["id"], owner_user_id=7, patch=draft)
        executor.futures[-1].result(timeout=100)
        with storage.factory() as db:
            reviewed = storage.service.get_run(db, run_id=created["id"], owner_user_id=7)
            assert reviewed["status"] == "preview_ready", reviewed["error"]
            with pytest.raises(EltError):
                storage.service.execute(
                    db,
                    run_id=created["id"],
                    owner_user_id=7,
                    confirmed=True,
                    valid_rows_only=False,
                    preview_revision="0" * 64,
                )
            assert db.query(PurchaseUnit).count() == 0
            storage.service.execute(
                db,
                run_id=created["id"],
                owner_user_id=7,
                confirmed=True,
                valid_rows_only=False,
                preview_revision=reviewed["preview_revision"],
            )
        executor.futures[-1].result(timeout=100)
        with storage.factory() as db:
            completed = db.get(EltRun, created["id"])
            assert (completed.status, completed.executed_rows, completed.operation_token) == (
                "completed",
                1,
                None,
            )
            assert db.query(PurchaseUnit).one().unit_name == "测试客户"
        assert not background._ADMITTED


def _hang_owned_elt(_service_type, job, control, start, deadline):
    if not tool_process._worker_start(control, start, deadline, monitored_memory=True):
        return
    engine = create_engine(job.database_url)
    with tenant_scope(job.owner.tenant_id), sessionmaker(bind=engine)() as db:
        run = db.get(EltRun, job.owner.run_id)
        activate_operation(db, run, OWNED_EXECUTE, job.owner.token)
        db.commit()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(90)"], start_new_session=True
    )
    Path(engine.url.database).with_suffix(".worker.json").write_text(
        json.dumps(
            [
                {"pid": pid, "created": psutil.Process(pid).create_time()}
                for pid in (os.getpid(), child.pid)
            ]
        )
    )
    time.sleep(90)


@pytest.mark.parametrize("proof", [True, False])
def test_real_hung_owned_tree_is_reaped_and_only_proven_cleanup_releases(
    storage, monkeypatch, proof
):
    monkeypatch.setattr(background, "_worker", _hang_owned_elt)
    original_wait = tool_process._WorkerProcessSupervisor.wait_ack

    def short_execution_deadline(supervisor, control, marker, deadline, **kwargs):
        # Keep cold-import/startup time separate from the injected execution hang.
        if marker == b"d":
            deadline = min(deadline, time.monotonic() + 5)
        return original_wait(supervisor, control, marker, deadline, **kwargs)

    monkeypatch.setattr(tool_process._WorkerProcessSupervisor, "wait_ack", short_execution_deadline)
    if not proof:
        original = tool_process._WorkerProcessSupervisor

        class MissingCleanupReceipt(original):
            def close(self):
                super().close()
                self.clean = False

        monkeypatch.setattr(tool_process, "_WorkerProcessSupervisor", MissingCleanupReceipt)
    run_id = seed(storage, kind="execute")
    with ObservedExecutor() as executor:
        use_executor(monkeypatch, executor)
        submit(storage, run_id, kind="execute")
        executor.futures[-1].result(timeout=100)
    identities = json.loads((storage.root / "business.worker.json").read_text())
    for identity in identities:
        try:
            process = psutil.Process(identity["pid"])
            assert (
                process.create_time() != identity["created"]
                or process.status() == psutil.STATUS_ZOMBIE
            )
        except psutil.NoSuchProcess:
            pass
    with tenant_scope(1), storage.factory() as db:
        run = db.get(EltRun, run_id)
        assert run.status == "outcome_unknown" and run.operation_token
        assert run.operation_kind == OWNED_EXECUTE
        with pytest.raises(EltConflict):
            claim_operation(db, run, "execute_queue", allowed_statuses={"outcome_unknown"})
    assert (run_id not in background._ADMITTED) is proof


def test_restart_and_stale_recovery_never_reclaim_owned_execution(storage, monkeypatch):
    from app.application.elt import stale_watchdog
    from app.application.elt.operation_owner import recover_stale_owner

    run_id = seed(storage, kind="execute")
    with tenant_scope(1), storage.factory() as db:
        run = db.get(EltRun, run_id)
        run.operation_kind, run.operation_token = OWNED_EXECUTE, str(uuid4())
        run.operation_lease_until = run.updated_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
        token = run.operation_token
        assert recover_stale_owner(db, run)
        assert (run.status, run.operation_token) == ("outcome_unknown", token)
        run.status = run.stage = "executing"
        db.commit()
    assert mark_interrupted_runs_on_startup(storage.engine) == 1
    with tenant_scope(1), storage.factory() as db:
        run = db.get(EltRun, run_id)
        assert (run.status, run.operation_token) == ("outcome_unknown", token)
        run.status = run.stage = "executing"
        run.updated_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    monkeypatch.setattr(runtime_db, "get_engine", lambda: storage.engine)
    assert stale_watchdog.sweep_stale_runs() == 1
    with tenant_scope(1), storage.factory() as db:
        run = db.get(EltRun, run_id)
        assert (run.status, run.operation_token) == ("outcome_unknown", token)
        with pytest.raises(EltConflict):
            storage.service.retry(db, run_id=run_id, owner_user_id=7)
