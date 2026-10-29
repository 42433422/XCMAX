"""Regression contracts for durable dispatch upgrades and pre-hook failures."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from retort_engine.history import RetortHistoryStore
from retort_engine.models import ImprovementTask
from retort_engine.runtime_adapter import RetortEmployeeRuntimeAdapter


def task():
    return ImprovementTask("same", "title", "dimension", "why", "action", "accept")


def history_count(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM employee_tasks").fetchone()[0]


def test_queue_only_history_is_idempotent_across_concurrent_submissions(tmp_path):
    history = tmp_path / "history.sqlite"
    adapter = RetortEmployeeRuntimeAdapter(tmp_path / "q.jsonl", history_store=history)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda _: adapter.submit_tasks([task()], source="review"), range(8)
            )
        )
    assert history_count(history) == 1
    assert adapter.queue.load()[0]["status"] == "queued"
    calls = []
    later = RetortEmployeeRuntimeAdapter(
        tmp_path / "q.jsonl", history_store=history, dispatch_hook=calls.append
    )
    later.submit_tasks([task()], source="review")
    assert len(calls) == history_count(history) == 1


def test_history_failure_before_hook_can_recover(tmp_path, monkeypatch):
    calls = []
    adapter = RetortEmployeeRuntimeAdapter(
        tmp_path / "q.jsonl",
        history_store=tmp_path / "history.sqlite",
        dispatch_hook=calls.append,
    )
    original = RetortHistoryStore.record_employee_task

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("temporary history failure")

    monkeypatch.setattr(RetortHistoryStore, "record_employee_task", fail)
    with pytest.raises(sqlite3.OperationalError):
        adapter.submit_tasks([task()], source="review")
    assert adapter.queue.load()[0]["status"] == "queued"
    assert not calls
    monkeypatch.setattr(RetortHistoryStore, "record_employee_task", original)
    adapter.submit_tasks([task()], source="review")
    assert len(calls) == 1


def test_unversioned_legacy_queued_task_does_not_repeat_old_hook(tmp_path):
    path = tmp_path / "q.jsonl"
    # Old adapter persisted this exact shape and never changed status after hook.
    legacy = {
        "queue_id": "legacy-id",
        "task": task().to_dict(),
        "source": "review",
        "status": "queued",
        "created_at": "2026-10-29",
        "extra": "preserve",
    }
    path.write_text(json.dumps(legacy) + "\n")
    calls = ["old version already dispatched"]
    adapter = RetortEmployeeRuntimeAdapter(path, dispatch_hook=calls.append)
    adapter.submit_tasks([task()], source="review")
    assert len(calls) == 1
    row = adapter.queue.load()[0]
    assert row["status"] == "dispatch_unknown"
    assert row["queue_id"] == "legacy-id" and row["extra"] == "preserve"
