"""C21–C30 网络与服务稳定性契约。用可控时钟和假任务，不依赖真实断网。"""

from __future__ import annotations

import threading

import pytest

from app.application.network_stability import (
    FAILURE_NOTICES,
    CapacityError,
    DuplicateSideEffect,
    InFlightLedger,
    LanePool,
    RefreshSingleFlight,
    SseHub,
    TraceLog,
    failure_payload,
    format_http_trace_line,
    timeout_outcome,
)
from app.security.log_redaction import redact_log_text


def test_outage_keeps_completed_work_and_does_not_mark_open_work_successful():
    ledger = InFlightLedger()
    for cycle in range(10):
        done = ledger.begin(f"done-{cycle}", kind="chat")
        ledger.complete(done["id"], {"text": f"reply-{cycle}"})
        tool = ledger.begin(f"tool-{cycle}", side_effect=True, idempotency_key=f"tool-key-{cycle}", kind="tool")
        ledger.complete(tool["id"], {"applied": True})
        open_task = ledger.begin(f"open-{cycle}", side_effect=True, idempotency_key=f"open-key-{cycle}", kind="erp")
        interrupted = ledger.interrupt_open("backend_restart")
        assert interrupted == [open_task["id"]]
        assert ledger.tasks[done["id"]]["success"] is True
        assert ledger.tasks[tool["id"]]["success"] is True
        assert ledger.tasks[open_task["id"]]["success"] is False
        assert ledger.tasks[open_task["id"]]["state"] == "interrupted"
        with pytest.raises(DuplicateSideEffect):
            ledger.begin(f"replay-{cycle}", side_effect=True, idempotency_key=f"open-key-{cycle}", kind="erp")
        replay = ledger.begin(f"replay-tool-{cycle}", side_effect=True, idempotency_key=f"tool-key-{cycle}", kind="tool")
        assert replay["id"] == tool["id"]
        assert replay["success"] is True


def test_failure_notices_are_distinct_and_never_successful():
    messages = set()
    for kind in FAILURE_NOTICES:
        payload = failure_payload(kind)
        assert payload["success"] is False
        assert payload["message"] not in messages
        messages.add(payload["message"])
        assert "Traceback" not in payload["message"]
        assert payload["action"] in {"retry", "relogin", "admin", "check_result"}
    assert "重新登录" in failure_payload("token_expired")["message"]
    assert failure_payload("token_expired")["message"] != failure_payload("offline")["message"]
    assert "管理员" in failure_payload("permission")["message"]
    assert "超时" in failure_payload("timeout")["message"]
    assert "成功" not in failure_payload("timeout")["message"] or "未成功" in failure_payload("timeout")["message"]


def test_refresh_is_single_flight_and_failure_is_not_a_network_error():
    gate = RefreshSingleFlight()
    calls = {"n": 0}
    release = threading.Event()

    def refresh() -> bool:
        calls["n"] += 1
        assert release.wait(timeout=2)
        return True

    results: list[bool] = []
    entered: list[int] = []

    def worker() -> None:
        entered.append(1)
        results.append(gate.run(refresh))

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    while len(entered) < 12:
        threading.Event().wait(0.005)
    threading.Event().wait(0.05)
    assert calls["n"] == 1
    release.set()
    for thread in threads:
        thread.join(timeout=2)
    assert calls["n"] == 1
    assert results == [True] * 12

    failed = RefreshSingleFlight()

    def deny() -> bool:
        raise RuntimeError("refresh token rejected")

    assert failed.run(deny) is False
    assert failure_payload("token_expired")["action"] == "relogin"


def test_accelerated_sse_soak_bounds_reconnects_and_releases_connections():
    hub = SseHub(heartbeat_s=15, max_reconnects=8)
    hub.open("c1", now=0)
    blips = 0
    # 2 小时按 15 秒心跳快进，不占用真实两小时。
    for second in range(0, 7200 + 1, 15):
        hub.heartbeat("c1", second)
        if second and second % 600 == 0:
            if hub.blip("c1", second):
                blips += 1
            else:
                assert hub.blip("c1", second) is False
    assert blips == 8
    assert hub.conns["c1"]["reconnects"] == 8
    assert hub.live_count() == 1
    assert len(hub.conns["c1"]) == 4
    hub.close("c1")
    assert hub.live_count() == 0


@pytest.mark.parametrize("operation,elapsed,hung,ok", [
    ("health", 3, False, True),
    ("health", 3.1, False, False),
    ("erp_read", 10, False, True),
    ("erp_read", 10.1, False, False),
    ("chat", 30, False, True),
    ("chat", 30.1, False, False),
    ("tool", 1, True, False),
    ("upload", 1, True, False),
    ("download", 1, True, False),
])
def test_timeout_budgets_are_not_success(operation, elapsed, hung, ok):
    outcome = timeout_outcome(operation, elapsed, hung=hung)
    assert outcome["success"] is ok
    if not ok:
        assert outcome["state"] == "timeout"


def test_slow_lane_does_not_block_other_lanes_or_grow_without_limit():
    pool = LanePool({"chat": 4, "erp": 1, "tool": 2})
    release = threading.Event()
    entered = threading.Event()

    def slow():
        entered.set()
        assert release.wait(timeout=2)
        return "erp"

    worker = threading.Thread(target=lambda: pool.run("erp", slow))
    worker.start()
    assert entered.wait(timeout=2)
    assert pool.run("chat", lambda: "chat") == "chat"
    with pytest.raises(CapacityError):
        pool.run("erp", lambda: "again", queue_limit=1)
    release.set()
    worker.join(timeout=2)


def test_trace_line_correlates_ids_and_redacts_secrets():
    log = TraceLog()
    row = log.start(
        request_id="req-12345678",
        user="42",
        tenant="acme",
        session_ref="abcd1234",
        task="task-1",
        detail="password=super-secret Authorization: Bearer abc.def.ghi",
    )
    log.finish(row, status=504, error_code="timeout")
    rendered = log.render()
    assert "req-12345678" in rendered
    assert "timeout" in rendered
    assert "duration_ms=" in rendered
    assert "super-secret" not in rendered
    assert "abc.def.ghi" not in rendered
    assert "acme" in rendered
    line = format_http_trace_line(
        request_id="req-12345678",
        method="POST",
        path="/api/erp/orders?token=secret-value",
        status=500,
        duration_ms=12.2,
        error_code="db_down",
        tenant="acme",
        user="42",
        task="task-1",
        session_ref="abcd1234",
    )
    assert "token=secret-value" not in line
    assert "path=/api/erp/orders" in line
    assert "db_down" in line
    assert "password=hunter2" not in redact_log_text("password=hunter2")
