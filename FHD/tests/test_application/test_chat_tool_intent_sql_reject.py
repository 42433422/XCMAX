"""Direct SQL refusal policy does not invent executable business nodes."""

from app.application.workflow.sql_execution_policy import rejected_sql_plan


def test_explicit_sql_policy_returns_no_executable_nodes():
    plan = rejected_sql_plan("执行 DELETE FROM customers", "policy-case")
    assert plan.nodes == []
    assert plan.metadata["refusal_code"] == "raw_sql_execution_not_supported"


def test_raw_sql_policy_does_not_misclassify_business_requests():
    assert rejected_sql_plan("查一下客户列表", "plan-1") is None
