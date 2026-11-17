"""Claims serialize across workers; remote maintenance never holds the ledger lock."""

import json
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.application.autonomy import approval_resume as ledger
from app.application.autonomy import maintenance_console as service
from scripts.autonomy import rundeck_executor

JOB = "eaf2fd6d-c7fa-48d4-9ed0-b682ad85eca1"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for name, filename in {
        "XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH": "ledger.jsonl",
        "XCAGI_AUTONOMY_AUDIT_LOG_PATH": "audit.jsonl",
        "XCAGI_AUTONOMY_AUDIT_DB_PATH": "audit.sqlite3",
        "XCAGI_AUTONOMY_METRICS_LOG_PATH": "metrics.jsonl",
    }.items():
        monkeypatch.setenv(name, str(tmp_path / filename))
    monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("XCAGI_RUNDECK_URL", "https://synthetic.invalid")
    monkeypatch.setenv("XCAGI_RUNDECK_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("XCAGI_RUNDECK_JOBS", json.dumps({"clear_logs": JOB}))
    return tmp_path


def pending(action_id):
    decision, row = ledger.request_action("clear_logs", action_id=action_id, executor_name="test")
    assert row["state"] == "pending_approval"
    return decision


@pytest.mark.parametrize("operation", ["resume", "reject", "mark", "request"])
def test_claim_cannot_be_overwritten_by_concurrent_transition(isolated, monkeypatch, operation):
    action_id = str(uuid4())
    pending(action_id)
    entered, release, competing = threading.Event(), threading.Event(), threading.Event()
    original = ledger.evaluate_risk
    original_latest = ledger._latest
    overlapping = threading.Event()

    def observed_latest(*args):
        if entered.is_set() and not release.is_set():
            overlapping.set()
        return original_latest(*args)

    def held_risk(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    def transition():
        competing.set()
        if operation == "resume":
            return ledger.resume_action(action_id, approver="other", defer_execution=True)
        if operation == "reject":
            return ledger.reject_action(action_id, approver="other")
        if operation == "mark":
            return ledger.mark_approval_requested(action_id, approval_id="other")
        return ledger.request_action("clear_logs", action_id=action_id)[1]

    monkeypatch.setattr(ledger, "evaluate_risk", held_risk)
    monkeypatch.setattr(ledger, "_latest", observed_latest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ledger.resume_action, action_id, approver="admin", defer_execution=True)
        assert entered.wait(5)
        second = pool.submit(transition)
        assert competing.wait(5)
        try:
            assert not overlapping.wait(0.1), "competing transition read an unclaimed pending row"
        finally:
            release.set()
        assert first.result(timeout=5)["state"] == "approved"
        if operation == "request":
            assert second.result(timeout=5)["state"] == "approved"
        else:
            with pytest.raises(ledger.ApprovalStateError, match="not pending"):
                second.result(timeout=5)
    assert ledger.get_action_state(action_id)["state"] == "approved"


def test_concurrent_maintenance_preserves_success_and_releases_claim_lock(isolated, monkeypatch):
    submitted, release = threading.Event(), threading.Event()
    posts = []

    class Session:
        def __init__(self):
            self.headers = {}

        def close(self):
            pass

        def request(self, method, url, **kwargs):
            if method == "POST":
                posts.append(url)
                submitted.set()
                assert release.wait(5)
                data = {"id": 99}
            else:
                data = {"job": {"id": JOB}, "status": "succeeded"}
            return SimpleNamespace(status_code=200, json=lambda: data)

    monkeypatch.setattr(rundeck_executor.requests, "Session", Session)
    action_id = service.request_run("clear_logs", str(uuid4()), "operator")["action_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ledger.resume_action, action_id, approver="admin")
        try:
            assert submitted.wait(5)
            second = pool.submit(ledger.resume_action, action_id, approver="other")
            with pytest.raises(ledger.ApprovalStateError, match="not pending"):
                second.result(timeout=2)
            # Read and an unrelated request both finish while remote HTTP is blocked.
            assert ledger.get_action_state(action_id)["state"] == "approved"
            pending(str(uuid4()))
        finally:
            release.set()
        assert first.result(timeout=5)["state"] == "executed"
    assert len(posts) == 1
    assert ledger.get_action_state(action_id)["state"] == "executed"


def _process_resume(action_id, start, output, effects):
    original = ledger.evaluate_risk

    def delayed_risk(*args, **kwargs):
        # Widen the old read/append race without relying on fork-inherited locks.
        threading.Event().wait(0.1)
        return original(*args, **kwargs)

    def execute(payload):
        with Path(effects).open("a") as stream:
            stream.write("executed\n")
        return {"ok": True}

    start.wait(10)
    with patch.object(ledger, "evaluate_risk", delayed_risk):
        try:
            output.put(ledger.resume_action(action_id, approver="admin", executor=execute)["state"])
        except ledger.ApprovalStateError:
            output.put("not_pending")


def test_two_spawned_workers_execute_once(isolated):
    action_id = str(uuid4())
    pending(action_id)
    context = multiprocessing.get_context("spawn")
    start, output = context.Event(), context.Queue()
    effects = isolated / "effects.txt"
    workers = [
        context.Process(target=_process_resume, args=(action_id, start, output, str(effects)))
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        start.set()
        results = [output.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert sorted(results) == ["executed", "not_pending"]
        assert effects.read_text() == "executed\n"
        assert ledger.get_action_state(action_id)["state"] == "executed"
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()
        output.close()


def test_lock_failure_preserves_pending_and_executor(isolated, monkeypatch):
    action_id = str(uuid4())
    pending(action_id)
    calls = []
    ledger.register_action_executor(
        "test", lambda payload: calls.append(payload), action_id=action_id
    )
    with monkeypatch.context() as locked:
        locked.setattr(
            ledger,
            "exclusive_file_lock",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("busy")),
        )
        with pytest.raises(ledger.ApprovalStateError, match="ledger unavailable"):
            ledger.resume_action(action_id, approver="admin")
    assert ledger.get_action_state(action_id)["state"] == "pending_approval"
    assert not calls
    assert ledger.resume_action(action_id, approver="admin")["state"] == "executed"
    assert len(calls) == 1
