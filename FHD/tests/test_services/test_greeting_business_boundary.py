"""Check all default greeting entry points against salutation-prefixed business text."""

import pytest

from app.domain.neuro.reflex_arc import IntentReflexArc, ReflexType
from app.domain.neuro.reflex_patterns import ReflexPatternMatcher
from app.services.intent_service import _reflex_basic_intents, is_greeting


@pytest.mark.parametrize(
    "text",
    [
        "你好",
        "您好！",
        "你好呀",
        " Hi! ",
        "Hello there.",
        "早上好",
        "下午好！",
        "晚上好",
        "哈喽",
        "在吗？",
    ],
)
def test_standalone_greetings_remain_recognized(text):
    assert is_greeting(text)
    assert _reflex_basic_intents(text)["is_greeting"]
    result = IntentReflexArc().process(text)
    assert result.triggered and result.reflex_type == ReflexType.GREETING
    assert ReflexPatternMatcher().match(text)[0] == ReflexType.GREETING


@pytest.mark.parametrize(
    "text",
    [
        "shipping records",
        "查询 shipping 的客户",
        "查一下 Hitachi 型号",
        "你好，查询客户列表",
        "您好，请导出销售报表",
        "hello, list customers",
        "hi show inventory",
        "早上好，查一下库存",
        "下午好，生成发货单",
        "晚上好，新增客户星光贸易",
        "哈喽，打印标签",
        "在吗？帮我查客户",
    ],
)
def test_business_request_is_not_consumed_by_default_greeting_routes(text):
    assert not is_greeting(text)
    assert not _reflex_basic_intents(text)["is_greeting"]
    result = IntentReflexArc().process(text)
    assert not (result.triggered and result.reflex_type == ReflexType.GREETING)
    assert ReflexPatternMatcher().match(text)[0] != ReflexType.GREETING


@pytest.mark.parametrize("business_text", ["客户列表", "查询产品", "发货记录"])
def test_salutation_prefixed_request_retains_rule_business_intent(business_text):
    from app.services.intent_service import recognize_intents

    baseline = recognize_intents(business_text)
    prefixed = recognize_intents("你好，" + business_text)
    assert baseline["tool_key"] is not None
    assert prefixed["tool_key"] == baseline["tool_key"]
    assert not prefixed["is_greeting"]
