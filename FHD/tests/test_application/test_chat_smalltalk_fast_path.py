"""小闲聊短路回归：问候/再见/求助不得进入 generic_workflow 执行业务工具。

背景（2026-09-07 清单冒烟）：「你好」被 planner 误判为 generic_workflow，
真的调用 query_products 查了产品库。修复为确定性快路径短路。
"""

from __future__ import annotations

import pytest

from app.application.workflow.chat_deterministic_fast_paths import (
    _try_smalltalk_reply,
    try_deterministic_chat_reply,
)


@pytest.mark.parametrize("message", ["你好", "您好", "hello", "嗨"])
def test_pure_greeting_short_circuits(message: str) -> None:
    reply = _try_smalltalk_reply(message)
    assert reply is not None
    assert reply["action"] == "greeting"
    assert reply["trace_intent"] == "smalltalk_greeting"
    assert "智能助手" in reply["response"]


@pytest.mark.parametrize("message", ["再见", "拜拜", "bye"])
def test_pure_goodbye_short_circuits(message: str) -> None:
    reply = _try_smalltalk_reply(message)
    assert reply is not None
    assert reply["action"] == "goodbye"


def test_help_short_circuits() -> None:
    reply = _try_smalltalk_reply("帮助")
    assert reply is not None
    assert reply["action"] == "help"
    assert "开单发货" in reply["response"]


@pytest.mark.parametrize(
    "message",
    [
        "你好，帮我开单 太阳鸟 5桶 20L规格",
        "你好，查一下客户",
        "帮助我生成发货单",
    ],
)
def test_business_message_not_short_circuited(message: str) -> None:
    """含业务意图时不得短路，交给后续业务链路。"""
    assert _try_smalltalk_reply(message) is None


def test_deterministic_entry_returns_smalltalk() -> None:
    reply = try_deterministic_chat_reply("你好")
    assert reply is not None
    assert reply.get("action") == "greeting"


def test_deterministic_entry_passes_through_business() -> None:
    assert try_deterministic_chat_reply("随便说点什么业务外的话哈") is None
