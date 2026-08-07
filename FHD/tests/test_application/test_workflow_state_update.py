"""Tests for workflow engine ``state.update`` streaming events.

验证 WorkflowEngine 在每步节点完成后（含成功与失败）都会回调
``{"type":"state.update","node_id","status","output_summary"}``，
且 AIChatApplicationService 能把该事件列表收集并透传到响应体供前端消费。
"""

from unittest.mock import MagicMock

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import Branch, PlanGraph, WorkflowNode


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
        engine.run(_plan([node]), state_event_callback=events.append)
        assert any(e["node_id"] == "router" for e in events)

    def test_callback_from_constructor_used_when_run_has_none(self):
        collected = []
        engine = WorkflowEngine(
            tool_dispatcher=lambda **kw: {"success": True, "data": []},
            state_event_callback=collected.append,
        )
        engine.run(_plan([_node("n1")]))
        assert len(collected) == 1
        assert collected[0]["node_id"] == "n1"

    def test_run_callback_overrides_constructor(self):
        ctor_events = []
        run_events = []
        engine = WorkflowEngine(
            tool_dispatcher=lambda **kw: {"success": True, "data": []},
            state_event_callback=ctor_events.append,
        )
        engine.run(_plan([_node("n1")]), state_event_callback=run_events.append)
        assert len(run_events) == 1
        # 无 explicit run 回调时回退到构造函数回调
        engine.run(_plan([_node("n2")]))
        assert len(ctor_events) == 1
        assert ctor_events[0]["node_id"] == "n2"

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


class TestAiChatCollectsStateUpdates:
    def test_workflow_response_attaches_state_updates(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        state_updates = [
            {"type": "state.update", "node_id": "n1", "status": "succeeded", "output_summary": "ok"}
        ]
        svc = AIChatApplicationService.__new__(AIChatApplicationService)
        plan = _plan([_node("n1")])
        run_result = MagicMock()
        run_result.success = True
        run_result.message = "完成"
        run_result.node_results = []
        run_result.final_context = {}
        payload = svc._format_workflow_run_response(
            plan,
            run_result,
            state_updates=state_updates,
        )
        assert payload["data"]["data"]["state_updates"] == state_updates

    def test_run_workflow_with_state_updates_collects(self):
        from app.application import ai_chat_app_service as mod

        svc = mod.AIChatApplicationService.__new__(mod.AIChatApplicationService)
        engine = _engine({"success": True, "data": []})
        svc.workflow_engine = engine
        plan = _plan([_node("n1"), _node("n2", depends_on=["n1"])])
        run_result, events = svc._run_workflow_with_state_updates(
            plan=plan, runtime_context={}, max_retries=1
        )
        assert run_result.success is True
        assert [e["node_id"] for e in events] == ["n1", "n2"]
        assert all(e["type"] == "state.update" for e in events)
