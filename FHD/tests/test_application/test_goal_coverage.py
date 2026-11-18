"""Intent-to-plan admission: independent goals, no partial writes, durable graph execution."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.workflow.goal_coverage import GoalCoverage, coverage_error
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.services.tools_execution.registry import get_workflow_tool_registry

MESSAGE = "不要删除 A1，先查询 A1，再查询 B2"


def _response(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def _plan_payload(*, complete=True):
    nodes = [
        {"node_id": "a", "tool_id": "products", "action": "query", "params": {"keyword": "A1"}}
    ]
    if complete:
        nodes.append(
            {
                "node_id": "b",
                "tool_id": "products",
                "action": "query",
                "params": {"keyword": "B2"},
                "depends_on": ["a"],
            }
        )
    return {"mode": "workflow", "intent": "two_queries", "nodes": nodes}


def _review():
    return {
        "goals": [
            {"goal_id": "no_delete", "source": "不要删除 A1", "outcome": "negated", "node_ids": []},
            {"goal_id": "first", "source": "先查询 A1", "outcome": "execute", "node_ids": ["a"]},
            {
                "goal_id": "second",
                "source": "再查询 B2",
                "outcome": "execute",
                "node_ids": ["b"],
                "depends_on": ["first"],
            },
        ],
        "violations": [],
    }


def _graph():
    return PlanGraph(
        plan_id="p",
        intent="queries",
        nodes=[
            WorkflowNode("a", "products", "query", {"keyword": "A1"}),
            WorkflowNode("b", "products", "query", {"keyword": "B2"}, depends_on=["a"]),
        ],
    )


def _planner(completion):
    return LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )


def test_negation_is_scoped_to_its_goal_and_affirmative_tasks_are_preserved():
    review = GoalCoverage.model_validate(_review())
    assert coverage_error(review, _graph(), MESSAGE) is None
    review.goals[0].node_ids = ["a"]
    assert "不得执行" in coverage_error(review, _graph(), MESSAGE)


def test_all_current_goal_dependencies_must_be_present_in_actual_graph():
    graph = _graph()
    graph.nodes[1].depends_on = []
    assert "未保留先后依赖" in coverage_error(
        GoalCoverage.model_validate(_review()), graph, MESSAGE
    )


def test_independent_goals_can_still_run_in_parallel():
    graph, review = _graph(), GoalCoverage.model_validate(_review())
    graph.nodes[1].depends_on = []
    review.goals[2].depends_on = []
    assert coverage_error(review, graph, MESSAGE) is None


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_source",
        "unknown_node",
        "missing_goal_node",
        "unsupported",
        "extra_node",
        "cycle",
        "unknown_goal",
    ],
)
def test_invalid_coverage_never_admits_partial_plan(fault):
    graph, review = _graph(), GoalCoverage.model_validate(_review())
    if fault == "foreign_source":
        review.goals[1].source = "历史消息中的删除任务"
    elif fault == "unknown_node":
        review.goals[1].node_ids = ["invented"]
    elif fault == "missing_goal_node":
        review.goals[1].node_ids = []
    elif fault == "unsupported":
        review.goals[1].outcome, review.goals[1].node_ids = "unsupported", []
    elif fault == "extra_node":
        graph.nodes.append(WorkflowNode("delete", "products", "delete", {"id": 1}))
    elif fault == "cycle":
        review.goals[1].depends_on = ["second"]
    else:
        review.goals[2].depends_on = ["not-a-goal"]
    assert coverage_error(review, graph, MESSAGE)


def test_full_planner_reviews_repaired_graph_and_replans_missing_goal_once():
    missing = _review()
    missing["violations"] = ["漏掉查询 B2；不得只执行 A1"]
    completion = Mock(
        side_effect=[
            _response(_plan_payload(complete=False)),
            _response(missing),
            _response(_plan_payload()),
            _response(_review()),
        ]
    )
    plan = _planner(completion).plan(
        "owner", MESSAGE, get_workflow_tool_registry(), {"session_id": "s1"}
    )
    assert not plan.metadata.get("planning_rejected")
    assert [node.node_id for node in plan.nodes] == ["a", "b"]
    assert plan.nodes[1].depends_on == ["a"]
    assert len(plan.metadata["goal_coverage"]["goals"]) == 3
    requests = [
        json.loads(call.kwargs["messages"][1]["content"]) for call in completion.call_args_list
    ]
    assert requests[1]["task"] == requests[3]["task"] == "audit_goal_coverage"
    assert requests[2]["coverage_feedback"]["error"].startswith("漏掉")
    assert requests[2]["user_message"] == MESSAGE


def test_repeated_semantic_failure_is_bounded_and_never_returns_partial_nodes():
    failure = _review()
    failure["violations"] = ["遗漏查询 B2"]
    completion = Mock(
        side_effect=[_response(_plan_payload(complete=False)), _response(failure)] * 2
    )
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"]
    assert all(node.tool_id == "clarify" for node in plan.nodes)
    assert completion.call_count == 4


@pytest.mark.parametrize(
    "verdict", [None, _response({"goals": [], "violations": []}), _response({"approved": True})]
)
def test_missing_or_malformed_independent_review_fails_closed(verdict):
    completion = Mock(side_effect=[_response(_plan_payload()), verdict])
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"]
    assert "目标" in plan.metadata["rejection_reason"]
    assert completion.call_count == 2


def test_business_reply_cannot_claim_unexecuted_work_completed():
    bad_reply = {"mode": "reply", "reply": "已经完成查询和删除"}
    failure = {
        "goals": [
            {"goal_id": "query", "source": "查询 A1", "outcome": "unsupported", "node_ids": []}
        ],
        "violations": ["无工具结果且用户禁止删除，回复虚构完成"],
    }
    completion = Mock(side_effect=[_response(bad_reply), _response(failure)] * 2)
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"]
    assert all(node.tool_id == "clarify" for node in plan.nodes)


def test_admitted_graph_executes_in_existing_runtime_in_order_without_replay(monkeypatch, tmp_path):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    completion = Mock(side_effect=[_response(_plan_payload()), _response(_review())])
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert not plan.metadata.get("planning_rejected")
    # Isolate external I/O; retain real plan admission, graph, repository and tool executor.
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.AgentToolExecutor",
        lambda: SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor._reviewed_query_tenant",
        lambda *_: (None, None),
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    executed = []

    def execute(tool_id, action, params):
        executed.append(params["keyword"])
        return {"success": True, "data": [{"model_number": params["keyword"]}]}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", execute
    )
    repository = InMemoryAgentRunRepository()
    runtime = AgentOrchestrator(repository=repository)
    run = runtime.start_run_from_plan(user_id="owner", message=MESSAGE, plan=plan)
    assert run.status == "completed"
    assert executed == ["A1", "B2"]
    resumed = AgentOrchestrator(repository=repository).execute_dispatched_run(run.run_id)
    assert resumed.status == "completed" and executed == ["A1", "B2"]


def test_shared_prerequisite_node_does_not_require_a_self_dependency():
    review = GoalCoverage.model_validate(_review())
    review.goals[2].node_ids = ["a", "b"]
    assert coverage_error(review, _graph(), MESSAGE) is None


def test_pure_negation_can_be_acknowledged_without_executing_a_tool():
    graph = PlanGraph(
        plan_id="p",
        intent="ack",
        nodes=[WorkflowNode("reply", "conversation", "reply", {"response": "本次不会删除"})],
    )
    review = GoalCoverage.model_validate(
        {
            "goals": [
                {"goal_id": "no", "source": "不要删除产品A", "outcome": "negated", "node_ids": []}
            ],
            "violations": [],
        }
    )
    assert coverage_error(review, graph, "不要删除产品A") is None


def test_unsupported_goal_may_explain_limit_but_cannot_authorize_partial_work():
    graph = PlanGraph(
        plan_id="p",
        intent="limit",
        nodes=[
            WorkflowNode(
                "reply", "conversation", "reply", {"response": "当前没有该能力，未执行操作"}
            )
        ],
    )
    review = GoalCoverage.model_validate(
        {
            "goals": [
                {
                    "goal_id": "g",
                    "source": "完成此任务",
                    "outcome": "unsupported",
                    "node_ids": ["reply"],
                }
            ],
            "violations": [],
        }
    )
    assert coverage_error(review, graph, "完成此任务") is None
    graph.nodes.append(WorkflowNode("write", "products", "delete", {"id": 1}))
    assert coverage_error(review, graph, "完成此任务")


@pytest.mark.parametrize("choice", [None, [], "invalid", 4])
def test_provider_message_shape_failure_returns_controlled_rejection(choice):
    completion = Mock(side_effect=[_response(_plan_payload()), {"choices": [{"message": choice}]}])
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"]


def test_english_business_request_is_not_exempt_as_smalltalk():
    completion = Mock(side_effect=[_response({"mode": "reply", "reply": "Done"}), None])
    plan = _planner(completion).plan(
        "owner", "Create customer Acme and export orders", get_workflow_tool_registry(), {}
    )
    assert plan.metadata["planning_rejected"]
    assert completion.call_count == 2
    assert (
        json.loads(completion.call_args.kwargs["messages"][1]["content"])["task"]
        == "audit_goal_coverage"
    )


def test_semantic_replan_provider_error_stays_a_controlled_rejection():
    from app.infrastructure.modstore_transport import MarketModelError

    failure = _review()
    failure["violations"] = ["遗漏查询 B2"]
    completion = Mock(
        side_effect=[
            _response(_plan_payload(complete=False)),
            _response(failure),
            MarketModelError({"status": 502}),
        ]
    )
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"]
    assert completion.call_count == 3


def test_graph_changed_after_review_is_not_admitted(monkeypatch):
    from app.application.workflow import planner as module

    decorate = module.apply_clarification
    completion = Mock(side_effect=[_response(_plan_payload()), _response(_review())])

    def changed(candidate, *args, **kwargs):
        result = decorate(candidate, *args, **kwargs)
        if "goal_coverage" in candidate.metadata:
            candidate.nodes[0].params["keyword"] = "another customer"
        return result

    monkeypatch.setattr(module, "apply_clarification", changed)
    plan = _planner(completion).plan("owner", MESSAGE, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"]
    assert "核对后的计划发生变化" in plan.metadata["rejection_reason"]
