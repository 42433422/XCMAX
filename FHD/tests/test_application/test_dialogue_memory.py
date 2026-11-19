"""The unified model receives bounded, owner-scoped chat history."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.ai_chat.dialogue_memory import (
    conversation_key,
    prepare_chat_turn,
    recent_conversation_messages,
    settle_chat_turn,
    turn_status,
)


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dialogue_db) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    yield tmp_path
    from app.application.ai_chat import dialogue_memory as memory

    for path, held in list(memory._INFLIGHT.items()):
        if Path(held.lock_file).parent == tmp_path:
            held.release()
            memory._INFLIGHT.pop(path, None)


def _context(session: str, turn: str, **extra: object) -> dict[str, object]:
    return {
        "local_user_id": 1,
        "tenant_id": 1,
        "conversation_id": session,
        "turn_id": turn,
        **extra,
    }


def test_business_and_smalltalk_turns_share_the_same_transcript(memory_dir: Path) -> None:
    first = _context("unified", "1")
    assert prepare_chat_turn("查一下客户", first) is None
    settle_chat_turn(
        "查一下客户", first, {"success": True, "response": "找到客户记录。"}, "completed"
    )

    second = _context("unified", "2")
    assert prepare_chat_turn("你好", second) is None
    history = recent_conversation_messages(second)

    assert history == [
        {"role": "user", "content": "查一下客户"},
        {"role": "assistant", "content": "找到客户记录。"},
    ]


def test_same_turn_replays_receipt_and_rejects_changed_message(memory_dir: Path) -> None:
    context = _context("retry", "same")
    text = "查询产品"
    assert prepare_chat_turn(text, context) is None
    payload = {"success": True, "run_id": "run-1", "response": "已查询"}
    settle_chat_turn(text, context, payload, "completed")

    replay = prepare_chat_turn(text, context)
    assert replay["run_id"] == "run-1"
    assert replay["data"]["replay"] is True
    assert prepare_chat_turn("查询其他产品", context)["success"] is False
    assert turn_status(conversation_key(context), "same") == "completed"


def test_settle_with_reused_turn_id_does_not_break_the_turn(memory_dir: Path) -> None:
    from app.application.ai_chat import dialogue_memory as memory

    context = _context("reuse", "1")
    assert prepare_chat_turn("真正的那条消息", context) is None

    # 前端重试复用了同一 turn_id：结算只跳过本次，不抛错也不覆盖原轮次。
    settle_chat_turn("另一条消息", context, {"response": "不应写入"}, "failed")

    assert turn_status(conversation_key(context), "1") == "processing"
    assert recent_conversation_messages(_context("reuse", "2")) == [
        {"role": "user", "content": "真正的那条消息"}
    ]
    assert memory._turn_is_live(conversation_key(context), "1")
    settle_chat_turn("真正的那条消息", context, {"response": "原任务完成"}, "completed")
    assert prepare_chat_turn("真正的那条消息", context)["response"] == "原任务完成"


def test_abandoned_turn_is_not_treated_as_completed(memory_dir: Path) -> None:
    context = _context("half", "open")
    # A real worker exits without settling; the OS must release its turn lock.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json, os, sys
from app.application.ai_chat.dialogue_memory import prepare_chat_turn
assert prepare_chat_turn('查询客户', json.loads(sys.argv[1])) is None
os._exit(0)
""",
            json.dumps(context),
        ],
        check=True,
        timeout=30,
    )
    prepare_chat_turn("下一条消息", _context("half", "next"))
    assert turn_status(conversation_key(context), "open") == "interrupted"


@pytest.mark.parametrize("status", ["waiting_approval", "unknown"])
def test_unfinished_turn_replays_only_the_original_run(memory_dir: Path, status: str) -> None:
    context = _context("pending", "original")
    assert prepare_chat_turn("删除旧记录", context) is None
    waiting = {
        "run_id": "run-original",
        "response": "等待授权" if status == "waiting_approval" else "等待核对",
    }
    settle_chat_turn("删除旧记录", context, waiting, status)

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from app.application.ai_chat.dialogue_memory import prepare_chat_turn; "
            "d=json.load(sys.stdin); print(json.dumps(prepare_chat_turn(d['message'],d['context'])))",
        ],
        input=json.dumps({"message": "删除旧记录", "context": context}),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    replay = json.loads(process.stdout)
    assert replay["run_id"] == "run-original"
    assert replay["execution_state"] == status
    # 另一项执行的结算不再抛错中断整轮，而是跳过并保留原执行的记录。
    settle_chat_turn("删除旧记录", context, {"run_id": "other"}, "completed")
    assert turn_status(conversation_key(context), "original") == status
    assert prepare_chat_turn("删除旧记录", context)["run_id"] == "run-original"


@pytest.mark.parametrize("changed", [{"local_user_id": 2}, {"tenant_id": 2}, {"mod_id": "other"}])
def test_transcript_is_scoped_to_owner_tenant_and_mod(
    memory_dir: Path, changed: dict[str, object]
) -> None:
    original = _context("scope", "1", mod_id="erp")
    assert prepare_chat_turn("只属于当前会话的文字", original) is None
    settle_chat_turn("只属于当前会话的文字", original, {"response": "收到"}, "completed")
    other = {**original, **changed, "turn_id": "2"}

    if "local_user_id" in changed:
        from app.domain.shared_services.conversation_service import ConversationRevisionError

        with pytest.raises(ConversationRevisionError):
            recent_conversation_messages(other)
    else:
        assert recent_conversation_messages(other) == []
    assert conversation_key(original) != conversation_key(other)


def test_transcript_enrichment_preserves_existing_multimodal_turn(memory_dir: Path) -> None:
    from app.application.ai_chat.dialogue_memory import enrich_model_messages

    first = _context("enrich", "1")
    prepare_chat_turn("查一下客户", first)
    settle_chat_turn("查一下客户", first, {"response": "客户已查到"}, "completed")
    second = _context("enrich", "2")
    prepare_chat_turn("分析这个图片", second)
    current = {"role": "user", "content": [{"type": "text", "text": "分析这个图片"}]}
    original = [{"role": "system", "content": "Existing tool safety rules"}, current]

    enriched = enrich_model_messages(original, "分析这个图片", second)

    assert enriched[0] == original[0]
    assert enriched[-1] is current
    assert {"role": "user", "content": "查一下客户"} in enriched
    assert {"role": "assistant", "content": "客户已查到"} in enriched
    assert original == [{"role": "system", "content": "Existing tool safety rules"}, current]


def test_anonymous_conversations_do_not_share_persisted_transcripts(memory_dir: Path) -> None:
    context = {"conversation_id": "anonymous", "turn_id": "1"}
    assert prepare_chat_turn("私有内容", context) is None
    assert recent_conversation_messages(context) == []
    assert list(memory_dir.iterdir()) == []


def test_transcript_is_encrypted_and_legacy_plaintext_is_migrated(memory_dir: Path) -> None:
    context = _context("encrypted", "first")
    key = conversation_key(context)
    path = memory_dir / f"{key}.json"
    path.write_text(json.dumps({"active": True, "turns": [], "receipts": {}}))
    assert prepare_chat_turn("private message", context) is None
    assert b"private message" not in path.read_bytes()
    assert path.read_bytes().startswith(b"fernet:")
    assert turn_status(key, "first") == "processing"


def test_middle_facts_and_complete_messages_survive_without_a_summary_model(
    memory_dir: Path,
) -> None:
    from app.application.ai_chat import dialogue_memory as memory
    from app.application.ai_chat.dialogue_memory import enrich_model_messages

    for index in range(25):
        context = _context("summary", str(index))
        message = f"第{index}条消息:" + "detail" * 25 + f":FACT-{index:02d}"
        prepare_chat_turn(message, context)
        settle_chat_turn(
            message, context, {"success": True, "response": f"第{index}条回复"}, "completed"
        )

    key = conversation_key(_context("summary", "0"))
    stored = memory._read(key)
    assert stored.get("summary") is None
    assert len(stored["turns"]) == 50

    next_context = _context("summary", "next")
    enriched = enrich_model_messages(
        [{"role": "user", "content": "下一条消息"}], "下一条消息", next_context
    )
    history_text = json.dumps(enriched[1:], ensure_ascii=False)
    for index in range(25):
        assert f"FACT-{index:02d}" in history_text
    assert "未摘要" not in enriched[0]["content"]


def test_legacy_excerpt_summary_cannot_hide_its_retained_source(memory_dir: Path) -> None:
    from app.application.ai_chat import dialogue_memory as memory

    data = {
        "turns": [
            {"role": "user", "content": f"FACT-{i}", "turn_id": str(i), "at": time.time()}
            for i in range(40)
        ],
        "summary": {"count": 28, "text": "only the first few excerpts"},
    }
    context = _context("legacy-summary", "1")
    prepare_chat_turn("seed", context)
    key = conversation_key(context)
    stored = memory._read(key)
    stored.update(data)
    memory._write(key, stored)
    messages = memory._model_messages(memory._read(key), "next")
    assert all(f"FACT-{i}" in json.dumps(messages) for i in range(40))


def test_history_budget_is_enforced_at_provider_without_silent_pretrimming(memory_dir):
    from app.application.agent_orchestrator.context_window_manager import (
        ContextWindowExceeded,
        ContextWindowManager,
    )
    from app.application.ai_chat import dialogue_memory as memory

    contents = [f"fact-{i}:" + "中" * 100 for i in range(6)]
    data = {
        "turns": [
            {"role": "user" if i % 2 == 0 else "assistant", "content": text, "at": time.time()}
            for i, text in enumerate(contents)
        ]
    }
    messages = memory._model_messages(data, "")
    assert [row["content"] for row in messages[1:]] == contents
    original = json.dumps(messages, ensure_ascii=False)
    with pytest.raises(ContextWindowExceeded):
        asyncio.run(ContextWindowManager(token_budget=500, enabled=False).compress(messages))
    assert json.dumps(messages, ensure_ascii=False) == original


def test_oversized_message_is_stored_whole_and_never_partially_claimed_as_history(memory_dir):
    from app.application.ai_chat import dialogue_memory as memory

    context = _context("large", "1")
    text = "完整原文" * 13000 + "TAIL-MARKER"
    prepare_chat_turn(text, context)
    stored = memory._read(conversation_key(context))
    assert stored["turns"][0]["content"] == text
    messages = memory._model_messages(stored, "1")
    assert messages[-1]["content"] == text
    from app.application.agent_orchestrator.context_window_manager import (
        ContextWindowExceeded,
        ContextWindowManager,
    )

    with pytest.raises(ContextWindowExceeded):
        asyncio.run(ContextWindowManager(token_budget=1200).compress(messages))
    assert messages[-1]["content"] == text


def test_summary_is_cleared_when_transcript_is_too_short(memory_dir: Path) -> None:
    from app.application.ai_chat import dialogue_memory as memory

    context = _context("short", "1")
    prepare_chat_turn("只有一条", context)
    settle_chat_turn("只有一条", context, {"response": "收到"}, "completed")
    assert memory._read(conversation_key(context)).get("summary") is None


def test_failed_transcript_write_does_not_leave_turn_in_flight(memory_dir, monkeypatch):
    from app.application.ai_chat import dialogue_memory as memory

    context = _context("write-failure", "first")
    key = conversation_key(context)
    with monkeypatch.context() as patch:
        patch.setattr(memory, "_write", lambda *_: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(OSError):
            prepare_chat_turn("private message", context)
    assert not memory._turn_is_live(key, "first")
    assert prepare_chat_turn("private message", context) is None


def test_failed_settlement_keeps_the_turn_lock_until_receipt_is_durable(memory_dir, monkeypatch):
    from app.application.ai_chat import dialogue_memory as memory

    context = _context("settle-failure", "first")
    key = conversation_key(context)
    assert prepare_chat_turn("task", context) is None
    with monkeypatch.context() as patch:
        patch.setattr(memory, "_write", lambda *_: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(OSError):
            settle_chat_turn("task", context, {"response": "done"}, "completed")
    assert turn_status(key, "first") == "processing"
    settle_chat_turn("task", context, {"response": "done"}, "completed")
    assert turn_status(key, "first") == "completed"
    assert not memory._turn_is_live(key, "first")


def test_two_live_processes_replay_processing_then_the_durable_receipt(memory_dir):
    context = _context("two-workers", "same-turn")
    script = """
import json,sys
from app.application.ai_chat.dialogue_memory import prepare_chat_turn, settle_chat_turn
c=json.loads(sys.argv[1])
print(json.dumps(prepare_chat_turn('task',c)),flush=True)
sys.stdin.readline()
settle_chat_turn('task',c,{'run_id':'real-run','response':'finished'},'completed')
"""
    owner = subprocess.Popen(
        [sys.executable, "-c", script, json.dumps(context)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "XCAGI_DIALOGUE_MEMORY_DIR": str(memory_dir)},
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(owner.stdout.readline).result(timeout=30).strip() == "null"
        retry_script = """
import json,sys
from app.application.ai_chat.dialogue_memory import prepare_chat_turn
print(json.dumps(prepare_chat_turn('task',json.loads(sys.argv[1]))))
"""
        retry = subprocess.run(
            [sys.executable, "-c", retry_script, json.dumps(context)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert owner.poll() is None
        assert json.loads(retry.stdout)["data"]["status"] == "processing"
        owner.communicate("settle\n", timeout=30)
        assert owner.returncode == 0
        replay = subprocess.run(
            [sys.executable, "-c", retry_script, json.dumps(context)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        receipt = json.loads(replay.stdout)
        assert receipt["run_id"] == "real-run"
        assert receipt["execution_state"] == "completed"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=30)


def test_prepare_and_settle_can_use_different_threads(memory_dir):
    context = _context("thread-pool", "one")
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(prepare_chat_turn, "task", context).result() is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(settle_chat_turn, "task", context, {"response": "done"}, "completed").result()
    assert turn_status(conversation_key(context), "one") == "completed"
    from app.application.ai_chat import dialogue_memory as memory

    assert not memory._turn_is_live(conversation_key(context), "one")


def test_concurrent_process_writes_preserve_both_workers_messages(memory_dir, monkeypatch):
    from app.application.ai_chat import dialogue_memory as memory

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XCAGI_SECRET_KEY", raising=False)
    script = """
import sys
from app.application.ai_chat.dialogue_memory import prepare_chat_turn, settle_chat_turn
sys.stdin.readline()
for i in range(10):
    turn=f'{sys.argv[1]}-{i}'
    c={'local_user_id':1,'tenant_id':1,'conversation_id':'concurrent','turn_id':turn}
    assert prepare_chat_turn(turn,c) is None
    settle_chat_turn(turn,c,{'response':turn+'-done'},'completed')
"""
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ("first", "second")
    ]
    try:
        for worker in workers:
            worker.stdin.write("go\n")
            worker.stdin.flush()
        for worker in workers:
            _, error = worker.communicate(timeout=30)
            assert worker.returncode == 0, error
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=30)
    stored = memory._read(conversation_key(_context("concurrent", "unused")))
    assert len(stored["turns"]) == 40
    assert len(stored["receipts"]) == 20
    assert all(receipt["status"] == "completed" for receipt in stored["receipts"].values())
