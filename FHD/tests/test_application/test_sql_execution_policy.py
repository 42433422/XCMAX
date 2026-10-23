import logging

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.normal_chat.routing import RoutingPorts, route_message
from app.application.workflow.sql_execution_policy import REFUSAL_CODE, rejected_sql_plan


@pytest.mark.parametrize(
    "message",
    [
        "帮我在数据库里执行 DELETE FROM customers 清空客户表",
        "执行 truncate table customers",
        "运行 DROP TABLE products",
        "execute DELETE /* comment */ FROM customers",
        "DELETE FROM customers",
    ],
)
def test_direct_sql_is_blocked_with_no_executable_steps(message):
    plan = rejected_sql_plan(message, "p1")
    assert plan is not None and not plan.nodes
    run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
        user_id="u1", message=message, plan=plan
    )
    assert run.status == "blocked" and run.error == REFUSAL_CODE
    assert not run.tool_calls and not run.steps
    assert run.final_output["refusal_code"] == REFUSAL_CODE


@pytest.mark.parametrize(
    "message", ["解释 DELETE FROM customers 的作用", "新增客户甲", "查询客户列表"]
)
def test_sql_discussion_and_business_requests_are_not_direct_execution(message):
    assert rejected_sql_plan(message, "p1") is None


def test_sql_block_comment_scanner_preserves_refusal_after_many_untrusted_markers():
    message = "执行 /*" + "a/*" * 20_000 + "*/ DELETE FROM customers"

    plan = rejected_sql_plan(message, "p1")

    assert plan is not None and plan.metadata["refusal_code"] == REFUSAL_CODE


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("恢复数据库 backup-2026_10.bak", "backup-2026_10.bak"),
        ("恢复数据库 ../private.bak", None),
        ("恢复数据库 name.bakx", None),
        ("恢复数据库 " + "0" * 100_000, None),
    ],
)
def test_database_restore_backup_filename_scan_is_bounded_and_compatible(message, expected):
    from app.application.workflow.sql_execution_policy import database_maintenance_plan

    plan = database_maintenance_plan(
        message, "p1", {"system_maintenance": {"actions": {"restore_database": {}}}}
    )

    if expected is None:
        assert plan is None or plan.nodes[0].tool_id == "clarify"
    else:
        assert plan is not None and plan.nodes[0].params["backup_file"] == expected


def test_normal_chat_refuses_oversized_message_before_regex_routing():
    def unexpected(*_args, **_kwargs):
        pytest.fail("oversized input must be rejected before routing callbacks")

    ports = RoutingPorts(
        database_maintenance=unexpected,
        desktop_action=unexpected,
        is_negation=unexpected,
        is_negated_action=unexpected,
        sales_write=unexpected,
        label_slots=unexpected,
        is_full_product_list=unexpected,
        llm_route=unexpected,
        logger=logging.getLogger(__name__),
    )

    assert route_message("型号 " + "0" * 100_000, ports) == {"intent": "unknown", "slots": {}}


def test_workflow_parsers_fail_closed_on_oversized_untrusted_text():
    from app.application.workflow.finance_write_plan import finance_transaction_node
    from app.application.workflow.read_query_plan import (
        customer_read_node,
        report_read_node,
        sales_export_node,
    )
    from app.application.workflow.sales_quote_plan import sales_quote_node
    from app.application.workflow.shipment_plan import shipment_document_node

    message = "请创建销售订单 " + "\t" * 100_000
    registry = {
        "customers": {},
        "finance": {},
        "reports": {},
        "sales": {},
        "shipment_orders": {},
    }

    assert customer_read_node(message, {"intent": "customers_query"}, registry) is None
    assert report_read_node(message, registry) is None
    assert sales_export_node(message, registry) is None
    assert sales_quote_node(message, registry) is None
    assert shipment_document_node(message, registry) is None
    assert finance_transaction_node(message, registry) is None
