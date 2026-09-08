"""Non-execution must bypass both model planning and tool dispatch."""

from unittest.mock import Mock, patch

import pytest

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.no_operation import no_operation_plan
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph


@pytest.mark.parametrize(
    "message",
    [
        "你好",
        "hello!",
        "不要新建客户",
        "请不要删除所有数据",
        "不用查询客户",
        "不要打印标签",
        "别开单",
        "暂不发货",
        "不要打印标签，然后给客户开单",
        "不要删除，只查询客户",
    ],
)
def test_non_execution_bypasses_model_and_tools(message):
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    planner._plan_with_react_multiagent = Mock(side_effect=AssertionError("model must not run"))
    dispatch = Mock(side_effect=AssertionError("tool must not run"))
    for plan in [
        planner.plan("user", message, {}),
        planner._fallback_plan("fallback", message, {}),
    ]:
        assert plan.intent == "no_operation"
        assert validate_plan_graph(plan) is None
        for agentic in [False, True]:
            result = WorkflowEngine(dispatch).run(
                plan, agentic_loop=agentic, tool_registry={"products": {}}
            )
            assert result.success and result.node_results == []
            assert result.message == plan.metadata["response"]
    dispatch.assert_not_called()
    planner._plan_with_react_multiagent.assert_not_called()


@pytest.mark.parametrize(
    "message",
    [
        "你好，查询客户",
        "不要新建客户，查询产品",
        "查询客户不要公司",
        "不要忘记新建客户",
        "客户列表",
        "",
    ],
)
def test_business_or_unparsed_text_is_not_suppressed(message):
    assert no_operation_plan("p", message) is None


def test_empty_business_plan_remains_invalid():
    assert validate_plan_graph(PlanGraph(plan_id="p", intent="customers_query")) == "nodes 不能为空"


def test_no_operation_cannot_smuggle_tool_nodes():
    plan = PlanGraph(
        plan_id="p",
        intent="no_operation",
        nodes=[WorkflowNode(node_id="n", tool_id="products", action="query")],
    )
    assert validate_plan_graph(plan) is not None
    dispatch = Mock(side_effect=AssertionError("tool must not run"))
    assert not WorkflowEngine(dispatch).run(plan).success
    dispatch.assert_not_called()


@pytest.mark.parametrize("auto_execute", [False, True])
def test_orchestrator_persists_completed_non_execution(auto_execute):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repository = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repository)
    plan = no_operation_plan("p", "不要新建客户")
    with patch.object(
        orchestrator, "_execute_ready_steps", side_effect=AssertionError("must not execute")
    ):
        run = orchestrator.start_run_from_plan(
            user_id="u", message="不要新建客户", plan=plan, auto_execute=auto_execute
        )
    assert run.status == "completed"
    assert not run.steps and not run.tool_calls and not run.error
    assert run.events[-1].message == plan.metadata["response"]


def test_orchestrator_rejects_no_operation_with_business_nodes():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    plan = PlanGraph(
        plan_id="p",
        intent="no_operation",
        nodes=[WorkflowNode(node_id="n", tool_id="products", action="query")],
    )
    with patch.object(
        orchestrator, "_execute_ready_steps", side_effect=AssertionError("must not execute")
    ):
        run = orchestrator.start_run_from_plan(user_id="u", message="hello", plan=plan)
    assert run.status == "failed"
    assert not run.tool_calls


@pytest.mark.parametrize(
    "message",
    [
        "帮我在数据库里执行 DELETE FROM customers 清空客户表",
        "DELETE FROM customers",
        "运行 truncate table customers",
        "execute INSERT INTO customers VALUES (1)",
        "run UPDATE customers SET name='x'",
        "执行 SELECT * FROM customers",
    ],
)
def test_raw_sql_request_does_not_turn_into_business_crud(message):
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    with patch.object(
        planner, "_plan_with_react_multiagent", side_effect=AssertionError("must not plan tools")
    ):
        plan = planner.plan("u", message, {"business_db": {}})
    assert plan.nodes == []
    assert plan.metadata["reason"] == "unsupported_raw_sql"
    assert "未执行" in plan.metadata["response"]
    dispatch = Mock(side_effect=AssertionError("must not dispatch"))
    WorkflowEngine(dispatch).run(plan)
    dispatch.assert_not_called()


@pytest.mark.parametrize(
    "message", ["删除客户 ID 12", "查询客户名单", "解释 DELETE FROM 的含义", "查询客户 Select科技"]
)
def test_business_requests_and_sql_explanations_are_not_raw_sql_execution(message):
    assert no_operation_plan("p", message) is None
