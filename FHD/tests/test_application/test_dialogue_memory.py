"""连续对话把本会话原话交给模型完成函数，不在进程里拼答案。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from app.application.ai_chat.dialogue_memory import (
    dialogue_reply,
    prepare_chat_turn,
    set_dialogue_complete,
    settle_chat_turn,
    should_answer_as_dialogue,
    turn_status,
)


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def model_calls(memory_dir: Path) -> list[list[dict[str, str]]]:
    seen: list[list[dict[str, str]]] = []

    async def complete(messages: Sequence[dict[str, str]]) -> str:
        seen.append([dict(item) for item in messages])
        return "模型完成:" + messages[-1]["content"]

    set_dialogue_complete(complete)
    yield seen
    set_dialogue_complete(None)


def test_operational_commands_stay_on_the_business_path(memory_dir: Path) -> None:
    assert should_answer_as_dialogue("发货单 太阳鸟 5桶 20L规格", {"conversation_id": "c11"}) is False
    assert should_answer_as_dialogue("查一下客户", {"conversation_id": "c11"}) is False
    assert should_answer_as_dialogue("请提交一个缺陷工单", {"conversation_id": "c11"}) is False
    assert (
        should_answer_as_dialogue(
            "如果按这个表统计有多少行",
            {"conversation_id": "sheet", "excel_analysis": {"file_path": "/tmp/a.xlsx"}},
        )
        is False
    )
    assert (
        should_answer_as_dialogue(
            "我们发现一个问题，在聊天过程中切换到客户管理页面，首次加载可能需要1.7秒。",
            {"conversation_id": "c11"},
        )
        is True
    )


async def test_reply_comes_from_the_complete_callback(model_calls: list[list[dict[str, str]]]) -> None:
    first = {"conversation_id": "memo", "turn_id": "1"}
    assert prepare_chat_turn("先记下客户 120 家。", first) is None
    opened = await dialogue_reply("先记下客户 120 家。", first)
    assert opened is not None
    settle_chat_turn("先记下客户 120 家。", first, opened, "completed")
    second = {"conversation_id": "memo", "turn_id": "2"}
    assert prepare_chat_turn("刚才的客户是多少？", second) is None
    answered = await dialogue_reply("刚才的客户是多少？", second)
    assert answered is not None
    assert answered["response"] == "模型完成:刚才的客户是多少？"
    assert answered["data"]["action"] == "dialogue_memory"
    assert len(model_calls) == 2
    sent = "\n".join(item["content"] for item in model_calls[1] if item["role"] == "user")
    assert "客户 120 家" in sent
    assert "刚才的客户是多少" in sent


async def test_same_turn_does_not_call_the_model_again(model_calls: list[list[dict[str, str]]]) -> None:
    context = {"conversation_id": "retry", "turn_id": "same"}
    text = "星河科技目前有120家客户。"
    assert prepare_chat_turn(text, context) is None
    payload = await dialogue_reply(text, context)
    settle_chat_turn(text, context, payload, "completed")
    again = prepare_chat_turn(text, context)
    assert again is not None
    assert again["response"] == payload["response"]
    assert len(model_calls) == 1
    other = prepare_chat_turn("星河科技目前有1家客户。", context)
    assert other is not None and other["success"] is False
    assert len(model_calls) == 1


def test_abandoned_turn_is_not_a_successful_analysis(memory_dir: Path) -> None:
    context = {"conversation_id": "half", "turn_id": "open"}
    assert prepare_chat_turn("企业目前有120家客户。", context) is None
    assert turn_status("half", "open") == "processing"
    from app.application.ai_chat import dialogue_memory as memory

    memory._INFLIGHT.clear()
    prepare_chat_turn("后来新增10家客户。", {"conversation_id": "half", "turn_id": "next"})
    assert turn_status("half", "open") == "interrupted"


async def test_sessions_do_not_share_transcripts(model_calls: list[list[dict[str, str]]]) -> None:
    whale = {"conversation_id": "whale", "turn_id": "w"}
    pine = {"conversation_id": "pine", "turn_id": "p"}
    assert prepare_chat_turn("识别标记为蓝鲸-731。", whale) is None
    await dialogue_reply("识别标记为蓝鲸-731。", whale)
    assert prepare_chat_turn("识别标记为松塔-284。", pine) is None
    await dialogue_reply("识别标记为松塔-284。", pine)
    pine_text = "\n".join(item["content"] for item in model_calls[-1])
    assert "松塔-284" in pine_text
    assert "蓝鲸-731" not in pine_text
