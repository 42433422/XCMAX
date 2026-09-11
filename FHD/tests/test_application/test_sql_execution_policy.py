import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
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
