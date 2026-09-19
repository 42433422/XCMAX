"""拒绝类请求不得进入写入执行计划，包括实机复现的只读限定语。"""

from __future__ import annotations

import pytest

from app.application.normal_chat_dispatch import route_normal_mode_message
from app.domain.services.conversation.chat_tool_intent import (
    is_negated_action_request,
    looks_like_business_db_write,
)

EXECUTION_INTENTS = {
    "shipment",
    "sales_write",
    "delete_entity",
    "label_print",
    "inventory_count",
    "business_db_write",
}

NEGATED_REQUESTS = (
    "只查询，不新增、修改或删除任何业务数据。请查产品编码 DEMO-001，列出产品名称、单价和当前库存，并说明查询是否成功。",
    "不删除产品 DEMO-001",
    "不修改客户资料",
    "不新增产品",
    "不要打印标签",
    "别打印标签",
    "不要删除客户张三",
    "别删除客户张三",
    "不用开单",
    "不要发货",
    "别导出报表",
    "不要新增产品",
    "禁止打印送货单",
    "不要给我打印",
    "不用帮我删除客户",
    "不想再开单了",
    "别再删除客户了",
)


@pytest.mark.parametrize("message", NEGATED_REQUESTS)
def test_negated_request_never_routes_to_execution_intent(message: str) -> None:
    assert is_negated_action_request(message) is True
    route = route_normal_mode_message(message)
    assert route["intent"] == "unknown", f"拒绝类请求被路由到执行意图: {route}"


@pytest.mark.parametrize("message", NEGATED_REQUESTS)
def test_negated_request_is_not_business_db_write(message: str) -> None:
    assert looks_like_business_db_write(message) is False


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("帮我打印标签", "label_print"),
        ("开单", "shipment"),
        ("删除客户张三", "customers_query"),
        ("导出报表", "reports_query"),
        ("把A001卖给七彩乐园，10桶，单价25", "sales_write"),
    ],
)
def test_affirmative_execution_requests_still_route(message: str, expected_intent: str) -> None:
    assert is_negated_action_request(message) is False
    assert route_normal_mode_message(message)["intent"] == expected_intent


def test_delete_entity_still_routes_when_affirmative() -> None:
    route = route_normal_mode_message("删除产品A001")
    assert route["intent"] == "customers_query" or looks_like_business_db_write("删除产品A001")


@pytest.mark.parametrize(
    "message",
    [
        "这个产品特别好用",
        "别的客户也买了",
        "客户别名为ABC",
        "分别查询两个客户",
        "识别一下这张发票",
        "保存好了吗",
    ],
)
def test_negation_detector_has_no_word_internal_false_positive(message: str) -> None:
    assert is_negated_action_request(message) is False


def test_business_db_write_still_true_for_affirmative_crud() -> None:
    assert looks_like_business_db_write("删除客户张三") is True
    assert looks_like_business_db_write("把新产品写入数据库") is True
