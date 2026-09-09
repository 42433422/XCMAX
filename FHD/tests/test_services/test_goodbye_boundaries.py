"""Cancellation and business content must survive the conversational shortcuts."""

import pytest

from app.services.intent_service import _reflex_basic_intents, is_goodbye
from scripts.dev.intent_benchmark_llm import predict


@pytest.mark.parametrize("text", ["再见", "拜拜！", "先这样吧", "Bye!", "goodbye", "See you."])
def test_standalone_farewell(text):
    assert is_goodbye(text)
    assert _reflex_basic_intents(text)["is_goodbye"]


@pytest.mark.parametrize("text", [
    "别开单", "停止", "取消", "stop", "cancel", "退出当前任务",
    "给张三发消息说再见", "查询型号 BYE-001", "先这样记录客户备注", "不要说再见",
])
def test_actions_and_content_are_not_farewells(text):
    assert not is_goodbye(text)
    assert not _reflex_basic_intents(text)["is_goodbye"]


def test_denied_shipment_reaches_cancellation_clarification():
    result = predict("别开单")
    assert result["intent"] == "clarify"
    assert result["reason"] == "negated_action"
