"""The unified model receives bounded, owner-scoped chat history."""

from __future__ import annotations

import json
import subprocess
import sys
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
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


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


def test_abandoned_turn_is_not_treated_as_completed(memory_dir: Path) -> None:
    context = _context("half", "open")
    assert prepare_chat_turn("查询客户", context) is None
    assert turn_status(conversation_key(context), "open") == "processing"

    from app.application.ai_chat import dialogue_memory as memory

    memory._INFLIGHT.clear()
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
    with pytest.raises(ValueError, match="另一项执行"):
        settle_chat_turn("删除旧记录", context, {"run_id": "other"}, "completed")


@pytest.mark.parametrize("changed", [{"local_user_id": 2}, {"tenant_id": 2}, {"mod_id": "other"}])
def test_transcript_is_scoped_to_owner_tenant_and_mod(
    memory_dir: Path, changed: dict[str, object]
) -> None:
    original = _context("scope", "1", mod_id="erp")
    assert prepare_chat_turn("只属于当前会话的文字", original) is None
    settle_chat_turn("只属于当前会话的文字", original, {"response": "收到"}, "completed")
    other = {**original, **changed, "turn_id": "2"}

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


def test_failed_transcript_write_does_not_leave_turn_in_flight(memory_dir, monkeypatch):
    from app.application.ai_chat import dialogue_memory as memory

    context = _context("write-failure", "first")
    key = conversation_key(context)
    with monkeypatch.context() as patch:
        patch.setattr(memory, "_write", lambda *_: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(OSError):
            prepare_chat_turn("private message", context)
    assert (key, "first") not in memory._INFLIGHT
    assert prepare_chat_turn("private message", context) is None
