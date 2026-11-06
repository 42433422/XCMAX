"""A long conversation keeps confirmed facts and the same active id."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_chat.active_conversation import (
    active_conversation_for,
    remember_active_conversation,
)
from app.application.ai_chat.confirmed_facts import try_confirmed_fact_reply
from app.application.ai_chat.dialogue_memory import enrich_model_messages
from app.application.workflow.chat_deterministic_fast_paths import try_deterministic_chat_reply


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


def _ctx(conversation_id: str, turn: str, **extra: object) -> dict[str, object]:
    return {
        "local_user_id": 1,
        "tenant_id": 1,
        "conversation_id": conversation_id,
        "turn_id": turn,
        **extra,
    }


def test_fact_question_does_not_take_the_greeting_branch(memory_dir: Path) -> None:
    ctx = _ctx("kept", "1")
    established = try_confirmed_fact_reply(
        "请确认记下这些事实：客户总数11，A类7，B类4，合同总额2万元，会话标记甲-9。",
        ctx,
    )
    assert established is not None
    assert try_deterministic_chat_reply("已确认的客户总数是多少？", runtime_context=ctx) is None
    asked = try_confirmed_fact_reply("已确认的客户总数是多少？", _ctx("kept", "2"))
    assert asked is not None
    assert "11" in asked["response"]
    assert "智能助手" not in asked["response"]


def test_smalltalk_after_confirmed_facts_stays_on_the_ledger(memory_dir: Path) -> None:
    ctx = _ctx("kept", "1")
    try_confirmed_fact_reply(
        "请确认记下这些事实：客户总数11，A类7，B类4，合同总额2万元，会话标记甲-9。",
        ctx,
    )
    reply = try_deterministic_chat_reply("请用一句中文说你好。", runtime_context=ctx)
    assert reply is not None
    assert reply["action"] == "confirmed_facts"
    assert "11" in reply["response"]
    assert "智能助手" not in reply["response"]


def test_greeting_without_confirmed_facts_is_unchanged(memory_dir: Path) -> None:
    reply = try_deterministic_chat_reply("你好", runtime_context=_ctx("empty", "1"))
    assert reply is not None
    assert reply["action"] == "greeting"


def test_fact_line_is_kept_when_history_is_compressed(memory_dir: Path) -> None:
    import asyncio

    from app.application.agent_orchestrator.context_window_manager import ContextWindowManager

    ctx = _ctx("kept", "ask")
    try_confirmed_fact_reply(
        "请确认记下这些事实：客户总数11，A类7，B类4，合同总额2万元，会话标记甲-9。",
        _ctx("kept", "1"),
    )
    current = {"role": "user", "content": "已确认的客户总数是多少？"}
    enriched = enrich_model_messages(
        [{"role": "system", "content": "现有规则"}, current],
        "已确认的客户总数是多少？",
        ctx,
    )
    fact_lines = [
        item["content"]
        for item in enriched
        if item.get("role") == "system" and "已确认事实" in str(item.get("content"))
    ]
    assert fact_lines and "11" in fact_lines[0]
    filler = [
        {"role": "user", "content": f"无关闲聊第{index}句" * 40} for index in range(12)
    ]
    compressed = asyncio.run(
        ContextWindowManager(token_budget=500, recent_keep=1, summarize_threshold=2).compress(
            [*enriched[:-1], *filler, current]
        )
    )
    kept = "\n".join(
        str(item.get("content") or "")
        for item in compressed.messages
        if item.get("role") == "system"
    )
    assert "11" in kept


def test_restart_state_points_at_the_previous_conversation(memory_dir: Path) -> None:
    remember_active_conversation(_ctx("conv-kept", "9"), conversation_id="conv-kept")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    remember_active_conversation(_ctx("other", "1", tenant_id=2), conversation_id="other")
    assert active_conversation_for(1, tenant_id="1") == "conv-kept"
    assert active_conversation_for(1, tenant_id="2") == "other"
    assert active_conversation_for(1, tenant_id="") == ""


def test_active_route_is_registered_before_the_session_path() -> None:
    from app.fastapi_routes.domains.conversation.conversation_routes import router

    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.index("/api/conversations/active") < paths.index("/api/conversations/{session_id}")
