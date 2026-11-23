"""Per-run graph composition and SQL session cleanup."""

from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime


def test_each_graph_uses_its_own_dispatcher():
    first, second = Mock(return_value={"success": True}), Mock(return_value={"success": True})
    plan = PlanGraph(
        plan_id="composition",
        intent="test",
        nodes=[
            WorkflowNode(
                node_id="read",
                tool_id="products",
                action="query",
                params={},
                risk="low",
                idempotent=True,
            )
        ],
    )
    assert XCAGILangGraphRuntime(tool_dispatcher=first).run(plan).success
    assert XCAGILangGraphRuntime(tool_dispatcher=second).run(plan).success
    assert first.call_count == second.call_count == 1


@pytest.mark.parametrize("failure", [RuntimeError, KeyError, TypeError, AssertionError, OSError])
def test_run_repository_closes_and_rolls_back_failed_session(failure):
    session = Mock()
    repo = SQLAlchemyAgentRunRepository(session_factory=lambda: session, auto_create=False)
    error = failure("injected storage failure")
    with pytest.raises(failure) as caught:
        with repo._session_scope():
            raise error
    assert caught.value is error
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()
