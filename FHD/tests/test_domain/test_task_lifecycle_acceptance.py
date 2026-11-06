"""A19–A30 task lifecycle acceptance against the shared ledger."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.task_lifecycle.adapters import legacy_transition_allowed
from app.domain.task_lifecycle.ledger import TaskLedger, TaskLifecycleError
from app.domain.task_lifecycle.machine import retry_delay_seconds, transition_allowed

_LEGAL = [
    ("created", "queued", False),
    ("queued", "running", False),
    ("running", "waiting_approval", False),
    ("waiting_approval", "queued", False),
    ("waiting_approval", "rejected", False),
    ("running", "succeeded", False),
    ("running", "failed", False),
    ("running", "timed_out", False),
    ("running", "cancelled", False),
    ("queued", "cancelled", False),
    ("failed", "queued", True),
    ("timed_out", "queued", True),
]
_ILLEGAL = [
    ("succeeded", "running"),
    ("cancelled", "running"),
    ("rejected", "queued"),
    ("waiting_approval", "succeeded"),
    ("queued", "succeeded"),
    ("succeeded", "failed"),
    ("failed", "queued"),
    ("timed_out", "queued"),
]


class Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 11, 6, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


def ledger(**kwargs: object) -> tuple[Clock, TaskLedger]:
    clock = Clock()
    params: dict[str, object] = {
        "now": clock,
        "approvers": {"boss"},
        "admins": {"admin"},
        "jitter_ratio": 0.2,
    }
    params.update(kwargs)
    return clock, TaskLedger(**params)  # type: ignore[arg-type]


def make(book: TaskLedger, **overrides: object) -> dict:
    payload = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "employee_id": "employee-a",
        "source_type": "agent",
        "name": "对账",
        "description": "生成本月对账",
        "payload": {"action": "reconcile", "tools": ["excel"]},
        "priority": 100,
    }
    payload.update(overrides)
    return book.create(**payload)  # type: ignore[arg-type]


def run_one(book: TaskLedger, **overrides: object) -> dict:
    created = make(book, auto_queue=True, **overrides)
    claimed = book.claim_message(created["task_id"], "worker-1", f"boot-{created['task_id']}")
    assert claimed["task_id"] == created["task_id"]
    assert claimed["status"] == "running"
    return claimed


def test_sm_legal_and_illegal_transitions() -> None:
    for current, target, retryable in _LEGAL:
        assert transition_allowed(current, target, retryable=retryable)
    for current, target in _ILLEGAL:
        assert not transition_allowed(current, target, retryable=False)
    assert not transition_allowed("running", "queued")


def test_legacy_modules_share_terminal_guard() -> None:
    samples = {
        "agent": ("completed", "running"),
        "workflow": ("succeeded", "running"),
        "employee": ("success", "running"),
        "ticket": ("resolved", "running"),
    }
    for module, (current, target) in samples.items():
        assert not legacy_transition_allowed(module, current, target)


def test_a19_create_identity_payload_and_restart() -> None:
    clock, book = ledger()
    rows = [make(book, name=f"任务{index}", idempotency_key=f"k{index}") for index in range(100)]
    assert len({row["task_id"] for row in rows}) == 100
    assert all(len(row["task_id"]) == 37 and row["task_id"].startswith("task_") for row in rows)
    assert rows[0]["status"] == "created"
    queued = book.enqueue(rows[0]["task_id"])
    assert queued["status"] == "queued"
    assert queued["name"] == "任务0" and queued["description"] == "生成本月对账"
    assert queued["payload"]["action"] == "reconcile"
    other = make(
        book,
        tenant_id="tenant-b",
        user_id="user-b",
        employee_id="employee-b",
        source_type="workflow",
    )
    assert (other["tenant_id"], other["user_id"], other["employee_id"]) == (
        "tenant-b",
        "user-b",
        "employee-b",
    )
    sources = [
        make(book, source_type=source, idempotency_key=source)["source_type"]
        for source in ("agent", "workflow", "employee", "ticket")
    ]
    assert sources == ["agent", "workflow", "employee", "ticket"]
    with pytest.raises(TaskLifecycleError) as missing:
        make(book, payload={"tools": []}, required=("action",))
    assert missing.value.code == "invalid_params"
    with pytest.raises(TaskLifecycleError):
        make(book, payload="bad")  # type: ignore[arg-type]
    with pytest.raises(TaskLifecycleError):
        make(book, name="x" * 161)
    assert book.list_tenant("tenant-a")
    clock.advance(1)
    restored = TaskLedger(now=clock, approvers={"boss"})
    restored.load(book.dump())
    assert restored.get(rows[0]["task_id"])["status"] == "queued"
    assert {"task_id", "status", "tenant_id", "payload"} <= set(rows[0])


def test_a19_concurrent_create_has_unique_ids() -> None:
    _clock, book = ledger()
    found: list[str] = []
    barrier = threading.Barrier(100)

    def _create(index: int) -> None:
        barrier.wait()
        row = make(book, name=f"并发{index}", idempotency_key=f"concurrent-{index}")
        found.append(row["task_id"])

    threads = [threading.Thread(target=_create, args=(index,)) for index in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(found) == 100
    assert len(set(found)) == 100


def test_a20_queue_priority_capacity_and_isolation() -> None:
    _clock, book = ledger(max_running=5, aging_seconds=1)
    first = make(book, auto_queue=True, name="only")
    assert first["status"] == "queued"
    batch = [make(book, auto_queue=True, name=f"q{index}") for index in range(100)]
    assert len(book.list_tenant("tenant-a")) >= 101
    running = [book.claim("worker") for _ in range(5)]
    assert all(row is not None for row in running)
    assert book.claim("worker") is None
    for row in running:
        book.succeed(row["task_id"], "worker", {"ok": True})  # type: ignore[index]
    clock2, fair = ledger(max_running=1, aging_seconds=1)
    low = make(fair, auto_queue=True, name="low", priority=100)
    clock2.advance(101)
    high = make(fair, auto_queue=True, name="high", priority=0)
    assert fair.claim("worker")["task_id"] == low["task_id"]
    assert fair.claim("worker") is None
    fair.succeed(low["task_id"], "worker", {"ok": True})
    assert fair.claim("worker")["task_id"] == high["task_id"]


def test_a20_fifo_duplicate_delivery_and_restart() -> None:
    clock, book = ledger(max_running=10)
    created = [
        make(book, auto_queue=True, name=f"fifo-{index}", priority=50) for index in range(10)
    ]
    claimed = [book.claim("worker")["task_id"] for _ in range(10)]
    assert claimed == [row["task_id"] for row in created]
    for task_id in claimed:
        book.succeed(task_id, "worker", {"ok": True})
    _clock, capacity = ledger(max_running=5)
    queued = [make(capacity, auto_queue=True, name=str(index)) for index in range(20)]
    running = []
    while True:
        row = capacity.claim("worker")
        if row is None:
            break
        running.append(row["task_id"])
    assert len(running) == 5
    assert len(queued) == 20
    again = capacity.claim_message(running[0], "other", "msg-1")
    assert again["attempt_count"] == 1
    repeat = capacity.claim_message(running[0], "other", "msg-1")
    assert repeat["attempt_count"] == 1
    snapshot = capacity.dump()
    clock.advance(5)
    revived = TaskLedger(now=clock, max_running=5)
    revived.load(snapshot)
    revived.start()
    assert len(revived.list_tenant("tenant-a")) == 20
    alien = make(capacity, tenant_id="tenant-b", user_id="user-b", auto_queue=True)
    assert {row["tenant_id"] for row in capacity.list_tenant("tenant-a")} == {"tenant-a"}
    with pytest.raises(TaskLifecycleError):
        capacity.read(alien["task_id"], tenant_id="tenant-a")


def test_a21_execution_binding_progress_and_single_claim() -> None:
    clock, book = ledger(max_running=20, lease_seconds=30)
    task = run_one(book)
    assert task["status"] == "running"
    assert task["worker_id"] == "worker-1"
    assert task["started_at"]
    assert task["payload"]["action"] == "reconcile"
    updated = book.report_progress(task["task_id"], "worker-1", progress=40, checkpoint={"step": 1})
    assert updated["progress"] == 40
    clock.advance(2)
    heartbeat = book.heartbeat(task["task_id"], "worker-1")
    assert heartbeat["heartbeat_at"] != task["heartbeat_at"]
    done = book.succeed(task["task_id"], "worker-1", {"rows": 3})
    assert done["result"] == {"rows": 3}
    assert "running" in {event["to"] for event in done["events"]}
    assert book.scheduler_status(task["task_id"]) == book.ui_status(task["task_id"]) == "succeeded"
    _clock, parallel = ledger(max_running=20)
    tasks = [run_one(parallel, name=f"p{index}") for index in range(20)]
    # run_one always claims worker-1; recreate with distinct claims.
    del tasks
    _clock, parallel = ledger(max_running=20)
    queued = [make(parallel, auto_queue=True, name=str(index)) for index in range(20)]
    claimed = []
    for index in range(20):
        row = parallel.claim(f"worker-{index}")
        assert row is not None
        claimed.append(row)
    barrier = threading.Barrier(20)

    def _finish(row: dict, worker: str) -> None:
        barrier.wait()
        parallel.succeed(row["task_id"], worker, {"worker": worker})

    threads = [
        threading.Thread(target=_finish, args=(row, f"worker-{index}"))
        for index, row in enumerate(claimed)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert {parallel.get(row["task_id"])["result"]["worker"] for row in queued} == {
        f"worker-{index}" for index in range(20)
    }
    hidden = make(parallel, tenant_id="tenant-z", user_id="user-z", employee_id="employee-z")
    with pytest.raises(TaskLifecycleError):
        parallel.read(hidden["task_id"], tenant_id="tenant-a")
    with pytest.raises(TaskLifecycleError):
        parallel.call_tool(claimed[0]["task_id"], "worker-0", "payroll")
    _clock, race = ledger(max_running=1)
    make(race, auto_queue=True)
    winners: list[str] = []
    barrier = threading.Barrier(2)

    def _claim(worker: str) -> None:
        barrier.wait()
        row = race.claim(worker)
        if row is not None:
            winners.append(worker)

    threads = [threading.Thread(target=_claim, args=(worker,)) for worker in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(winners) == 1


def test_a22_a23_a24_approval_gate() -> None:
    clock, book = ledger(approval_timeout_seconds=30, max_attempts=1)
    task = run_one(book)
    book.report_progress(task["task_id"], "worker-1", progress=25, checkpoint={"step": "draft"})
    waiting = book.request_approval(task["task_id"], "worker-1", summary="导出工资", risk="high")
    assert waiting["status"] == "waiting_approval"
    assert waiting["approval_id"]
    approval = waiting["approvals"][-1]
    assert approval["task_id"] == waiting["task_id"]
    assert approval["summary"] == "导出工资" and approval["risk"] == "high"
    with pytest.raises(TaskLifecycleError):
        book.begin_effect(waiting["task_id"], "worker-1", "export")
    with pytest.raises(TaskLifecycleError) as denied:
        book.approve(waiting["task_id"], actor="stranger")
    assert denied.value.code == "permission_denied"
    clock.advance(10)
    assert book.tick() == []
    assert book.get(waiting["task_id"])["status"] == "waiting_approval"
    snapshot = book.dump()
    revived = TaskLedger(now=clock, approvers={"boss"}, approval_timeout_seconds=30)
    revived.load(snapshot)
    revived.start()
    assert revived.get(waiting["task_id"])["status"] == "waiting_approval"
    approved = book.approve(waiting["task_id"], actor="boss")
    again = book.approve(waiting["task_id"], actor="boss")
    assert approved["task_id"] == waiting["task_id"] == again["task_id"]
    assert approved["status"] == "queued"
    assert approved["checkpoint"]["step"] == "draft"
    assert approved["payload"] == waiting["payload"]
    assert again["attempt_count"] == approved["attempt_count"]
    resumed = book.claim("worker-2")
    assert resumed is not None and resumed["task_id"] == waiting["task_id"]
    assert resumed["progress"] == 25
    failed = book.fail(
        resumed["task_id"],
        "worker-2",
        code="network_down",
        kind="system",
        message="下游不可用",
        stage="export",
    )
    assert failed["status"] == "failed"
    other = run_one(book, name="超时审批")
    book.request_approval(other["task_id"], "worker-1", summary="付款", risk="high")
    clock.advance(31)
    assert book.tick()
    timed = book.get(other["task_id"])
    assert timed["status"] == "rejected"
    assert timed["error"]["code"] == "approval_timeout"
    rejected = run_one(book, name="拒绝")
    book.request_approval(rejected["task_id"], "worker-1", summary="删库", risk="high")
    first = book.reject(rejected["task_id"], actor="boss", reason="超出权限")
    second = book.reject(rejected["task_id"], actor="boss", reason="超出权限")
    assert first["status"] == "rejected"
    assert len(second["events"]) == len(first["events"])
    assert first["error"]["message"] == "超出权限"
    with pytest.raises(TaskLifecycleError):
        book.call_tool(rejected["task_id"], "worker-1", "excel")
    with pytest.raises(TaskLifecycleError):
        book.mutate_payload(rejected["task_id"], actor="user-a", payload={"action": "bypass"})
    with pytest.raises(TaskLifecycleError):
        book.fail(
            rejected["task_id"],
            "worker-1",
            code="network_down",
            kind="system",
            message="retry",
            stage="tool",
        )
    with pytest.raises(TaskLifecycleError):
        book.reject(rejected["task_id"], actor="user-a", reason="改结果")
    decision = first["approvals"][-1]
    assert (
        decision["actor"] == "boss" and decision["reason"] == "超出权限" and decision["decided_at"]
    )


def test_a23_concurrent_approve_is_single() -> None:
    _clock, book = ledger()
    task = run_one(book)
    book.request_approval(task["task_id"], "worker-1", summary="双人", risk="low")
    results: list[str] = []
    barrier = threading.Barrier(2)

    def _approve() -> None:
        barrier.wait()
        row = book.approve(task["task_id"], actor="boss")
        results.append(row["approvals"][-1]["status"])

    threads = [threading.Thread(target=_approve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == ["approved", "approved"]
    assert book.get(task["task_id"])["status"] == "queued"


def test_a25_success_is_durable_and_terminal() -> None:
    clock, book = ledger()
    task = run_one(book)
    book.write_file(task["task_id"], "worker-1", "out.csv", "a,b\n1,2\n")
    done = book.succeed(task["task_id"], "worker-1", {"total": 1})
    assert done["status"] == "succeeded" and done["completed_at"]
    assert book.read_file(task["task_id"], "tenant-a", "out.csv") == "a,b\n1,2\n"
    assert done["completion_events"] == 1
    assert done["notifications"][0]["task_id"] == task["task_id"]
    again = book.succeed(task["task_id"], "worker-1", {"total": 9})
    assert again["result"] == {"total": 1}
    assert again["completion_events"] == 1
    clock.advance(3)
    revived = TaskLedger(now=clock)
    revived.load(book.dump())
    revived.start()
    assert revived.get(task["task_id"])["status"] == "succeeded"
    with pytest.raises(TaskLifecycleError):
        revived.cancel(task["task_id"], actor="user-a", reason="回滚")
    assert not transition_allowed("succeeded", "running")


def test_a26_failure_classification_and_retry_limits() -> None:
    _clock, book = ledger(max_attempts=1)
    task = run_one(book)
    failed = book.fail(
        task["task_id"],
        "worker-1",
        code="tool_explode",
        kind="system",
        message="工具异常",
        stage="tool",
    )
    assert failed["status"] == "failed"
    assert failed["error"]["stage"] == "tool"
    assert any(event["to"] == "failed" for event in failed["events"])
    business = run_one(book, name="业务")
    business_failed = book.fail(
        business["task_id"],
        "worker-1",
        code="business_rule",
        kind="business",
        message="余额不足",
        stage="validate",
    )
    assert business_failed["error"]["kind"] == "business"
    denied = run_one(book, name="权限", max_attempts=3)
    stuck = book.fail(
        denied["task_id"],
        "worker-1",
        code="permission_denied",
        kind="system",
        message="无权限",
        stage="tool",
    )
    assert stuck["status"] == "failed"
    assert stuck["attempt_count"] == 1


def test_a27_timeout_isolates_late_results() -> None:
    clock, book = ledger(max_running=5, lease_seconds=60)
    parent = run_one(book, name="parent", timeout_seconds=10)
    child = book.add_child(
        parent["task_id"],
        tenant_id="tenant-a",
        user_id="user-a",
        employee_id="employee-a",
        source_type="agent",
        name="child",
        payload={"action": "child"},
        auto_queue=True,
    )
    claimed_child = book.claim("worker-child")
    assert claimed_child is not None and claimed_child["task_id"] == child["task_id"]
    book.begin_effect(parent["task_id"], "worker-1", "hold")
    clock.advance(20)
    changed = book.tick()
    assert parent["task_id"] in changed
    timed = book.get(parent["task_id"])
    assert timed["status"] == "timed_out"
    assert timed["needs_verification"] is True
    assert book.get(child["task_id"])["status"] == "cancelled"
    assert book.scheduler_status(parent["task_id"]) != "running"
    with pytest.raises(TaskLifecycleError):
        book.succeed(parent["task_id"], "worker-1", {"late": True})
    assert book.get(parent["task_id"])["result"] is None
    with pytest.raises(TaskLifecycleError):
        book.retry(parent["task_id"])
    clean = run_one(book, name="clean-timeout", timeout_seconds=10, max_attempts=3)
    clock.advance(11)
    book.tick()
    assert book.get(clean["task_id"])["status"] == "timed_out"
    retried = book.retry(clean["task_id"])
    assert retried["status"] == "queued"
    assert retried["next_retry_at"]


def test_a27_completion_and_timeout_have_one_winner() -> None:
    clock, book = ledger(lease_seconds=60)
    task = run_one(book, timeout_seconds=10)
    clock.advance(10)
    barrier = threading.Barrier(2)
    errors: list[str] = []

    def _finish() -> None:
        barrier.wait()
        try:
            book.succeed(task["task_id"], "worker-1", {"ok": True})
        except TaskLifecycleError as exc:
            errors.append(exc.code)

    def _expire() -> None:
        barrier.wait()
        book.tick()

    threads = [threading.Thread(target=_finish), threading.Thread(target=_expire)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    final = book.get(task["task_id"])
    assert final["status"] in {"succeeded", "timed_out"}
    if final["status"] == "succeeded":
        assert final["result"] == {"ok": True}
    else:
        assert final["result"] is None
        assert errors


def test_a28_cancel_is_terminal_for_queue_run_and_approval() -> None:
    _clock, book = ledger()
    queued = make(book, auto_queue=True, name="queued")
    cancelled = book.cancel(queued["task_id"], actor="user-a", reason="不需要了")
    assert cancelled["status"] == "cancelled"
    assert book.claim("worker") is None or book.claim("worker")["task_id"] != queued["task_id"]
    running = run_one(book, name="running")
    book.cancel(running["task_id"], actor="admin", reason="停止")
    with pytest.raises(TaskLifecycleError):
        book.call_tool(running["task_id"], "worker-1", "excel")
    waiting = run_one(book, name="waiting")
    book.request_approval(waiting["task_id"], "worker-1", summary="等", risk="low")
    book.cancel(waiting["task_id"], actor="user-a", reason="撤回")
    assert book.get(waiting["task_id"])["status"] == "cancelled"
    parent = run_one(book, name="parent")
    child = book.add_child(
        parent["task_id"],
        tenant_id="tenant-a",
        user_id="user-a",
        employee_id="employee-a",
        source_type="ticket",
        name="sub",
        payload={"action": "sub"},
        auto_queue=True,
    )
    book.cancel(parent["task_id"], actor="user-a", reason="整单取消")
    assert book.get(child["task_id"])["status"] == "cancelled"
    before = book.get(parent["task_id"])["files"]
    with pytest.raises(TaskLifecycleError):
        book.write_file(parent["task_id"], "worker-1", "late.txt", "nope")
    assert book.get(parent["task_id"])["files"] == before
    repeated = book.cancel(parent["task_id"], actor="user-a", reason="整单取消")
    assert repeated["version"] == book.get(parent["task_id"])["version"]
    with pytest.raises(TaskLifecycleError) as forbidden:
        book.cancel(queued["task_id"], actor="stranger", reason="越权")
    assert forbidden.value.code == "permission_denied"
    record = book.get(queued["task_id"])
    assert record["cancel_reason"] == "不需要了"
    assert any(
        event["actor"] == "user-a" and event["to"] == "cancelled" for event in record["events"]
    )


def test_a29_restart_classifies_without_replaying_effects() -> None:
    clock, book = ledger(lease_seconds=5, max_attempts=3)
    queued = make(book, auto_queue=True, name="queued")
    safe = run_one(book, name="safe")
    book.finish_effect(safe["task_id"], "worker-1", "posted")
    uncertain = run_one(book, name="uncertain")
    book.begin_effect(uncertain["task_id"], "worker-1", "charge")
    waiting = run_one(book, name="approval")
    book.request_approval(waiting["task_id"], "worker-1", summary="批", risk="low")
    done = run_one(book, name="done")
    book.succeed(done["task_id"], "worker-1", {"ok": True})
    broken = run_one(book, name="broken", max_attempts=1)
    book.fail(
        broken["task_id"], "worker-1", code="disk", kind="system", message="磁盘", stage="write"
    )
    snapshot = book.dump()
    clock.advance(1)
    revived = TaskLedger(now=clock, approvers={"boss"}, lease_seconds=5)
    revived.load(snapshot)
    recovered = revived.start()
    assert queued["task_id"] not in recovered
    assert revived.get(queued["task_id"])["status"] == "queued"
    assert revived.claim("worker")["task_id"] == queued["task_id"]
    assert safe["task_id"] in recovered
    assert revived.get(safe["task_id"])["status"] == "queued"
    assert revived.get(safe["task_id"])["applied_effects"] == ["posted"]
    assert revived.get(uncertain["task_id"])["needs_verification"] is True
    assert revived.get(uncertain["task_id"])["status"] == "running"
    assert "charge" not in revived.get(uncertain["task_id"])["applied_effects"]
    assert revived.get(waiting["task_id"])["status"] == "waiting_approval"
    assert revived.get(done["task_id"])["status"] == "succeeded"
    assert revived.get(broken["task_id"])["status"] == "failed"
    assert any(
        event["reason"] == "lease_reclaimed" for event in revived.get(safe["task_id"])["events"]
    )
    for _ in range(10):
        revived.start()
    assert revived.get(done["task_id"])["applied_effects"] == []
    assert revived.get(safe["task_id"])["applied_effects"] == ["posted"]
    assert revived.scheduler_status(done["task_id"]) == revived.get(done["task_id"])["status"]


def test_a30_idempotency_holds_under_replay() -> None:
    clock, book = ledger(idempotency_ttl_seconds=60, max_attempts=3)
    first = make(book, idempotency_key="same", auto_queue=True)
    for _ in range(99):
        again = make(book, idempotency_key="same", auto_queue=True)
        assert again["task_id"] == first["task_id"]
    distinct = [
        make(book, idempotency_key=f"other-{index}", name=f"n{index}")["task_id"]
        for index in range(100)
    ]
    assert len(set(distinct)) == 100
    claimed = book.claim("worker")
    assert claimed is not None
    for index in range(10):
        book.claim_message(claimed["task_id"], "worker", "delivery-1")
    assert book.get(claimed["task_id"])["attempt_count"] == 1
    book.finish_effect(claimed["task_id"], "worker", "invoice")
    book.fail(
        claimed["task_id"],
        "worker",
        code="network_down",
        kind="system",
        message="超时后重提",
        stage="http",
    )
    clock.advance(2)
    replay = book.claim("worker")
    assert replay is not None and replay["task_id"] == first["task_id"]
    assert book.begin_effect(replay["task_id"], "worker", "invoice") == "applied"
    clock.advance(61)
    fresh = make(book, idempotency_key="same", name="对账")
    assert fresh["task_id"] != first["task_id"]
    done = run_one(book, name="terminal-idem")
    book.succeed(done["task_id"], "worker-1", {"ok": True})
    book.succeed(done["task_id"], "worker-1", {"ok": False})
    assert book.get(done["task_id"])["result"] == {"ok": True}


def test_a30_concurrent_same_key_creates_one_task() -> None:
    _clock, book = ledger()
    found: list[str] = []
    barrier = threading.Barrier(100)

    def _create() -> None:
        barrier.wait()
        found.append(make(book, idempotency_key="shared")["task_id"])

    threads = [threading.Thread(target=_create) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(found)) == 1


def test_retry_backoff_jitter_and_cancel_during_wait() -> None:
    assert retry_delay_seconds(1) == 1
    assert retry_delay_seconds(2) == 2
    assert retry_delay_seconds(3) == 4
    assert retry_delay_seconds(20) == 30
    clock, book = ledger(max_attempts=4, jitter_ratio=0.2, lease_seconds=60)
    delays: list[float] = []
    task = run_one(book, name="backoff", max_attempts=4)
    previous = clock.moment
    for _ in range(3):
        failed = book.fail(
            task["task_id"],
            book.get(task["task_id"])["worker_id"],
            code="network_down",
            kind="system",
            message="暂时失败",
            stage="http",
        )
        assert failed["status"] == "queued"
        delays.append((datetime.fromisoformat(failed["next_retry_at"]) - previous).total_seconds())
        clock.advance(delays[-1])
        claimed = book.claim("worker-1")
        assert claimed is not None
        task = claimed
        previous = clock.moment
    assert delays[0] < delays[1] < delays[2]
    assert delays[-1] <= 30 * 1.2
    _clock, crowd = ledger(max_attempts=2, jitter_ratio=0.2)
    moments: set[str] = set()
    for index in range(100):
        row = run_one(crowd, name=f"j-{index}", max_attempts=2)
        failed = crowd.fail(
            row["task_id"],
            "worker-1",
            code="network_down",
            kind="system",
            message="抖动",
            stage="http",
        )
        moments.add(failed["next_retry_at"])
    assert len(moments) > 1
    waiting = run_one(book, name="cancel-retry", max_attempts=3)
    queued = book.fail(
        waiting["task_id"],
        "worker-1",
        code="network_down",
        kind="system",
        message="等重试",
        stage="http",
    )
    book.cancel(queued["task_id"], actor="user-a", reason="停止重试")
    clock.advance(30)
    assert book.get(queued["task_id"])["status"] == "cancelled"
    held = run_one(book, name="held-retry", max_attempts=3)
    held_fail = book.fail(
        held["task_id"],
        "worker-1",
        code="network_down",
        kind="system",
        message="重启前仍在退避",
        stage="http",
    )
    snapshot = book.dump()
    restored = TaskLedger(now=clock, max_attempts=4)
    restored.load(snapshot)
    restored.start()
    assert restored.get(waiting["task_id"])["status"] == "cancelled"
    assert restored.get(held["task_id"])["next_retry_at"] == held_fail["next_retry_at"]
    assert restored.get(held["task_id"])["status"] == "queued"


def test_retry_exhaustion_and_concurrent_retry_event() -> None:
    clock, book = ledger(max_attempts=3, jitter_ratio=0, lease_seconds=60)
    task = run_one(book, name="exhaust", max_attempts=3)
    worker = "worker-1"
    for expected in (1, 2):
        row = book.fail(
            task["task_id"],
            worker,
            code="network_down",
            kind="system",
            message="失败",
            stage="http",
        )
        assert row["status"] == "queued"
        assert row["attempt_count"] == expected
        clock.advance(30)
        claimed = book.claim(worker)
        assert claimed is not None
        task = claimed
    final = book.fail(
        task["task_id"],
        worker,
        code="network_down",
        kind="system",
        message="耗尽",
        stage="http",
    )
    assert final["status"] == "failed"
    assert final["attempt_count"] == 3
    assert len({item["attempt_id"] for item in final["attempts"]}) == 3
    third = run_one(book, name="third-time", max_attempts=3)
    for _ in range(2):
        book.fail(
            third["task_id"],
            "worker-1",
            code="network_down",
            kind="system",
            message="再试",
            stage="http",
        )
        clock.advance(30)
        assert book.claim("worker-1")["task_id"] == third["task_id"]
    done = book.succeed(third["task_id"], "worker-1", {"ok": True})
    assert done["status"] == "succeeded"
    assert [item["status"] for item in done["attempts"]] == ["failed", "failed", "succeeded"]
    timed = run_one(book, name="one-retry", timeout_seconds=1, max_attempts=3)
    clock.advance(2)
    book.tick()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def _retry() -> None:
        barrier.wait()
        try:
            outcomes.append(book.retry(timed["task_id"])["status"])
        except TaskLifecycleError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=_retry) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("queued") == 1
    assert book.get(timed["task_id"])["status"] == "queued"
