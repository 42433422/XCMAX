"""SQL tombstones and OS locks survive real worker boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from app.application.ai_chat import dialogue_memory as memory
from app.application.ai_chat.active_conversation import (
    active_conversation_for,
    remember_active_conversation,
)
from app.application.task_conversation_store import task_conversation_store as store
from app.db.models import AIConversation, AIConversationSession
from app.domain.shared_services.conversation_service import ConversationRevisionError


@pytest.fixture
def runtime(dialogue_db, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "memory"))
    return dialogue_db, tmp_path


def _context(session="shared", turn="first"):
    return {"local_user_id": 1, "tenant_id": 1, "conversation_id": session, "turn_id": turn}


def _start_worker(tmp_path, turn="late"):
    marker = tmp_path / f"{turn}.ready"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import json, sys, time
from pathlib import Path
from app.application.ai_chat import dialogue_memory as memory
from app.application.ai_chat.active_conversation import remember_active_conversation
from app.application.task_conversation_store import task_conversation_store as store
context = json.loads(sys.argv[1])
message = 'message-' + context['turn_id']
assert memory.prepare_chat_turn(message, context) is None
Path(sys.argv[2]).write_text(json.dumps(context))
sys.stdin.readline()
write = memory._write
def delayed_write(key, data):
    time.sleep(0.2)
    write(key, data)
memory._write = delayed_write
result = {}
for name, callback in (
    ('sql', lambda: store.save_message(session_id=context['conversation_id'], user_id=1,
        role='assistant', content='late-result', expected_revision=context['_conversation_revision'])),
    ('file', lambda: memory.settle_chat_turn(message, context, {'response': 'late-result'}, 'completed')),
):
    try:
        callback()
        result[name] = 'saved'
    except Exception as exc:
        result[name] = type(exc).__name__
remember_active_conversation(context)
print(json.dumps(result))
""",
            json.dumps(_context(turn=turn)),
            str(marker),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 20
    while not marker.is_file() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not marker.is_file():
        process.kill()
        raise AssertionError(process.communicate(timeout=5))
    return process, json.loads(marker.read_text())


@pytest.mark.parametrize("action", ["delete", "clear"])
def test_delete_fences_live_first_turn_sql_file_and_active_pointer(runtime, action):
    factory, tmp_path = runtime
    worker, context = _start_worker(tmp_path)
    try:
        remember_active_conversation(context)
        assert active_conversation_for(1, tenant_id="1") == "shared"
        if action == "delete":
            assert store.delete_session(session_id="shared", user_id=1)
        else:
            assert store.clear_sessions(user_id=1) == 1
        out, err = worker.communicate("finish\n", timeout=30)
        assert worker.returncode == 0, err
        assert json.loads(out) == {
            "sql": "ConversationRevisionError",
            "file": "ConversationRevisionError",
        }
        assert active_conversation_for(1, tenant_id="1") == ""
        assert memory._read(memory.conversation_key(context))["turns"] == []
        with pytest.raises(ConversationRevisionError):
            memory.prepare_chat_turn("reopen deleted id", _context(turn="new"))
        with factory() as db:
            session = db.query(AIConversationSession).one()
            assert session.deleted_at is not None and session.revision == 1
            assert db.query(AIConversation).count() == 0
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=5)


def test_withdraw_rebuilds_only_surviving_sql_and_rejects_late_completion(runtime):
    _, tmp_path = runtime
    for turn, content in (("keep", "confirmed surviving fact"), ("remove", "withdrawn secret")):
        context = _context(turn=turn)
        memory.prepare_chat_turn(content, context)
        user_id = store.save_message(session_id="shared", user_id=1, role="user", content=content)
        store.save_message(
            session_id="shared", user_id=1, role="assistant", content=f"reply-{turn}"
        )
        memory.settle_chat_turn(content, context, {"response": f"reply-{turn}"}, "completed")
    worker, old_context = _start_worker(tmp_path)
    try:
        assert store.delete_messages_from(session_id="shared", user_id=1, message_id=user_id) == 2
        out, err = worker.communicate("finish\n", timeout=30)
        assert worker.returncode == 0, err
        assert set(json.loads(out).values()) == {"ConversationRevisionError"}
        with pytest.raises(ConversationRevisionError):
            store.save_message(
                session_id="shared",
                user_id=1,
                role="user",
                content="old UI copy",
                expected_revision=0,
            )
        current = _context(turn="next")
        memory.prepare_chat_turn("continue", current)
        assert current["_conversation_revision"] == 1
        restored = memory._read(memory.conversation_key(current), current)
        text = json.dumps(restored)
        assert "confirmed surviving fact" in text
        assert "withdrawn secret" not in text and "message-late" not in text
        with pytest.raises(ConversationRevisionError):
            memory._read(memory.conversation_key(old_context), old_context)
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=5)


def test_two_live_workers_keep_both_turns_without_false_abandonment(runtime):
    _, tmp_path = runtime
    first, first_context = _start_worker(tmp_path, "a")
    second = None
    try:
        second, _ = _start_worker(tmp_path, "b")
        key = memory.conversation_key(first_context)
        assert memory.turn_status(key, "a") == "processing"
        assert memory.turn_status(key, "b") == "processing"
        for worker in (second, first):
            worker.stdin.write("finish\n")
            worker.stdin.flush()
        for worker in (second, first):
            out, err = worker.communicate(timeout=30)
            assert worker.returncode == 0, err
            assert set(json.loads(out).values()) == {"saved"}
        data = memory._read(key)
        assert {row["turn_id"] for row in data["turns"]} == {"a", "b"}
        assert len(data["turns"]) == 4
        assert all(
            row["status"] == "completed" for row in data["turns"] if row["role"] == "assistant"
        )
        assert set(data["receipts"]) == {"a", "b"}
    finally:
        for worker in (first, second):
            if worker is not None and worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=5)


def test_worker_death_releases_turn_lock_and_next_request_marks_interrupted(runtime):
    _, tmp_path = runtime
    worker, context = _start_worker(tmp_path)
    worker.kill()
    worker.communicate(timeout=5)
    memory.prepare_chat_turn("after restart", _context(turn="after"))
    assert memory.turn_status(memory.conversation_key(context), "late") == "interrupted"


def test_failed_history_receipt_keeps_full_text_until_save_only_repair(runtime, monkeypatch):
    monkeypatch.setattr(memory, "_MEMORY_MAX_TURNS", 2)
    context = _context()
    message = "original long input " * 600
    response = "original long result " * 600
    memory.prepare_chat_turn(message, context)
    memory.settle_chat_turn(
        message,
        context,
        {
            "response": response,
            "history_persistence": {"status": "failed", "retry": "save_only"},
        },
        "completed",
    )
    other = _context(turn="next")
    memory.prepare_chat_turn("next", other)
    memory.settle_chat_turn("next", other, {"response": "ok"}, "completed")
    receipt = memory.stored_turn_receipt(context, "first")
    assert receipt["message"] == message and receipt["payload"]["response"] == response
    assert receipt["revision"] == 0
    memory.mark_history_persisted(context, "first", {"status": "saved", "revision": 0})
    assert memory.stored_turn_receipt(context, "first") is None
    store.delete_session(session_id="shared", user_id=1)
    assert memory.stored_turn_receipt(_context(), "next") is None


def test_conflicting_conversation_identifiers_are_rejected_before_registration(runtime):
    factory, _ = runtime
    with pytest.raises(ValueError, match="same conversation"):
        memory.prepare_chat_turn("wrong destination", {**_context(), "session_id": "other"})
    with factory() as db:
        assert db.query(AIConversationSession).count() == 0


@pytest.mark.parametrize(
    "success,approval",
    [
        (True, False),
        (False, False),
        (None, False),
        (None, True),
    ],
)
def test_sql_only_replay_does_not_invent_success(runtime, success, approval):
    metadata = json.dumps(
        {
            "business_harness": {"turn_id": "first", "run_id": "original-run"},
            "summary": {"success": success},
            "ui": {"approvalCard": {"id": "approval"} if approval else None},
        }
    )
    for role, content in (("user", "original"), ("assistant", "original reply")):
        store.save_message(
            session_id="shared", user_id=1, role=role, content=content, metadata=metadata
        )
    replay = memory.prepare_chat_turn("original", _context())
    # Client/legacy SQL metadata has no server-bound tenant and Mod scope.
    assert replay["execution_state"] == "unknown" and replay["run_id"] == "original-run"


def test_history_recovers_original_text_receipt_in_fresh_process(runtime):
    context = _context()
    memory.prepare_chat_turn("原问题", context)
    memory.settle_chat_turn(
        "原问题", context, {"success": True, "response": "重启前的原始回复。"}, "completed"
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
from app.application.task_conversation_store import TaskConversationStore
from app.infrastructure.tenant_scope import tenant_scope
with tenant_scope(1):
    history = TaskConversationStore().get_history(session_id='shared', user_id=1, turn_id='first')
print(json.dumps(history, ensure_ascii=False))
""",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(process.stdout)
    assert result["messages"] == []
    receipt = result["turn_receipt"]
    assert receipt["turn_id"] == "first" and receipt["run_id"] == ""
    assert receipt["receipt_kind"] == "turn" and receipt["durable"] is True
    assert receipt["status"] == "completed" and receipt["message"] == "重启前的原始回复。"
