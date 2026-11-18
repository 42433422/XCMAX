"""Tests for app.application.workflow.planner — coverage ramp."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _filter_tool_registry_for_profile,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry as get_tool_registry
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.planner_model import goal_review_response

# ========================= get_tool_registry =============================


def test_planner_token_budget_is_configurable_for_reasoning_models(monkeypatch):
    from app.application.workflow.planner_llm_gateway import planner_max_tokens

    monkeypatch.delenv("XCAGI_PLANNER_MAX_TOKENS", raising=False)
    assert planner_max_tokens() == 4096
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", "8192")
    assert planner_max_tokens() == 8192
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", "not-a-number")
    assert planner_max_tokens() == 4096


def test_plan_schema_flags_workflow_without_nodes():
    from app.application.workflow.llm_plan_generation import model_plan_schema_error

    assert "nodes" in (model_plan_schema_error({"mode": "workflow"}) or "")
    assert "reply" in (model_plan_schema_error({"mode": "reply"}) or "")
    assert (
        model_plan_schema_error(
            {
                "mode": "workflow",
                "nodes": [{"tool_id": "products", "action": "query", "params": {}}],
            }
        )
        is None
    )


def test_planner_repairs_workflow_output_without_nodes():
    replies = [
        json.dumps({"mode": "workflow"}),
        json.dumps(
            {
                "mode": "workflow",
                "intent": "查询产品 A1",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {"keyword": "A1"},
                    }
                ],
            }
        ),
    ]
    responses = iter(replies)

    def scripted_completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        if payload.get("task") == "audit_goal_coverage":
            return goal_review_response(
                payload, source="查询产品 A1", node_ids=["n1"], outcome="execute"
            )
        return {"choices": [{"message": {"content": next(responses)}}]}

    completion = Mock(side_effect=scripted_completion)
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )

    plan = planner.plan("7", "查询产品 A1", get_tool_registry(), {"source": "normal"})

    assert plan is not None
    assert [node.tool_id for node in plan.nodes] == ["products"]
    assert completion.call_count == 3


def test_planner_does_not_mix_global_history_into_an_explicit_conversation():
    captured = {}
    ai = Mock()
    ai.get_context.return_value.conversation_history = [
        {"role": "assistant", "content": "FOREIGN_SESSION_MARKER"}
    ]

    def completion(**kwargs):
        captured.update(json.loads(kwargs["messages"][1]["content"]))
        return {"choices": [{"message": {"content": '{"mode":"reply","reply":"ready"}'}}]}

    LLMWorkflowPlanner(ai_service=ai, completion=completion).plan(
        "7", "hello", get_tool_registry(), context={"session_id": "isolated-conversation"}
    )
    assert "FOREIGN_SESSION_MARKER" not in json.dumps(captured["recent_messages"])


@pytest.mark.parametrize("light_reply", [False, True])
def test_long_history_keeps_latest_constraints_in_order(light_reply, monkeypatch, tmp_path):
    from app.application.workflow.llm_plan_generation import LlmPlanGeneration

    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    captured = {}

    def completion(**kwargs):
        captured.update(json.loads(kwargs["messages"][1]["content"]))
        return {"choices": [{"message": {"content": '{"mode":"reply","reply":"ready"}'}}]}

    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": "旧说明" * 3000}
        for index in range(4)
    ] + [
        {"role": "user", "content": "最新约束：保持金额。api_key=history-secret"},
        {"role": "assistant", "content": "最新确认：金额保持。Bearer private-history-token"},
    ]
    context = {
        "local_user_id": 31,
        "tenant_id": 5,
        "conversation_id": "long-owned-history",
        "_chat_evidence_authorized": True,
        "chat_owned_history": history,
    }
    generator = LlmPlanGeneration(Mock(get_context=Mock(return_value=None)), completion, Mock())
    plan = (
        generator._light_reply("p1", "你好", context)
        if light_reply
        else generator.generate("p1", "31", "查询客户", {}, context)
    )

    assert plan is not None
    recent = captured["recent_messages"]
    assert [item["role"] for item in recent[-2:]] == ["user", "assistant"]
    assert recent[-2]["content"].startswith("最新约束：保持金额。")
    assert recent[-1]["content"].startswith("最新确认：金额保持。")
    serialized = json.dumps(captured, ensure_ascii=False)
    assert "history-secret" not in serialized
    assert "private-history-token" not in serialized
    if not light_reply:
        assert captured["context"]["chat_owned_history"][-1] == recent[-1]


def test_employee_discovery_uses_verified_actor_and_replaces_client_catalog(
    monkeypatch, trusted_actor
):
    actor = trusted_actor(user_id=77, role="user")
    monkeypatch.setattr(
        "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
        lambda: {
            "employee_pack_tools": [
                {"pack_id": "known-report-worker", "runtime_ok": True},
                {"pack_id": "broken-worker", "runtime_ok": False},
                # 宿主管理员工：非平台管理员不可执行，不能出现在规划器选项里。
                {"pack_id": "user-customer-service-officer", "runtime_ok": True},
            ]
        },
    )
    captured = {}
    ai = Mock()
    ai.get_context.return_value = None
    planner = LLMWorkflowPlanner(
        ai_service=ai,
        completion=lambda **kwargs: goal_review_response(
            json.loads(kwargs["messages"][1]["content"]),
            source="介绍报表处理方式",
            node_ids=["reply"],
            outcome="reply",
        ),
    )

    def model(plan_id, user_id, message, registry, context):
        captured.update(context)
        return PlanGraph(
            plan_id=plan_id,
            intent="conversation_reply",
            nodes=[
                WorkflowNode(
                    node_id="reply",
                    tool_id="conversation",
                    action="reply",
                    params={"response": "ready"},
                )
            ],
            metadata={"response_mode": "reply", "reply": "ready"},
        )

    monkeypatch.setattr(planner, "_plan_with_llm", model)
    planner.plan(
        "77",
        "介绍报表处理方式",
        get_tool_registry(),
        context={**actor.context, "available_employees": [{"employee_id": "forged-worker"}]},
    )
    assert [row["employee_id"] for row in captured["available_employees"]] == [
        "known-report-worker"
    ]
    captured.clear()
    planner.plan(
        "untrusted",
        "介绍报表处理方式",
        get_tool_registry(),
        context={"available_employees": [{"employee_id": "forged-worker"}]},
    )
    # The second prompt must not receive either a forged catalog or an unauthenticated discovery.
    assert "available_employees" not in captured


class TestGetToolRegistry:
    def test_returns_dict(self):
        reg = get_tool_registry()
        assert isinstance(reg, dict)
        assert "products" in reg
        assert "customers" in reg
        assert "shipment_orders" in reg

    def test_tool_has_actions(self):
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


# ========================= _filter_tool_registry_for_profile =============


class TestFilterToolRegistryForProfile:
    def test_normal_removes_pro_only(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "pro_only",
                "actions": {"exec": {"availability": "pro_only", "risk": "high"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_pro_default_removes_normal_only(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "normal_only",
                "actions": {"slot": {"availability": "normal_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "pro_default")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_shared_kept_in_both(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
        }
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "pro_default")

    def test_action_level_filtering(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {
                    "query": {"availability": "shared", "risk": "low"},
                    "admin": {"availability": "pro_only", "risk": "high"},
                },
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "query" in result["tool_a"]["actions"]
        assert "admin" not in result["tool_a"]["actions"]

    def test_non_dict_spec_skipped(self):
        reg = {"bad": "not a dict"}
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad" not in result

    def test_empty_actions_skipped(self):
        reg = {
            "tool_a": {
                "availability": "pro_only",
                "actions": {"query": {"availability": "pro_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" not in result


class TestPlanWithLLM:
    def test_reply_rejects_unexpected_tool_calls(self):
        from app.application.workflow.llm_plan_generation import _decode_completion

        content = json.dumps({"mode": "reply", "reply": "这是说明。"}, ensure_ascii=False)
        assert _decode_completion({"choices": [{"message": {"content": content}}]}) is not None
        for field in ("tool_calls", "function_call"):
            result = {"choices": [{"message": {"content": content, field: [{"name": "write"}]}}]}
            assert _decode_completion(result) is None

    def test_auxiliary_model_task_reuses_the_configured_planner_provider(self):
        ai_service = Mock()
        result_payload = {"choices": [{"message": {"content": "{}"}}]}
        completion = Mock(return_value=result_payload)
        planner = LLMWorkflowPlanner(ai_service=ai_service, completion=completion)
        messages = [{"role": "user", "content": "map columns"}]
        context = {"tenant_id": 17}

        result = planner.complete_messages(
            messages=messages,
            context=context,
            temperature=0,
            max_tokens=300,
        )

        assert result is result_payload
        assert completion.call_args.kwargs["ai_service"] is ai_service
        assert completion.call_args.kwargs["messages"] == messages
        assert completion.call_args.kwargs["context"] == context
        assert completion.call_args.kwargs["temperature"] == 0
        assert completion.call_args.kwargs["max_tokens"] == 300

    def test_planner_receives_current_conversation_history_without_turn_classifier(
        self, monkeypatch, tmp_path
    ):
        from app.application.ai_chat.dialogue_memory import prepare_chat_turn, settle_chat_turn

        monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
        captured = {}

        def completion(**kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            if payload.get("task") == "audit_goal_coverage":
                return goal_review_response(
                    payload, source="你好", node_ids=["model_reply"], outcome="reply"
                )
            captured.update(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"mode": "reply", "reply": "这是同一会话的回复。"},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        context = {
            "local_user_id": 31,
            "tenant_id": 5,
            "conversation_id": "unified-session",
            "turn_id": "current",
        }
        previous = {**context, "turn_id": "previous"}
        assert prepare_chat_turn("查一下客户", previous) is None
        settle_chat_turn(
            "查一下客户",
            previous,
            {"success": True, "response": "上一轮已查询到客户记录。"},
            "completed",
        )
        assert prepare_chat_turn("你好", context) is None

        ai_service = Mock()
        ai_service.get_context.return_value = None
        plan = LLMWorkflowPlanner(ai_service=ai_service, completion=completion).plan(
            "owner", "你好", get_tool_registry(), context=context
        )

        assert plan.metadata["response_mode"] == "reply"
        assert captured["recent_messages"] == [
            {"role": "user", "content": "查一下客户"},
            {"role": "assistant", "content": "上一轮已查询到客户记录。"},
        ]

    def test_plan_prompt_receives_current_memory_and_authorized_knowledge(self):
        captured = {}

        def completion(**kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            if payload.get("task") == "audit_goal_coverage":
                return goal_review_response(
                    payload, source="查那个客户", node_ids=["query_customer"], outcome="execute"
                )
            captured.update(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "customer_query",
                                    "todo_steps": ["查询客户"],
                                    "risk_level": "low",
                                    "nodes": [
                                        {
                                            "node_id": "query_customer",
                                            "tool_id": "customers",
                                            "action": "query",
                                            "params": {"keyword": "宗南"},
                                            "risk": "low",
                                            "idempotent": True,
                                            "description": "查询客户",
                                            "depends_on": [],
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            }

        ai_service = Mock()
        ai_service.get_context.return_value = None
        planner = LLMWorkflowPlanner(ai_service=ai_service, completion=completion)
        context = {
            "recent_messages": [{"role": "user", "content": "之前提到宗南账单"}],
            "chat_knowledge_evidence": [
                {"dataset": "business-documents", "source": "宗南账单.xlsx", "text": "订单 SO-91"}
            ],
            "_chat_evidence_authorized": True,
            "tenant_id": 2,
        }

        plan = planner.plan(
            "owner-41",
            "查那个客户",
            get_tool_registry(),
            context=context,
        )

        assert plan.nodes
        model_context = captured["context"]
        assert model_context["recent_messages"][0]["content"] == "之前提到宗南账单"
        assert model_context["chat_knowledge_evidence"][0]["text"] == "订单 SO-91"
        assert "_chat_evidence_authorized" not in model_context
        assert "tenant_id" not in model_context

    def test_no_api_key_returns_none(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
        assert result is None

    def test_llm_returns_valid_plan(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "product_query",
                                "todo_steps": ["查询产品"],
                                "risk_level": "low",
                                "nodes": [
                                    {
                                        "node_id": "n1",
                                        "tool_id": "products",
                                        "action": "query",
                                        "params": {"keyword": "test"},
                                        "risk": "low",
                                        "idempotent": True,
                                        "description": "查询产品",
                                        "depends_on": [],
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "test-key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "test-model"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            with patch(
                "app.application.workflow.planner.request_planner_completion",
                return_value=mock_response.json() if mock_response.status_code < 400 else None,
            ):
                planner = LLMWorkflowPlanner()
                result = planner._plan_with_llm("p1", "u1", "查询产品", get_tool_registry(), {})

        assert result is not None
        assert result.intent == "product_query"
        assert len(result.nodes) == 1

    def test_same_model_can_select_reply_and_reply_runs_through_langgraph(self):
        from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch

        def completion(**_kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"mode": "reply", "reply": "你好，我可以帮你查询业务数据。"},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        ai_service = Mock()
        ai_service.get_context.return_value = None
        planner = LLMWorkflowPlanner(ai_service=ai_service, completion=completion)
        plan = planner.plan("owner", "你好", get_tool_registry(), context={})

        assert plan.metadata["response_mode"] == "reply"
        assert len(plan.nodes) == 1
        assert (plan.nodes[0].tool_id, plan.nodes[0].action) == ("conversation", "reply")

        result = PlannedWorkflowDispatch._execute_reply_plan(plan, {})

        assert result["success"] is True
        assert result["response"] == "你好，我可以帮你查询业务数据。"
        assert result["data"]["workflow_runtime"] == "xcagi-langgraph"

    def test_reply_plan_failure_declares_no_business_write(self):
        from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
        from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

        plan = PlanGraph(
            plan_id="plan-1",
            intent="chat",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="conversation", action="reply"),
                WorkflowNode(node_id="n2", tool_id="conversation", action="reply"),
            ],
        )
        result = PlannedWorkflowDispatch._execute_reply_plan(
            plan, {"turn_id": "turn-1", "idempotency_key": "turn-1"}
        )
        assert result["success"] is False
        assert result["execution"]["effect"] == "none"
        assert result["execution"]["committed"] is False
        assert result["execution"]["idempotency_key"] == "turn-1"

    def test_llm_http_error_returns_none(self):
        mock_response = Mock()
        mock_response.status_code = 500
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "test-key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "test-model"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            with patch(
                "app.application.workflow.planner.request_planner_completion",
                return_value=mock_response.json() if mock_response.status_code < 400 else None,
            ):
                planner = LLMWorkflowPlanner()
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})

        assert result is None


class TestPlannerStageMetrics:
    """规划指标必须区分「模型返回了」「计划校验通过」，不能用单点 success 代替。"""

    @staticmethod
    def _delta(before: dict, after: dict, *, stage: str, outcome: str) -> float:
        key = f"xcagi_plan_stage_total{{outcome={outcome},stage={stage}}}"
        return float(after.get(key, 0.0)) - float(before.get(key, 0.0))

    def test_missing_model_plan_is_not_counted_as_success(self, monkeypatch):
        from app.infrastructure.observability import metrics

        planner = LLMWorkflowPlanner(ai_service=Mock())
        monkeypatch.setattr(planner, "_plan_with_llm", lambda *args, **kwargs: None)

        before = metrics.snapshot()
        plan = planner.plan("u-metric-empty", "请把客户写入数据库", get_tool_registry(), {})
        after = metrics.snapshot()

        assert plan.metadata.get("planning_rejected") is True
        assert self._delta(before, after, stage="model_returned", outcome="empty") == 1
        assert self._delta(before, after, stage="plan_valid", outcome="rejected") == 1
        assert self._delta(before, after, stage="plan_valid", outcome="valid_first_pass") == 0

    def test_valid_reply_plan_records_first_pass(self, monkeypatch):
        from app.infrastructure.observability import metrics

        planner = LLMWorkflowPlanner(
            ai_service=Mock(),
            completion=lambda **kwargs: {
                "choices": [{"message": {"content": '{"mode":"reply","reply":"ready"}'}}]
            },
        )

        before = metrics.snapshot()
        plan = planner.plan("u-metric-valid", "hello", get_tool_registry(), {})
        after = metrics.snapshot()

        assert plan.metadata.get("response_mode") == "reply"
        assert self._delta(before, after, stage="model_returned", outcome="returned") == 1
        assert self._delta(before, after, stage="plan_valid", outcome="valid_first_pass") == 1
