"""Tests for workflow engine ``state.update`` streaming events.

验证 WorkflowEngine 在每步节点完成后（含成功与失败）都会回调
``{"type":"state.update","node_id","status","output_summary"}``，
当前聊天通过统一 AgentRun 的 node_results 和持久化事件投影状态。
"""

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import Branch, PlanGraph, WorkflowNode
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime as WorkflowEngine
from tests.test_application.ai_chat_test_helpers import _make_svc


def _engine(dispatch_result):
    def mock_dispatch(tool_id, action, params):
        return dict(dispatch_result)

    return WorkflowEngine(tool_dispatcher=mock_dispatch)


def _plan(nodes):
    return PlanGraph(
        plan_id="p_state",
        intent="test_state_update",
        todo_steps=["s1"],
        nodes=nodes,
        risk_level="low",
    )


def _node(node_id, tool_id="products", action="query", depends_on=None, risk="low"):
    return WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params={},
        risk=risk,
        idempotent=True,
        depends_on=depends_on or [],
    )


class TestWorkflowStateUpdate:
    def test_emits_state_update_on_success(self):
        events = []
        engine = _engine({"success": True, "data": []})
        engine.run(
            _plan([_node("n1")]),
            state_event_callback=events.append,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "state.update"
        assert ev["node_id"] == "n1"
        assert ev["status"] == "succeeded"
        assert "output_summary" in ev

    def test_emits_state_update_on_failure_status_failed(self):
        events = []
        engine = _engine({"success": False, "message": "boom"})
        result = engine.run(
            _plan([_node("n1")]),
            state_event_callback=events.append,
        )
        assert result.success is False
        assert len(events) == 1
        assert events[0]["status"] == "failed"
        assert events[0]["node_id"] == "n1"

    def test_emits_in_execution_order_for_sequential_nodes(self):
        events = []
        engine = _engine({"success": True, "data": []})
        engine.run(
            _plan(
                [
                    _node("n1"),
                    _node("n2", depends_on=["n1"]),
                    _node("n3", depends_on=["n2"]),
                ]
            ),
            state_event_callback=events.append,
        )
        assert [e["node_id"] for e in events] == ["n1", "n2", "n3"]
        assert all(e["type"] == "state.update" for e in events)
        assert all(e["status"] == "succeeded" for e in events)

    def test_emits_for_conditional_router_node(self):
        # 条件边 router 节点（branches）执行后同样应触发 state.update。
        events = []
        engine = _engine({"success": True, "data": []})
        node = WorkflowNode(
            node_id="router",
            tool_id="router",
            action="route",
            params={},
            risk="low",
            branches=[
                Branch(condition={"key": "kind", "equals": "a"}, target="ta"),
                Branch(condition={"key": "kind", "equals": "b"}, target="tb"),
            ],
        )
        targets = [
            WorkflowNode(node_id=target, tool_id="router", action="route")
            for target in ("ta", "tb")
        ]
        engine.run(_plan([node, *targets]), state_event_callback=events.append)
        assert any(e["node_id"] == "router" for e in events)
        assert not any(e["node_id"] in {"ta", "tb"} for e in events)

    def test_callback_from_constructor_used_when_run_has_none(self):
        collected = []
        engine = WorkflowEngine(tool_dispatcher=lambda *_args, **_kw: {"success": True, "data": []})
        engine.run(_plan([_node("n1")]), state_event_callback=collected.append)
        assert len(collected) == 1
        assert collected[0]["node_id"] == "n1"

    def test_run_callback_overrides_constructor(self):
        ctor_events = []
        run_events = []
        engine = WorkflowEngine(tool_dispatcher=lambda *_args, **_kw: {"success": True, "data": []})
        engine.run(_plan([_node("n1")]), state_event_callback=run_events.append)
        assert len(run_events) == 1
        assert ctor_events == []

    def test_no_callback_no_side_effect(self):
        engine = _engine({"success": True, "data": []})
        result = engine.run(_plan([_node("n1")]))
        assert result.success is True

    def test_callback_exception_does_not_break_run(self):
        def boom(_ev):
            raise RuntimeError("callback failed")

        engine = _engine({"success": True, "data": []})
        result = engine.run(_plan([_node("n1")]), state_event_callback=boom)
        assert result.success is True
        assert len(result.node_results) == 1


class TestAiChatProjectsRunState:
    @pytest.mark.parametrize("status", ["completed", "failed"])
    def test_workflow_response_projects_authoritative_step_state(self, status):
        plan = _plan([_node("n1")])
        run = AgentRun(user_id="state-test", message="query", status=status)
        run.steps = [
            AgentStep(
                node_id="n1",
                tool_id="products",
                action="query",
                status=status,
                output={"success": status == "completed", "data": []},
                error="private failure" if status == "failed" else "",
            )
        ]
        payload = _make_svc()._format_agent_run_response(plan, run)
        projected = payload["data"]["data"]["node_results"]
        assert projected[0]["node_id"] == "n1"
        assert projected[0]["success"] is (status == "completed")
        assert payload["data"]["data"]["agent_status"] == status
        assert payload["run_id"] == run.run_id
        assert "private failure" not in str(payload)

    def test_unified_run_retains_completion_event_for_frontend(self):
        from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
        from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

        repository = InMemoryAgentRunRepository()
        orchestrator = AgentOrchestrator(repository=repository)
        plan = _plan(
            [
                WorkflowNode(
                    node_id="model_reply",
                    tool_id="conversation",
                    action="reply",
                    params={"response": "说明"},
                    idempotent=True,
                )
            ]
        )
        plan.metadata = {"response_mode": "reply", "reply": "说明"}
        run = orchestrator.start_run_from_plan(user_id="state-test", message="说明", plan=plan)
        assert run.status == "completed", (run.error, run.final_output)
        assert run.steps[0].status == "completed"
        events = orchestrator.list_events(run.run_id)
        assert events[-1].event_type == "run.completed"
        assert all(event.run_id == run.run_id for event in events)
        assert repository.get(run.run_id).final_output["response"] == "说明"
