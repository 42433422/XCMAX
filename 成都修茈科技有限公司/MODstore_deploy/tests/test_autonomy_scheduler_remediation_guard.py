import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def env(monkeypatch, tmp_path):
    from modstore_server import autonomy_scheduler as m
    from modstore_server import scheduler_runtime as runtime
    from modstore_server.maintenance_loop import coordinator, store

    memory = {"open_items": []}
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(store, "_load_loop_memory", lambda: memory)
    monkeypatch.setattr(store, "ledger_path", lambda: ledger)
    dispatch = Mock(return_value={"status": "failed", "error": "git_prep_unavailable"})
    monkeypatch.setattr(coordinator, "run_self_maintenance_loop", dispatch)
    monkeypatch.setattr(m, "register_founder_scorecard_job", lambda *_: None)
    monkeypatch.setattr(m, "_reconcile_completed_loop_memory_safely", lambda: None)
    monkeypatch.setattr(m, "_remediation_lineage_by_run_id", lambda: {})
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_REMEDIATION_COOLDOWN_MINUTES", "15")
    clock = [datetime(2026, 10, 23, tzinfo=UTC)]

    class Clock:
        @classmethod
        def now(cls, tz=None):
            return clock[0]

        fromisoformat = staticmethod(datetime.fromisoformat)

    monkeypatch.setattr(m, "datetime", Clock)
    item = {
        "kind": "automated_remediation",
        "branch": "repair",
        "task_id": "task-a",
        "run_id": "origin",
        "reason": "structured_qa_verdict_not_pass",
    }
    memory["open_items"] = [item]
    return SimpleNamespace(
        m=m,
        runtime=runtime,
        store=store,
        dispatch=dispatch,
        memory=memory,
        ledger=ledger,
        clock=clock,
        item=item,
    )


def attempt(e):
    with pytest.raises(RuntimeError, match="git_prep_unavailable"):
        e.m.run_pending_automated_remediation()


@pytest.mark.parametrize("kind", ["automated_remediation", "failed_steps"])
def test_limit_stops_real_dispatch_for_both_kinds(env, kind):
    env.item.update(kind=kind, steps=["code"])
    for _ in range(3):
        attempt(env)
        env.clock[0] += timedelta(days=1)
    before = env.ledger.read_bytes()
    with pytest.raises(env.m.RemediationBlocked) as ex:
        env.m.run_pending_automated_remediation()
    assert ex.value.receipt == {
        "status": "blocked",
        "reason": "retry_limit",
        "attempts": 3,
        "retry_at": None,
        "scheduler_status": "failed",
    }
    assert env.dispatch.call_count == 3
    assert env.ledger.read_bytes() == before
    assert len(env.memory["open_items"]) == 1


def test_switching_kind_does_not_reset_budget(env):
    for _ in range(3):
        attempt(env)
        env.clock[0] += timedelta(days=1)
    env.item.update(kind="failed_steps", steps=["code"])
    with pytest.raises(env.m.RemediationBlocked, match="retry_limit"):
        env.m.run_pending_automated_remediation()
    assert env.dispatch.call_count == 3


@pytest.mark.parametrize(
    "change", [{"task_id": "task-b"}, {"task_id": "task-c", "generation": "new"}]
)
def test_new_task_or_generation_has_own_budget(env, change):
    for _ in range(3):
        attempt(env)
        env.clock[0] += timedelta(days=1)
    env.item.update(change)
    attempt(env)
    assert env.dispatch.call_count == 4
    assert json.loads(env.ledger.read_text().splitlines()[-1])["attempt"] == 1


def test_same_task_other_kind_cannot_hide_stored_limit(env):
    env.memory["open_items"].append(
        {**env.item, "kind": "failed_steps", "steps": ["code"], "retry_count": 15}
    )
    with pytest.raises(env.m.RemediationBlocked, match="retry_limit"):
        env.m.run_pending_automated_remediation()
    env.dispatch.assert_not_called()


def test_other_task_old_count_not_inherited(env):
    env.memory["open_items"].insert(0, {**env.item, "task_id": "old", "retry_count": 15})
    attempt(env)
    assert env.dispatch.call_count == 1


def test_backoff_exact_boundary_and_exponential_delay(env):
    attempt(env)
    env.clock[0] += timedelta(minutes=15, microseconds=-1)
    with pytest.raises(env.m.RemediationBlocked, match="backoff") as ex:
        env.m.run_pending_automated_remediation()
    assert ex.value.receipt["retry_at"] == "2026-10-23T00:15:00+00:00"
    assert env.dispatch.call_count == 1
    env.clock[0] += timedelta(microseconds=1)
    attempt(env)
    env.clock[0] += timedelta(minutes=15)
    with pytest.raises(env.m.RemediationBlocked, match="backoff"):
        env.m.run_pending_automated_remediation()
    env.clock[0] += timedelta(minutes=15)
    attempt(env)
    assert env.dispatch.call_count == 3


def test_reservation_survives_restart_and_dispatch_crash(env):
    env.dispatch.side_effect = OSError("worker died")
    with pytest.raises(OSError):
        env.m.run_pending_automated_remediation()
    assert json.loads(env.ledger.read_text())["attempt"] == 1
    # No in-memory guard counter exists: reuse the ledger after the worker is replaced.
    env.dispatch = Mock(return_value={"status": "failed", "error": "git_prep_unavailable"})
    with pytest.raises(env.m.RemediationBlocked, match="backoff"):
        env.m.run_pending_automated_remediation()
    env.dispatch.assert_not_called()


@pytest.mark.parametrize(
    "damage",
    [
        "{not json}\n",
        json.dumps(
            {
                "phase": "remediation_attempt",
                "remediation_key": ["repair", "task-a"],
                "attempt": 1,
                "timestamp": "bad",
            }
        )
        + "\n",
    ],
)
def test_corrupt_guard_evidence_fails_closed(env, damage):
    env.ledger.write_text(damage)
    with pytest.raises((ValueError, RuntimeError)):
        env.m.run_pending_automated_remediation()
    env.dispatch.assert_not_called()
    assert env.ledger.read_text() == damage


def test_failed_ledger_write_prevents_dispatch(env, monkeypatch):
    monkeypatch.setattr(env.store, "ledger_path", lambda: Path("/dev/null/no-ledger"))
    with pytest.raises(OSError):
        env.m.run_pending_automated_remediation()
    env.dispatch.assert_not_called()


@pytest.mark.parametrize("reason", ["retry_limit", "backoff"])
def test_blocked_job_remains_failed_in_real_runtime_projection(env, monkeypatch, reason):
    if reason == "retry_limit":
        env.item["retry_count"] = 3
    else:
        attempt(env)
    records = []
    monkeypatch.setattr(env.runtime, "record_job_run", lambda **kw: records.append(kw))
    scheduler = Mock()
    env.m.register_autonomy_jobs(scheduler)
    scheduler.add_job.call_args.args[0]()
    assert records[-1]["status"] == "failed"
    assert f"remediation_blocked:{reason}" in records[-1]["error"]
    row = SimpleNamespace(id=1, **records[-1])
    health = env.runtime._job_summary(
        "self_maintenance_remediation_loop", [row], now=env.clock[0], stale_after=3600
    )
    assert health["state"] == "failing"
    assert health["last_success_at"] is None
    assert env.dispatch.call_count == (reason == "backoff")


def test_unknown_transport_error_not_mislabeled_missing_branch(env):
    attempt(env)
    raw = env.ledger.read_text()
    assert "branch_missing" not in raw
    assert env.memory["open_items"] == [env.item]


def test_legacy_partial_budget_without_timestamp_blocks_instead_of_guessing(env):
    env.item["retry_count"] = 1
    with pytest.raises(env.m.RemediationBlocked, match="retry_history_timestamp_missing"):
        env.m.run_pending_automated_remediation()
    env.dispatch.assert_not_called()


def test_concurrent_ticks_share_one_durable_reservation(env):
    from concurrent.futures import ThreadPoolExecutor

    def tick(_):
        try:
            env.m.run_pending_automated_remediation()
        except RuntimeError as e:
            return str(e)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(tick, range(8)))
    assert sum("git_prep_unavailable" in x for x in outcomes) == 1
    assert sum("remediation_blocked:backoff" in x for x in outcomes) == 7
    assert env.dispatch.call_count == 1
    assert len(env.ledger.read_text().splitlines()) == 1


def test_existing_failure_rows_are_preserved_byte_for_byte(env):
    original = (
        json.dumps({"phase": "complete", "status": "failed", "error": "original QA veto"}) + "\n"
    )
    env.ledger.write_text(original)
    attempt(env)
    assert env.ledger.read_text().startswith(original)
    assert env.memory["open_items"] == [env.item]


@pytest.mark.parametrize("kind", ["automated_remediation", "failed_steps"])
def test_exhausted_legacy_record_cannot_be_reported_as_no_pending_success(env, kind):
    env.item.update(kind=kind, steps=["code"], retry_count=3)
    with pytest.raises(env.m.RemediationBlocked, match="retry_limit"):
        env.m.run_pending_automated_remediation()
    env.dispatch.assert_not_called()


def test_arbitrary_generation_string_cannot_reset_real_task_budget(env):
    for _ in range(3):
        attempt(env)
        env.clock[0] += timedelta(days=1)
    env.item["generation"] = "invented-reset"
    with pytest.raises(env.m.RemediationBlocked, match="retry_limit"):
        env.m.run_pending_automated_remediation()
    assert env.dispatch.call_count == 3


def test_guard_rows_do_not_displace_real_evidence_window(env):
    real = {
        "phase": "complete",
        "run_id": "actual-run",
        "status": "failed",
        "completed_at": env.clock[0].isoformat(),
    }
    guard = {
        "phase": "remediation_attempt",
        "run_id": "guard",
        "timestamp": env.clock[0].isoformat(),
    }
    env.ledger.write_text(json.dumps(real) + "\n" + (json.dumps(guard) + "\n") * 1000)
    from modstore_server.maintenance_loop import store

    rows = store._read_ledger(limit=1)
    assert rows == [real]
    assert store._select_recent_milestone_rows(rows, now=env.clock[0]) == [real]


def test_real_ledger_appender_and_guard_preserve_each_others_rows(env):
    attempt(env)
    env.store._append_ledger({"phase": "complete", "run_id": "actual", "status": "failed"})
    assert env.store._read_ledger(limit=10) == [
        {
            "phase": "complete",
            "run_id": "actual",
            "status": "failed",
            "correlation_id": "actual",
            "ledger_schema_version": 2,
        }
    ]
    with pytest.raises(env.m.RemediationBlocked, match="backoff"):
        env.m.run_pending_automated_remediation()
    assert len(env.ledger.read_text().splitlines()) == 2


def test_business_reader_keeps_bounded_memory_for_small_requested_window(env):
    import tracemalloc

    from modstore_server.maintenance_loop import store

    row = json.dumps({"phase": "complete", "run_id": "real", "payload": "x" * 10000}) + "\n"
    with env.ledger.open("w") as fh:
        for _ in range(1000):
            fh.write(row)
    tracemalloc.start()
    try:
        rows = env.store._read_ledger(limit=2)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(rows) == 2
    assert peak < 2_000_000  # Fixture is >10 MB; retaining the entire ledger fails this.


@pytest.mark.parametrize("resolved", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
def test_new_task_success_does_not_greenwash_older_blocked_scope(env, resolved, deferred):
    old = {**env.item, "task_id": "old-blocked", "retry_count": 3}
    env.memory["open_items"].insert(0, old)

    def complete(**_):
        env.memory["open_items"] = [] if resolved else [old]
        if deferred:
            return {"status": "failed", "error": "retort_clarification_pending"}
        return {"status": "completed_merged"}

    env.dispatch.side_effect = complete
    if resolved:
        result = env.m.run_pending_automated_remediation()
        if deferred:
            assert result["scheduler_status"] == "deferred"
        else:
            assert result["status"] == "completed_merged"
    else:
        with pytest.raises(env.m.RemediationBlocked, match="other_retry_limit"):
            env.m.run_pending_automated_remediation()
    assert env.dispatch.call_count == 1


@pytest.mark.parametrize("new_task", ["task-a", "task-b"])
def test_real_memory_writer_does_not_transfer_retry_count_to_new_task(
    monkeypatch, tmp_path, new_task
):
    from modstore_server.maintenance_loop import outcomes, store

    path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("DEVFLEET_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setattr(
        outcomes.self_evolution_knowledge, "salvage_kb_from_workspace", lambda **_: {}
    )
    monkeypatch.setattr(
        outcomes.self_evolution_knowledge,
        "record_loop_evolution_knowledge",
        lambda *_: {},
    )
    old = {
        "kind": "failed_steps",
        "run_id": "old-run",
        "branch": "repair",
        "para_task_id": "task-a",
        "retry_count": 2,
        "steps": ["code"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps({"open_items": [old], "closed_items": [], "recent_runs": []}))
    outcomes._update_loop_memory(
        {
            "run_id": "new-run",
            "branch": "repair",
            "para_task_id": new_task,
            "status": "failed",
            "steps": [{"step": "code", "ok": False}],
            "resume_candidate": {"failed_run_id": "old-run"},
        },
        {},
    )
    rows = store._load_loop_memory()["open_items"]
    by_task = {row.get("task_id") or row.get("para_task_id"): row for row in rows}
    if new_task == "task-a":
        assert len(rows) == 1 and by_task["task-a"]["retry_count"] == 3
    else:
        assert len(rows) == 2
        assert by_task["task-a"]["retry_count"] == 2
        assert by_task["task-b"]["retry_count"] == 1
        from modstore_server import autonomy_scheduler as scheduler

        with pytest.raises(scheduler.RemediationBlocked, match="backoff") as ex:
            scheduler._reserve_remediation_attempt({"branch": "repair", "task_id": "task-b"})
        assert ex.value.receipt["attempts"] == 1


def test_existing_failure_timestamp_controls_legacy_backoff(env):
    env.item.update(retry_count=1, created_at=env.clock[0].isoformat())
    with pytest.raises(env.m.RemediationBlocked, match="backoff"):
        env.m.run_pending_automated_remediation()
    env.clock[0] += timedelta(minutes=15)
    attempt(env)
    assert json.loads(env.ledger.read_text())["attempt"] == 2


@pytest.mark.parametrize("old_task,new_task", [(None, "new-task"), ("old-task", None)])
def test_real_memory_writer_does_not_guess_unknown_task_from_branch(
    monkeypatch, tmp_path, old_task, new_task
):
    from modstore_server.maintenance_loop import outcomes, store

    path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("DEVFLEET_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setattr(
        outcomes.self_evolution_knowledge, "salvage_kb_from_workspace", lambda **_: {}
    )
    monkeypatch.setattr(
        outcomes.self_evolution_knowledge,
        "record_loop_evolution_knowledge",
        lambda *_: {},
    )
    old = {
        "kind": "failed_steps",
        "run_id": "old-run",
        "branch": "same-branch",
        "retry_count": 15,
        "steps": ["code"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    if old_task:
        old["para_task_id"] = old_task
    path.write_text(json.dumps({"open_items": [old], "closed_items": [], "recent_runs": []}))
    final = {
        "run_id": "new-run",
        "branch": "same-branch",
        "status": "failed",
        "steps": [{"step": "code", "ok": False}],
        "resume_candidate": {"failed_run_id": "old-run"},
    }
    if new_task:
        final["para_task_id"] = new_task
    outcomes._update_loop_memory(final, {})
    memory = store._load_loop_memory()
    by_run = {row["run_id"]: row for row in memory["open_items"]}
    assert set(by_run) == {"old-run", "new-run"}
    assert by_run["old-run"]["retry_count"] == 15
    assert by_run["old-run"].get("para_task_id") == old_task
    assert by_run["new-run"]["retry_count"] == 1
    assert by_run["new-run"].get("para_task_id") == new_task
    assert memory.get("closed_items", []) == []
