"""Real spawn regression: observations arrive before the tool can finish."""

import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

import psutil
import pytest

from app.application.agent_orchestrator import tool_process
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import (
    AgentToolExecutor,
    execute_with_tool_deadline,
)
from app.infrastructure.chat_stream_lifetime import (
    StreamLifetime,
    StreamReceiptPersistenceError,
    current_lifetime,
    publish_stream_delta,
    publish_stream_note,
    publish_stream_tool_record,
)


class StreamingExecutor:
    def execute(self, step, *, runtime_context):
        folder = Path(step.params["folder"])
        (folder / "worker").write_text(str(os.getpid()))
        if step.action == "fork":
            child = os.fork()
            if child == 0:
                time.sleep(30)
                os._exit(0)
            (folder / "descendant").write_text(str(child))
        publish_stream_note("正在识别销售明细")
        for delta in ("已读取", " ", "第一行\n"):
            publish_stream_delta(delta)
        record = {"node_id": step.node_id, "tool_id": step.tool_id}
        publish_stream_tool_record({**record, "phase": "started", "action": step.action})
        if step.action == "flood":
            for _ in range(128):  # Bounded burst; still exceeds the pipe buffer.
                publish_stream_note("持续进度" * 8192)
        publish_stream_tool_record(
            {
                **record,
                "phase": "progress",
                "label": "正在写入",
                "progress": 50,
                "processed_rows": 1,
                "total_rows": 2,
            }
        )
        if step.action == "handshake":
            # Finishing depends on receipt in the parent, not on a timing guess.
            while not (folder / "observed").exists():
                time.sleep(0.01)
        (folder / "effect").write_text("committed once")
        if step.action == "exit_without_receipt":
            os._exit(7)
        try:
            publish_stream_tool_record(
                {
                    **record,
                    "phase": "finished",
                    "success": True,
                    "output_preview": "x" * tool_process._STREAM_FRAME_LIMIT
                    if step.action == "oversized"
                    else "committed once",
                }
            )
        except StreamReceiptPersistenceError:
            if step.action != "oversized":
                raise
        return {"success": True, "pid": os.getpid(), "tenant_id": runtime_context["tenant_id"]}


class FileDeadlineExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        from app.application.tool_execution_deadline import remaining_invocation_seconds

        renew = runtime_context["_renew_elt_file_deadline"]
        renew(step.params.get("phase", "preview"))
        time.sleep(step.params["preview_delay"])
        assert remaining_invocation_seconds(1000) > 60
        renew("execute")
        return {"success": True}


class ParentBudgetFileExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        from app.application.tool_execution_deadline import remaining_invocation_seconds

        runtime_context["_renew_elt_file_deadline"]("linked_preview")
        Path(step.params["started"]).write_text(str(remaining_invocation_seconds(1000)))
        time.sleep(20)
        Path(step.params["late"]).write_text("must never happen")
        return {"success": True}


@pytest.fixture(autouse=True)
def no_business_database(monkeypatch):
    # Exercise the real process transport without opening an unrelated customer DB.
    monkeypatch.setattr(tool_process, "_caller_business_db_url", lambda: "")


def run_tool(folder, lifetime, action="handshake", seconds=8):
    token = current_lifetime.set(lifetime)
    try:
        return tool_process.execute_isolated(
            StreamingExecutor(),
            AgentStep("file-1", "fixture", action, params={"folder": str(folder)}),
            {"tenant_id": 7},
            time.monotonic() + seconds,
        )
    finally:
        current_lifetime.reset(token)


@pytest.mark.parametrize("cancel", [False, True])
def test_spawn_forwards_live_events_and_drains_terminal_receipt(tmp_path, cancel):
    lifetime, received, notices = StreamLifetime(), [], []
    settled = threading.Event()

    def interruption(**state):
        notices.append(state)
        if not state["pending"]:
            settled.set()

    def tool(*, sequence, record):
        received.append((sequence, record))
        if record["phase"] == "progress":
            assert not (tmp_path / "effect").exists()
            if cancel:
                lifetime.cancel("consumer_closed")
            (tmp_path / "observed").write_text("received before completion")

    notes, deltas = [], []
    lifetime.observe(interruption)
    lifetime.observe_notes(notes.append)
    lifetime.observe_deltas(deltas.append)
    lifetime.observe_tools(tool)
    before = {child.pid for child in multiprocessing.active_children()}
    result = run_tool(tmp_path, lifetime)
    assert result["success"] is True and result["tenant_id"] == 7
    assert result["pid"] != os.getpid() and not psutil.pid_exists(result["pid"])
    assert {child.pid for child in multiprocessing.active_children()} <= before
    assert notes == ["正在识别销售明细"] and deltas == ["已读取", " ", "第一行\n"]
    assert [sequence for sequence, _ in received] == [1, 2, 3]
    assert [record["phase"] for _, record in received] == ["started", "progress", "finished"]
    assert received[1][1]["processed_rows"] == 1
    assert received[1][1]["progress"] == 50
    assert "action" not in received[1][1]  # Nested progress cannot rename its parent tool.
    assert (tmp_path / "effect").read_text() == "committed once"
    assert current_lifetime.get() is None
    if cancel:
        assert settled.wait(2)
        assert notices[-1] == {"pending": False, "reason": "consumer_closed"}


def test_backpressure_and_blocked_observer_cannot_disable_hard_deadline(tmp_path):
    lifetime = StreamLifetime()
    entered, release, settled = (threading.Event() for _ in range(3))

    def block(_note):
        entered.set()
        lifetime.cancel("consumer_closed")
        release.wait(15)

    lifetime.observe_notes(block)
    lifetime.observe(lambda **state: settled.set() if not state["pending"] else None)
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    try:
        result = run_tool(tmp_path, lifetime, "flood", seconds=4)
        assert entered.is_set(), result
        assert time.monotonic() - started < 6.5
        assert result["outcome"] == "unknown" and result["retryable"] is False
        assert not psutil.pid_exists(int((tmp_path / "worker").read_text()))
        assert not (tmp_path / "effect").exists()
        assert {child.pid for child in multiprocessing.active_children()} <= before
    finally:
        release.set()
    assert settled.wait(2)  # The relay releases ownership after the observer returns.


@pytest.mark.parametrize("failed_phase", ["progress", "finished"])
def test_observation_failure_only_requires_reconciliation_for_terminal_receipts(
    tmp_path, failed_phase
):
    lifetime = StreamLifetime()

    def failed_storage(*, sequence, record):
        if record["phase"] == failed_phase:
            raise OSError("receipt store unavailable")

    lifetime.observe_tools(failed_storage)
    result = run_tool(tmp_path, lifetime, "receipt")
    assert (tmp_path / "effect").read_text() == "committed once"
    if failed_phase == "progress":
        assert result["success"] is True
        assert not lifetime.stopped.is_set()
    else:
        assert result["outcome"] == "unknown" and result["retryable"] is False
        assert result["error_code"] == "tool_stream_receipt_failed"
        assert lifetime.reason == "tool_receipt_persistence_failed"
        result = result["reconciliation_evidence"]
        assert result["success"] is True
    assert not psutil.pid_exists(result["pid"])


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork descriptor inheritance is POSIX-only")
def test_descendant_inheriting_pipe_does_not_delay_a_completed_tool(tmp_path):
    lifetime, records = StreamLifetime(), []
    lifetime.observe_tools(lambda **event: records.append(event["record"]))
    started = time.monotonic()
    result = run_tool(tmp_path, lifetime, "fork")
    assert result["success"] is True and time.monotonic() - started < 6
    assert records[-1]["phase"] == "finished"
    child = int((tmp_path / "descendant").read_text())
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE


def test_oversized_terminal_receipt_does_not_lose_committed_result_evidence(tmp_path):
    result = run_tool(tmp_path, StreamLifetime(), "oversized")
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["error_code"] == "tool_stream_receipt_failed"
    assert result["reconciliation_evidence"]["success"] is True
    assert (tmp_path / "effect").read_text() == "committed once"


def test_eof_without_completion_marker_is_not_a_confirmed_receipt():
    receiver, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
    lifetime = StreamLifetime()
    drained, failed, stopped = (threading.Event() for _ in range(3))
    lifetime.worker_started()
    sender.close()
    tool_process._relay_stream(receiver, lifetime, drained, failed, stopped)
    assert drained.is_set() and failed.is_set()


def test_worker_exit_without_final_receipt_is_detected_before_deadline(tmp_path):
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    result = run_tool(tmp_path, StreamLifetime(), "exit_without_receipt", seconds=15)
    assert time.monotonic() - started < 12
    assert (tmp_path / "effect").read_text() == "committed once"
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["error_code"] == "tool_worker_exited"
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_worker_exit_does_not_discard_buffered_acknowledgement():
    from multiprocessing.connection import wait

    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=sender.send_bytes, args=(b"d",))
    process.start()
    sender.close()
    try:
        assert wait((process.sentinel,), timeout=8)
        assert tool_process._worker_acknowledged(receiver, process, b"d", time.monotonic() + 1) == (
            True,
            True,
        )
    finally:
        receiver.close()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        process.close()


@pytest.mark.parametrize("stage_stalls", [False, True])
@pytest.mark.parametrize(("stage", "marker"), [("preview", b"p"), ("linked_preview", b"l")])
def test_elt_file_deadline_supersedes_startup_and_still_bounds_stalled_stage(
    monkeypatch, stage_stalls, stage, marker
):
    from app.application.agent_orchestrator.tool_timeouts import ELT_FILE_WATCHDOG_SECONDS

    if stage_stalls:
        monkeypatch.setitem(ELT_FILE_WATCHDOG_SECONDS, marker, 0.2)
    # Match the other real-spawn tests: cold worker imports can exceed 3 seconds.
    # The stage must still outlive this initial budget; its own stall cap remains 0.2s.
    startup_seconds = 8
    step = AgentStep(
        "batch",
        "elt_import",
        "execute",
        params={
            "run_id": "child-preview",
            "preview_delay": startup_seconds + 0.1,
            "phase": stage,
        },
    )
    result = execute_with_tool_deadline(
        FileDeadlineExecutor(), step, runtime_context={}, timeout_seconds=startup_seconds
    )
    if stage_stalls:
        assert result["success"] is False
        assert result["outcome"] == "unknown"
        assert result["error_code"] == "tool_result_unknown"
        assert result["reconciliation_evidence"]["error_code"] == "tool_worker_incomplete"
        assert result["retryable"] is False
        assert result["reconciliation_required"] is True
    else:
        assert result == {"success": True}


def test_elt_stage_cannot_extend_trusted_parent_budget_or_write_after_timeout(tmp_path):
    from app.application.tool_execution_deadline import invocation_deadline

    began = time.monotonic()
    step = AgentStep(
        "batch",
        "elt_import",
        "execute",
        params={
            "run_id": "existing-preview",
            "started": str(tmp_path / "started"),
            "late": str(tmp_path / "late"),
        },
    )
    with invocation_deadline(began + 8):
        result = execute_with_tool_deadline(
            ParentBudgetFileExecutor(),
            step,
            runtime_context={"deadline_monotonic": 1e20},
            timeout_seconds=60,
        )
    assert time.monotonic() - began < 12
    assert (tmp_path / "started").is_file(), result
    assert 0 < float((tmp_path / "started").read_text()) <= 8
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert not (tmp_path / "late").exists()


def test_spawned_deltas_keep_whitespace_through_sse_queue_and_final_deduplication(tmp_path):
    from app.fastapi_routes.xcagi_compat_chat_stream import (
        _heartbeats,
        _StreamNoteQueue,
        _token_events,
        _ToolRecordQueue,
    )

    lifetime = StreamLifetime()
    tools, notes, deltas = _ToolRecordQueue(), _StreamNoteQueue(), _StreamNoteQueue()
    lifetime.observe_tools(tools.push)
    lifetime.observe_notes(notes.push)
    lifetime.observe_deltas(deltas.push)
    sink, streamed = {}, []

    def encode(event):
        return json.dumps(event).encode()

    token = current_lifetime.set(lifetime)
    try:
        events = [
            json.loads(event)
            for event in _heartbeats(
                lambda: run_tool(tmp_path, lifetime, "receipt"),
                "执行工具",
                sink,
                encode,
                tools,
                notes,
                deltas,
                streamed,
            )
        ]
    finally:
        current_lifetime.reset(token)
    assert sink["value"]["success"] is True
    assert [event["text"] for event in events if event["type"] == "token"] == [
        "已读取",
        " ",
        "第一行\n",
    ]
    remaining = list(_token_events(encode, "已读取 第一行\n导入完成", already="".join(streamed)))
    assert [json.loads(event)["text"] for event in remaining] == ["导入完成"]


def test_model_activity_reaches_existing_chat_sse():
    from app.fastapi_routes.xcagi_compat_chat_stream import _heartbeats, _StreamNoteQueue

    lifetime = StreamLifetime()
    activity = _StreamNoteQueue()
    lifetime.observe_model_activity(lambda: activity.push("active"))
    sink = {}

    def run():
        lifetime.publish_model_activity()
        return {"success": True}

    events = [
        json.loads(row)
        for row in _heartbeats(
            run,
            "正在处理任务",
            sink,
            lambda event: json.dumps(event).encode(),
            model_activity=activity,
        )
    ]
    assert [row for row in events if row["type"] == "model_activity"] == [
        {"type": "model_activity"}
    ]
