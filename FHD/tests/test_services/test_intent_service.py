"""
意图识别服务测试
"""

import pytest

from app.services.intent_service import (
    is_confirmation,
    is_goodbye,
    is_greeting,
    is_help_request,
    is_negation,
    is_negation_intent,
    recognize_intents,
)


class TestIntentServiceHelpers:
    """意图服务辅助函数测试"""

    def test_is_negation_positive(self):
        assert is_negation("不要生成发货单") is True
        assert is_negation("别开发货单") is True
        assert is_negation("不要上传") is True

    def test_is_negation_negative(self):
        assert is_negation("帮我生成发货单") is False
        assert is_negation("你好") is False

    def test_is_greeting_positive(self):
        assert is_greeting("你好") is True
        assert is_greeting("您好") is True
        assert is_greeting("hello") is True

    def test_is_greeting_negative(self):
        assert is_greeting("生成发货单") is False
        assert is_greeting("产品列表") is False

    def test_is_goodbye_positive(self):
        assert is_goodbye("再见") is True
        assert is_goodbye("拜拜") is True
        assert is_goodbye("bye") is True
        assert is_goodbye("先这样") is True

    def test_is_goodbye_negative(self):
        assert is_goodbye("你好") is False
        assert is_goodbye("帮我生成") is False

    def test_is_help_request_positive(self):
        assert is_help_request("你能做什么") is True
        assert is_help_request("怎么用") is True
        assert is_help_request("帮助") is True

    def test_is_help_request_negative(self):
        assert is_help_request("生成发货单") is False
        assert is_help_request("产品列表") is False

    def test_is_confirmation_positive(self):
        assert is_confirmation("好的") is True
        assert is_confirmation("可以") is True

    def test_is_negation_intent(self):
        assert is_negation_intent("不要生成发货单") is True
        assert is_negation_intent("算了") is True
        assert is_negation_intent("帮我生成") is False

    def test_erp_domain_context_attaches_open_ontology_without_forcing_tool(self):
        result = recognize_intents("借贷必平衡和 MRP 净需求怎么校验？")

        assert "erp_domain_ontology" in result["intent_hints"]
        context = result["domain_context"]
        assert context["source"] == "persy_erp_ontology"
        rule_ids = {rule["id"] for rule in context["rules"]}
        assert "accounting.double_entry_balance" in rule_ids
        assert "manufacturing.mrp_net_requirement" in rule_ids
        assert any("sum(line.amount" in rule["symbolic_expression"] for rule in context["rules"])

    def test_non_erp_question_does_not_get_domain_context(self):
        result = recognize_intents("客户北辰科技负责人是谁？")

        assert "domain_context" not in result
        assert "erp_domain_ontology" not in result["intent_hints"]
