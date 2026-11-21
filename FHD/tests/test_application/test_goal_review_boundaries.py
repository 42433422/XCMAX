"""Goal admission stays bound to reviewed data and reports the actual failure."""

import json
from unittest.mock import Mock

import pytest

from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.infrastructure.modstore_transport import MarketModelError
from app.services.tools_execution.registry import get_workflow_tool_registry
from tests.fixtures.planner_model import goal_review_response


def _response(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def _planned():
    return _response(
        {
            "mode": "workflow",
            "intent": "query",
            "nodes": [
                {
                    "node_id": "a",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "A1"},
                }
            ],
        }
    )


def _review(*, incomplete=False, clarification_question=None):
    return _response(
        {
            "goals": [
                {"goal_id": "first", "source": "查询A1", "outcome": "execute", "node_ids": ["a"]}
            ],
            "violations": ["遗漏第二项要求 internal_review_trace"] if incomplete else [],
            "clarification_question": clarification_question,
        }
    )


def _planner(completion):
    return LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )


@pytest.mark.parametrize(
    "shape", ["unbound", "reordered", "per_file", "foreign", "subset", "conditional"]
)
def test_batch_execute_binds_verified_selection_before_goal_review(shape):
    names = ["a.xlsx", "b.xlsx"]
    files = [{"id": str(i), "name": name, "suffix": ".xlsx"} for i, name in enumerate(names)]
    context = {
        "artifact_ids": [file["id"] for file in files],
        "file_context": {"attachment_manifest": files},
    }
    node = {"node_id": "import", "tool_id": "elt_import", "action": "execute"}
    params = {
        "unbound": {},
        "reordered": {"file_paths": names[::-1], "valid_rows_only": True},
        "per_file": {"file_paths": names[:1]},
        "foreign": {"file_paths": [*names, "outside.xlsx"]},
        "subset": {"file_paths": names[:1]},
        "conditional": {"file_paths": names},
    }[shape]
    nodes = [{**node, "params": params}]
    if shape == "per_file":
        nodes.append({**node, "node_id": "second", "params": {"file_paths": names[1:]}})
    if shape == "conditional":
        nodes[0]["branches"] = [{"target": "second", "condition": {"key": "ok", "value": True}}]
        nodes.append({**node, "node_id": "second", "params": {"file_paths": names[1:]}})
    admitted = shape in {"unbound", "reordered", "per_file"}
    completion = Mock(
        side_effect=[
            _response({"mode": "workflow", "nodes": nodes}),
            _response(
                {
                    "goals": [
                        {
                            "goal_id": "batch",
                            "source": "导入",
                            "outcome": "execute",
                            "node_ids": ["import"],
                        }
                    ],
                    "violations": [],
                }
            )
            if admitted
            else _response({"unknown": True}),
        ]
        + ([] if admitted else [_response({"unknown": True})])
    )
    plan = _planner(completion).plan("owner", "导入", get_workflow_tool_registry(), context)
    if admitted:
        audited = json.loads(completion.call_args.kwargs["messages"][-1]["content"])
        assert audited["task"] == "audit_goal_coverage"
        assert len(audited["plan"]["nodes"]) == 1
        assert audited["plan"]["nodes"][0]["params"] == {"file_paths": names}
        assert len(plan.nodes) == 1 and plan.nodes[0].params == {"file_paths": names}
    else:
        assert plan.metadata["planning_rejected"] is True
        assert plan.metadata["planning_failure_kind"] == "plan_repair_failed"
        assert completion.call_count == 3
        assert plan.metadata["plan_repair"]["attempts"] == 2
        repairs = [
            json.loads(call.kwargs["messages"][-1]["content"])
            for call in completion.call_args_list[1:]
        ]
        assert all(request["task"] != "audit_goal_coverage" for request in repairs)
        assert all(
            [node["params"] for node in request["original_plan"]["nodes"]]
            == [node["params"] for node in nodes]
            for request in repairs
        )
        assert not plan.nodes  # A rejected graph cannot create a fresh clarification wait.
        callbacks, risk = Mock(), Mock()
        callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
        result = PlannedWorkflowDispatch(
            {}, callbacks, Mock(plan=Mock(return_value=plan)), risk, Mock()
        ).handle("owner", "导入", "chat", context, "导入")
        assert result["success"] is False
        assert result["execution"]["outcome"] == "not_executed"
        risk.evaluate.assert_not_called()
        callbacks._capture_agent_run_interaction.assert_not_called()


@pytest.mark.parametrize("params", [{}, {"answer_key": "confirmed", "target_node_id": ""}])
@pytest.mark.parametrize("with_business_node", [False, True])
def test_only_a_standalone_model_question_can_skip_goal_review(with_business_node, params):
    question = "你要清理当前企业的业务记录，还是重置本地数据库？"
    nodes = [
        {
            "node_id": "scope",
            "tool_id": "clarify",
            "action": "ask",
            "params": {"question": question, **params},
        }
    ]
    if with_business_node:
        nodes.append({"node_id": "write", "tool_id": "products", "action": "clear", "params": {}})
    completion = Mock(side_effect=[_response({"mode": "workflow", "nodes": nodes}), None, None])
    plan = _planner(completion).plan("owner", "清空数据库", get_workflow_tool_registry())
    if with_business_node:
        assert plan.metadata["planning_rejected"] is True
        assert plan.metadata["planning_failure_kind"] == "goal_review_unavailable"
        assert not plan.metadata.get("goal_coverage_rejected")
        assert completion.call_count == 3
        assert plan.metadata["goal_coverage_trace"]["attempts"] == 2
        reviews = [
            json.loads(call.kwargs["messages"][-1]["content"])
            for call in completion.call_args_list[1:]
        ]
        assert all(request["task"] == "audit_goal_coverage" for request in reviews)
        assert all(
            [(node["tool_id"], node["action"]) for node in request["plan"]["nodes"]]
            == [("clarify", "ask"), ("products", "clear")]
            for request in reviews
        )
        assert not plan.nodes  # A rejected graph cannot create a fresh clarification wait.
        callbacks, risk = Mock(), Mock()
        callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
        result = PlannedWorkflowDispatch(
            {}, callbacks, Mock(plan=Mock(return_value=plan)), risk, Mock()
        ).handle("owner", "清空数据库", "chat", {}, "清空数据库")
        assert result["success"] is False
        assert result["execution"]["outcome"] == "not_executed"
        risk.evaluate.assert_not_called()
        callbacks._capture_agent_run_interaction.assert_not_called()
    else:
        assert completion.call_count == 1
        assert plan.metadata["planning_clarification"] is True
        assert [(node.tool_id, node.action) for node in plan.nodes] == [("clarify", "ask")]
        assert plan.nodes[0].params["question"] == question


def test_short_scope_answer_supplies_authorized_history_to_independent_review():
    calls = []
    history = [
        {"role": "user", "content": "清理全部知识库和整个本地数据库"},
        {"role": "assistant", "content": "你要重置整个本地数据库吗？"},
    ]
    reply = "可以生成知识库清理计划。工具目录没有整库重置操作。"

    def complete(**kwargs):
        request = json.loads(kwargs["messages"][-1]["content"])
        calls.append(request)
        assert request["user_message"] == "全部的"
        if request["task"] == "audit_reply":
            assert request["conversation_history"] == history
            assert "prior_conversation" not in request["context"]
            assert request["reply"] == reply
            return _response({"violations": []})
        assert request["recent_messages"] == history
        assert "prior_conversation" not in request["context"]
        assert any("整库重置" in rule for rule in request["rules"])
        return _response({"mode": "reply", "reply": reply})

    plan = _planner(complete).plan(
        "owner",
        "全部的",
        get_workflow_tool_registry(),
        {
            "session_id": "session",
            "local_user_id": "1",
            "_chat_evidence_authorized": True,
            "_chat_history_messages": history,
            "prior_conversation": [{"role": "user", "content": "untrusted"}],
        },
    )
    assert len(calls) == 2
    assert plan.metadata["reply"] == reply
    assert plan.metadata["goal_coverage"]["goals"][0]["outcome"] == "reply"
    assert [(node.tool_id, node.action) for node in plan.nodes] == [("conversation", "reply")]


def test_rejected_business_plan_preserves_a_durable_question_without_business_nodes():
    question = "你要清理当前企业的数据，还是重置整个本地数据库？"
    message = "清理全部知识库和数据库和模板库"
    candidate = _response(
        {"mode": "workflow", "nodes": [{"node_id": "a", "tool_id": "products", "action": "clear"}]}
    )
    review = _response(
        {
            "goals": [
                {"goal_id": "first", "source": "数据库", "outcome": "unsupported", "node_ids": []}
            ],
            "violations": ["仅清空产品没有覆盖全部范围"],
            "clarification_question": question,
        }
    )
    completion = Mock(side_effect=[candidate, review])
    plan = _planner(completion).plan("owner", message, get_workflow_tool_registry())
    assert completion.call_count == 2
    assert plan.metadata["planning_clarification"] is True
    assert [(node.tool_id, node.action) for node in plan.nodes] == [("clarify", "ask")]
    assert plan.nodes[0].params["question"] == question


@pytest.mark.parametrize("violations", [[], ["缺少查询对象"]])
def test_reply_review_question_enters_durable_clarification_even_without_violations(violations):
    question = "请提供要查询的客户名称。"
    completion = Mock(
        side_effect=[
            _response({"mode": "reply", "reply": question}),
            _response({"violations": violations, "clarification_question": question}),
        ]
    )
    plan = _planner(completion).plan("owner", "查询客户资料", get_workflow_tool_registry())
    assert completion.call_count == 2
    assert plan.metadata["planning_clarification"] is True
    assert not plan.metadata.get("planning_rejected")
    assert [(node.tool_id, node.action) for node in plan.nodes] == [("clarify", "ask")]
    assert plan.nodes[0].params["question"] == question
    assert json.loads(completion.call_args.kwargs["messages"][-1]["content"])["task"] == (
        "audit_reply"
    )


@pytest.mark.parametrize("clarification_question", [None, "   "])
def test_valid_review_rejection_is_not_reported_as_a_provider_outage(clarification_question):
    completion = Mock(
        side_effect=[
            _planned(),
            _review(incomplete=True, clarification_question=clarification_question),
        ]
        * 2
    )
    plan = _planner(completion).plan("owner", "先查询A1，再查询B2", get_workflow_tool_registry())
    assert plan.metadata["goal_coverage_rejected"] is True
    assert plan.metadata["planning_unavailable"] is False
    callbacks, risk = Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    planner = Mock(plan=Mock(return_value=plan))
    result = PlannedWorkflowDispatch({}, callbacks, planner, risk, Mock()).handle(
        "owner", "先查询A1，再查询B2", "chat", {}, "先查询A1，再查询B2"
    )
    assert result["success"] is False
    assert result["data"]["error_code"] == "workflow_goal_coverage_rejected"
    assert result["execution"]["outcome"] == "not_executed"
    assert "先后顺序" in result["response"] and "检查模型连接" not in result["response"]
    assert "internal_review_trace" not in json.dumps(result, ensure_ascii=False)
    risk.evaluate.assert_not_called()


def test_replan_provider_failure_keeps_the_provider_failure_classification():
    completion = Mock(
        side_effect=[
            _planned(),
            _review(incomplete=True),
            MarketModelError({"status": 402}),
        ]
    )
    plan = _planner(completion).plan("owner", "先查询A1，再查询B2", get_workflow_tool_registry())
    assert plan.metadata["planning_rejected"] is True
    assert plan.metadata["planning_unavailable"] is True
    assert not plan.metadata.get("goal_coverage_rejected")
    assert "余额不足" in plan.metadata["rejection_reason"]
    assert completion.call_count == 3


def _legacy_import_graph():
    return PlanGraph(
        plan_id="legacy-import",
        intent="import",
        risk_level="high",
        nodes=[
            WorkflowNode(
                "import",
                "import_excel_to_database",
                "import",
                {"file_path": "owned.xlsx", "import_type": "customers", "confirm": True},
                risk="high",
            )
        ],
    )


@pytest.mark.parametrize("native", [False, True])
def test_retired_import_is_rejected_before_goal_review_and_dispatch(native):
    message = "将 owned.xlsx 导入客户库"
    graph = plan_to_dict(_legacy_import_graph())
    payload = {"mode": "workflow", "risk_level": "high", "nodes": graph["nodes"]}
    requests = []

    def complete(**kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        requests.append(request)
        if request["task"] == "audit_goal_coverage":
            return goal_review_response(
                request, source=message, node_ids=["import"], outcome="execute"
            )
        if native and len(requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "SubmitWorkflowPlan",
                                        "arguments": json.dumps(payload),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        # A shape repair must not reintroduce the retired operation either.
        return _response(payload)

    callbacks, risk = Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    result = PlannedWorkflowDispatch({}, callbacks, _planner(complete), risk, Mock()).handle(
        "owner", message, "chat", {}, message
    )
    assert result["success"] is False
    assert result["execution"]["outcome"] == "not_executed"
    assert not any(request["task"] == "audit_goal_coverage" for request in requests)
    assert any("import_excel_to_database" in str(request.get("error")) for request in requests)
    risk.evaluate.assert_not_called()
    callbacks._capture_agent_run_interaction.assert_not_called()


def test_persisted_retired_import_cannot_resume_even_with_complete_confirmed_params():
    from app.application.agent_orchestrator import (
        AgentOrchestrator,
        AgentRun,
        AgentStep,
        InMemoryAgentRunRepository,
    )

    plan = _legacy_import_graph()
    error = validate_required_params(plan, get_workflow_tool_registry())
    assert "import_excel_to_database" in error and "ELT" in error
    node = plan.nodes[0]
    repository, executor = InMemoryAgentRunRepository(), Mock()
    pending = AgentRun(
        user_id="owner",
        message="将 owned.xlsx 导入客户库",
        plan_id=plan.plan_id,
        status="waiting_user",
        steps=[
            AgentStep(
                node.node_id,
                node.tool_id,
                node.action,
                dict(node.params),
                risk="high",
                status="waiting_user",
            )
        ],
        metadata={"plan": plan_to_dict(plan)},
    )
    repository.save(pending)
    resumed = AgentOrchestrator(repository=repository, tool_executor=executor).continue_run(
        pending.run_id, approved_by="owner", approved_step_id=node.node_id
    )
    assert resumed.status == "blocked"
    assert "approval.resume_plan_rejected" in [event.event_type for event in resumed.events]
    assert resumed.steps[0].params == node.params
    assert resumed.tool_calls == []
    executor.execute.assert_not_called()
    executor.execute_with_deadline.assert_not_called()


def test_elt_preview_and_dependent_execution_remain_valid():
    plan = PlanGraph(
        plan_id="elt-import",
        intent="import",
        nodes=[
            WorkflowNode("preview", "elt_import", "preview", {"file_path": "owned.xlsx"}),
            WorkflowNode(
                "execute",
                "elt_import",
                "execute",
                {"run_id": "{{preview.data.run_id}}"},
                depends_on=["preview"],
            ),
        ],
    )
    assert validate_required_params(plan, get_workflow_tool_registry()) is None
    assert plan.nodes[1].depends_on == ["preview"]
