"""连续对话底稿：纠正覆盖旧值，假设不改确认值，会话之间不串线。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.application.ai_chat.dialogue_memory import (
    build_messages,
    should_answer_as_dialogue,
    try_dialogue_memory_reply,
)


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


def test_scenario_is_dialogue_and_shipment_is_not(memory_dir: Path) -> None:
    assert should_answer_as_dialogue(
        "我们现在要对一款企业级桌面软件进行稳定性测试，产品名称叫 XCMAX。",
        {"conversation_id": "c11"},
    )
    assert not should_answer_as_dialogue("发货单 太阳鸟 5桶 20L规格", {"conversation_id": "c11"})
    assert should_answer_as_dialogue(
        "如果A窗口新增30家客户，其中10家成为活跃客户，那么活跃客户数量是多少？",
        {"conversation_id": "c11"},
    )


def test_active_session_keeps_recall_and_releases_real_customer_lookup(memory_dir: Path) -> None:
    context = {"conversation_id": "c11", "turn_id": "t1"}

    async def complete(_messages: list[dict[str, str]]) -> str:
        return "已记录。"

    asyncio.run(try_dialogue_memory_reply("星河科技目前有120家客户。", context, complete=complete))
    assert should_answer_as_dialogue("公司目前总共有多少员工？", {"conversation_id": "c11"})
    assert should_answer_as_dialogue(
        "我们发现一个问题，在聊天过程中切换到客户管理页面，首次加载可能需要1.7秒。",
        {"conversation_id": "c11"},
    )
    assert not should_answer_as_dialogue("查一下客户", {"conversation_id": "c11"})
    assert should_answer_as_dialogue(
        "其中10种商品已经入库。",
        {"conversation_id": "c11"},
    )
    assert should_answer_as_dialogue(
        "每种入库商品数量为20件。",
        {"conversation_id": "c11"},
    )
    assert should_answer_as_dialogue("入库后总库存是多少？", {"conversation_id": "c11"})
    assert not should_answer_as_dialogue("发货单 太阳鸟 5桶 20L规格", {"conversation_id": "c11"})


def test_ledger_keeps_earlier_facts_and_does_not_cross_sessions(memory_dir: Path) -> None:
    seen: list[str] = []

    async def complete(messages: list[dict[str, str]]) -> str:
        seen.append(messages[0]["content"])
        return "150家，活跃客户80家。"

    first = asyncio.run(
        try_dialogue_memory_reply(
            "A窗口的测试数据是客户数量120家，其中活跃客户80家。",
            {"conversation_id": "session-a", "turn_id": "a1"},
            complete=complete,
        )
    )
    assert first is not None
    second = asyncio.run(
        try_dialogue_memory_reply(
            "现在我修改一下，A窗口的客户数量从120家调整为150家，活跃客户仍然是80家。",
            {"conversation_id": "session-a", "turn_id": "a2"},
            complete=complete,
        )
    )
    assert second is not None and second["response"] == "150家，活跃客户80家。"
    prompt = seen[-1]
    assert "120家" in prompt and "调整为150家" in prompt
    assert "假设" in prompt and "撤销" in prompt
    assert "各部门最后一次有效人数" in prompt
    other = build_messages("session-b", "我的识别标记是什么？")
    assert "120家" not in other[0]["content"]


def test_same_turn_retries_do_not_call_the_model_again(memory_dir: Path) -> None:
    calls = {"n": 0}

    async def complete(_messages: list[dict[str, str]]) -> str:
        calls["n"] += 1
        return "收到。"

    context = {"conversation_id": "retry", "turn_id": "same"}
    text = "星河科技的稳定性测试请介绍当前范围。"
    asyncio.run(try_dialogue_memory_reply(text, context, complete=complete))
    again = asyncio.run(try_dialogue_memory_reply(text, context, complete=complete))
    assert calls["n"] == 1
    assert again is not None and again["response"] == "收到。"


def test_model_failure_keeps_the_user_turn_and_does_not_raise(memory_dir: Path) -> None:
    async def complete(_messages: list[dict[str, str]]) -> str:
        raise ValueError("model auth")

    result = asyncio.run(
        try_dialogue_memory_reply(
            "星河科技稳定性测试先记住产品名称 XCMAX。",
            {"conversation_id": "fail", "turn_id": "f1"},
            complete=complete,
        )
    )
    assert result is not None and "没有生成可靠回答" in result["response"]
    prompt = build_messages("fail", "产品名称是什么？")
    assert "XCMAX" in prompt[0]["content"]


def test_excel_context_stays_on_the_business_path(memory_dir: Path) -> None:
    assert not should_answer_as_dialogue(
        "如果按星河科技的测试方案统计这个表有多少行",
        {"conversation_id": "sheet", "excel_analysis": {"file_path": "/tmp/a.xlsx"}},
    )
