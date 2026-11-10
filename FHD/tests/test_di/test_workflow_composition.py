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


def test_run_repository_closes_and_rolls_back_failed_session():
    session = Mock()
    repo = SQLAlchemyAgentRunRepository(session_factory=lambda: session, auto_create=False)
    with pytest.raises(RuntimeError):
        with repo._session_scope():
            raise RuntimeError("injected storage failure")
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()
