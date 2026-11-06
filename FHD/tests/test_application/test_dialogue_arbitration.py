"""Dialogue facts must not be dispatched as enterprise customer lookups."""

from __future__ import annotations

from app.application.ai_chat.dialogue_arbitration import (
    is_client_version_question,
    is_dialogue_fact_message,
    is_explicit_enterprise_customer_query,
)
from app.application.ai_chat.dialogue_memory import should_answer_as_dialogue
from app.application.normal_chat_dispatch import route_normal_mode_message


def test_spoken_customer_counts_are_not_database_queries() -> None:
    text = "请记下：客户总数120，A类70，B类50，合同总额360万元，会话标记蓝鲸-1。"
    assert is_dialogue_fact_message(text) is True
    assert is_explicit_enterprise_customer_query(text) is False
    assert route_normal_mode_message(text)["intent"] == "dialogue_fact"


def test_fact_questions_and_hypotheses_stay_on_the_dialogue_path() -> None:
    question = "已确认的客户总数和分类是多少？"
    hypothesis = "假设A类再增加10个，暂时不要修改。"
    assert route_normal_mode_message(question)["intent"] == "dialogue_fact"
    assert route_normal_mode_message(hypothesis)["intent"] == "dialogue_fact"
    assert (
        should_answer_as_dialogue(
            "查一下已确认的客户总数", {"local_user_id": 1, "conversation_id": "c"}
        )
        is True
    )


def test_explicit_customer_database_reads_still_route_to_customers() -> None:
    for text in (
        "查询甲公司的客户",
        "客户有哪些",
        "查一下客户",
        "请查询企业客户库",
        "请只读查询企业客户库，不要修改数据。",
    ):
        assert is_explicit_enterprise_customer_query(text) is True
        assert is_dialogue_fact_message(text) is False
        assert route_normal_mode_message(text)["intent"] == "customers_query"
    assert route_normal_mode_message("不修改客户资料")["intent"] == "unknown"
    assert route_normal_mode_message("不允许修改客户资料")["intent"] == "unknown"


def test_desktop_version_question_is_not_a_product_lookup() -> None:
    text = "请只读告诉我桌面版本，不要改任何数据。"
    assert is_client_version_question(text) is True
    assert route_normal_mode_message(text)["intent"] == "unknown"


def test_read_only_customer_database_query_is_not_a_mutation_workflow() -> None:
    from app.domain.conversation.services.chat_tool_intent import (
        looks_like_explicit_workflow_tool_intent,
    )

    text = "请只读查询企业客户库，不要修改数据。"
    assert looks_like_explicit_workflow_tool_intent(text) is False
    assert looks_like_explicit_workflow_tool_intent("修改客户资料") is True
    assert looks_like_explicit_workflow_tool_intent("查数据库里的客户") is True
    assert route_normal_mode_message(text)["intent"] == "customers_query"


def test_operational_customer_lookup_still_skips_dialogue_memory() -> None:
    assert (
        should_answer_as_dialogue("查一下客户", {"local_user_id": 1, "conversation_id": "c"})
        is False
    )
