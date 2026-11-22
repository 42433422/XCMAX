"""Host goal admission uses one bound gateway and never executes its model plan."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_runtime import goal_admission as admission
from app.application.workflow.workflow_types import plan_to_dict
from app.domain.autonomy.risk_types import RiskDecision
from app.infrastructure.codex import CodexTransportConfig
from app.infrastructure.codex.binding import CodexBinding, CodexBindingError


def business_plan(params=None):
    return {
        "mode": "workflow",
        "intent": "sales_lookup",
        "nodes": [
            {"node_id": "query", "tool_id": "sales", "action": "query", "params": params or {}}
        ],
    }


def coverage(source, *, outcome="execute", node="query", **extra):
    return {
        "goals": [
            {"goal_id": "sales_goal", "source": source, "outcome": outcome, "node_ids": [node]}
        ],
        "violations": [],
        **extra,
    }


def response(payload, *, status="completed", output=None):
    return {
        "id": "resp_synthetic",
        "object": "response",
        "created_at": 1,
        "model": "bound-model",
        "status": status,
        "output": output
        if output is not None
        else [
            {
                "type": "message",
                "id": "msg_synthetic",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(payload, ensure_ascii=False),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
    }


@pytest.fixture
def compiler(monkeypatch, tmp_path):
    from app.application.agent_orchestrator import tool_permission
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.facades import tools_facade
    from app.application.workflow.risk_gate import HybridRiskGate

    registry = {
        "sales": {
            "description": "销售订单查询",
            "actions": {
                "query": {"risk": "low", "idempotent": True, "required_params": []},
            },
        }
    }
    run = AgentRun(user_id="71", message="查询已确认销售订单", run_id="goal-parent")
    run.metadata.update(runtime_context={"user_id": "71", "tenant_id": 7}, codex_runtime={})
    state = SimpleNamespace(
        run=run,
        replies=[],
        requests=[],
        clients=[],
        risk_plans=[],
        registry=registry,
        decision=RiskDecision(requires_confirmation=False, reason="test allow", allowed=True),
        after_request=lambda: None,
    )
    real_openai = openai.OpenAI

    def handle(request):
        state.requests.append(request)
        assert state.replies, "unexpected extra model request or fallback"
        result = state.replies.pop(0)
        state.after_request()
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json=result)

    def client(**kwargs):
        original = kwargs.pop("http_client")
        state.clients.append(
            {**kwargs, "trust_env": original._trust_env, "redirects": original.follow_redirects}
        )
        original.close()
        return real_openai(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )

    def evaluate(_self, plan, context):
        state.risk_plans.append(plan_to_dict(plan))
        return state.decision

    def prohibit_execution(*_args, **_kwargs):
        raise AssertionError("goal compilation executed a business tool")

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(tools_facade, "get_workflow_tool_registry", lambda: state.registry)
    monkeypatch.setattr(tool_permission, "actor_tool_denial", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(HybridRiskGate, "evaluate", evaluate)
    monkeypatch.setattr(AgentToolExecutor, "execute", prohibit_execution)
    state.config = CodexTransportConfig(
        runtime_root=tmp_path,
        scope_id="goal-parent",
        model="bound-model",
        provider_url="http://127.0.0.1:41111/api/agent-runtime/codex",
        provider_token="parent-model-grant",
        mcp_url="http://127.0.0.1:41111/mcp",
        mcp_token="parent-mcp-grant",
        context_window=32000,
        auto_compact_token_limit=24000,
        timeout_seconds=20,
        turn_timeout_seconds=30,
    )
    state.compile = lambda: admission.compile_runtime_goal(CodexBinding(run), state.config)
    return state


def test_planner_and_independent_review_use_only_bound_metered_gateway(compiler):
    compiler.replies = [response(business_plan()), response(coverage(compiler.run.message))]

    goal = compiler.compile()

    assert goal.mode == "business" and goal.plan["plan_id"] == "plan_goal-parent"
    assert goal.plan["nodes"][0]["tool_id"] == "sales"
    assert compiler.risk_plans[0]["plan_id"] == goal.plan["plan_id"]
    assert len(compiler.requests) == 2
    for request in compiler.requests:
        assert str(request.url) == "http://127.0.0.1:41111/api/agent-runtime/codex/responses"
        assert request.headers["authorization"] == "Bearer parent-model-grant"
        body = json.loads(request.content)
        assert body["model"] == "bound-model"
        assert body["tools"] == [] and body["store"] is False
        assert body["max_output_tokens"] == 8000
        assert 0 < request.extensions["timeout"]["read"] <= 20
    assert compiler.clients[0]["max_retries"] == 0
    assert compiler.clients[0]["trust_env"] is compiler.clients[0]["redirects"] is False
    assert compiler.run.tool_calls == [] and compiler.run.steps == []
    assert "runtime_goal_admitted" not in compiler.run.metadata


def test_pure_reply_has_no_business_graph_or_risk_execution(compiler):
    compiler.run.message = "解释发票的含义"
    compiler.replies = [
        response({"mode": "reply", "reply": "发票是交易凭证。"}),
        response(coverage(compiler.run.message, outcome="reply", node="model_reply")),
    ]
    goal = compiler.compile()
    assert (goal.mode, goal.plan, goal.reply) == ("reply", None, "发票是交易凭证。")
    assert compiler.risk_plans == [] and compiler.run.tool_calls == []


@pytest.mark.parametrize("kind", ["incomplete", "tool_call", "empty", "transport"])
def test_incomplete_or_toolful_provider_output_never_freezes_or_retries(compiler, kind):
    output = response(business_plan())
    if kind == "incomplete":
        output["status"] = "incomplete"
    elif kind == "tool_call":
        output["output"] = [
            {
                "type": "function_call",
                "name": "execute_action",
                "arguments": "{}",
                "call_id": "fake",
            }
        ]
    elif kind == "empty":
        output["output"] = []
    else:
        output = httpx.ReadTimeout("synthetic gateway timeout")
    compiler.replies = [output]
    with pytest.raises(CodexBindingError):
        compiler.compile()
    assert len(compiler.requests) == 1
    assert compiler.run.tool_calls == [] and compiler.risk_plans == []


def test_reply_cannot_satisfy_an_execute_goal(compiler):
    reply = response({"mode": "reply", "reply": "已完成销售查询。"})
    review = response(coverage(compiler.run.message, node="model_reply"))
    compiler.replies = [reply, review, reply, review]
    with pytest.raises(CodexBindingError):
        compiler.compile()
    assert len(compiler.requests) == 4
    assert compiler.risk_plans == [] and compiler.run.tool_calls == []


def test_missing_scope_is_a_question_without_a_frozen_graph(compiler):
    compiler.replies = [
        response(
            {
                "mode": "workflow",
                "intent": "clarify_scope",
                "nodes": [
                    {
                        "node_id": "question",
                        "tool_id": "clarify",
                        "action": "ask",
                        "params": {"question": "查询哪个月份的销售订单？"},
                    }
                ],
            }
        )
    ]
    goal = compiler.compile()
    assert goal.question == "查询哪个月份的销售订单？"
    assert goal.mode == "business" and goal.plan is None
    assert len(compiler.requests) == 1 and compiler.risk_plans == []


def test_clarification_uses_latest_attachment_references_without_authority_override(
    compiler, monkeypatch
):
    from app.application.agent_orchestrator import attachment_inputs

    observed = []
    compiler.run.metadata["runtime_context"].update(
        file_analysis={"source": "original"},
        attachment_upload_ids=["initial-upload"],
    )
    compiler.run.metadata["_codex_input_data"] = {"file_context": {"name": "old.csv"}}
    compiler.run.add_event(
        "runtime.input_answered",
        data={
            "question": "需要哪一个月份？",
            "answer": "只查询十一月，使用这份新附件。",
            "input_data": {
                "file_context": {"name": "new.csv"},
                "attachment_upload_ids": ["new-upload"],
                "tenant_id": 999,
                "_actor_authorization": {"forged": True},
            },
        },
    )

    def resolve(context):
        observed.append(copy.deepcopy(context))
        return context, []

    monkeypatch.setattr(attachment_inputs, "resolve_attachment_context", resolve)
    compiler.replies = [response(business_plan()), response(coverage(compiler.run.message))]
    goal = compiler.compile()
    assert goal.plan is not None
    assert observed[0]["file_context"] == {"source": "original", "name": "new.csv"}
    assert observed[0]["attachment_upload_ids"] == ["new-upload"]
    assert observed[0]["tenant_id"] == 7 and "_actor_authorization" not in observed[0]
    prompt = json.loads(json.loads(compiler.requests[0].content)["input"][1]["content"])
    clarified = json.loads(prompt["user_message"])
    assert clarified["original_request"] == compiler.run.message
    assert clarified["exchanges"][0]["answer"] == "只查询十一月，使用这份新附件。"
    assert compiler.run.metadata["runtime_context"]["attachment_upload_ids"] == ["initial-upload"]


def test_changed_targets_are_reviewed_again_before_final_risk_gate(compiler, monkeypatch):
    from app.application.elt import batch_continuation

    def bind(plan, context):
        assert plan.plan_id == "plan_goal-parent"
        plan.nodes[0].params = {"status": "confirmed"}

    monkeypatch.setattr(batch_continuation, "bind_durable_batch", bind)
    compiler.replies = [
        response(business_plan()),
        response(coverage(compiler.run.message)),
        response(coverage(compiler.run.message)),
    ]
    goal = compiler.compile()
    assert len(compiler.requests) == 3
    final_review = json.loads(json.loads(compiler.requests[-1].content)["input"][1]["content"])
    assert final_review["plan"]["nodes"][0]["params"] == {"status": "confirmed"}
    assert compiler.risk_plans[0]["nodes"] == goal.plan["nodes"]
    assert compiler.risk_plans[0]["plan_id"] == goal.plan["plan_id"]


def test_bound_target_permission_is_rechecked_after_planning(compiler, monkeypatch):
    from app.application.agent_orchestrator import tool_permission

    monkeypatch.setattr(
        tool_permission,
        "actor_tool_denial",
        lambda *args: "denied" if len(args) > 3 and args[3] else None,
    )
    compiler.replies = [
        response(business_plan({"status": "confirmed"})),
        response(coverage(compiler.run.message)),
    ]
    with pytest.raises(CodexBindingError) as error:
        compiler.compile()
    assert error.value.code == "goal_permission_denied"
    assert compiler.risk_plans == []


@pytest.mark.parametrize(
    "blocking,denied", [([], []), (["nonexistent"], []), (["query"], ["query"])]
)
def test_invalid_risk_approval_cannot_become_an_executable_goal(compiler, blocking, denied):
    compiler.decision = RiskDecision(
        requires_confirmation=True,
        reason="test denial",
        blocking_nodes=blocking,
        denied_nodes=denied,
    )
    compiler.replies = [response(business_plan()), response(coverage(compiler.run.message))]
    with pytest.raises(CodexBindingError) as error:
        compiler.compile()
    assert error.value.code == "goal_risk_denied"


def test_approval_keeps_the_original_graph_and_marks_only_blocking_nodes(compiler):
    compiler.decision = RiskDecision(
        requires_confirmation=True, reason="test approval", blocking_nodes=["query"]
    )
    compiler.replies = [response(business_plan()), response(coverage(compiler.run.message))]
    goal = compiler.compile()
    assert goal.plan["metadata"]["approval_required_node_ids"] == ["query"]
    assert goal.plan["nodes"][0]["risk"] == "high"
    assert goal.plan["nodes"][0]["params"] == compiler.risk_plans[0]["nodes"][0]["params"]
    assert compiler.run.tool_calls == []


def test_compiler_deadline_bounds_every_request_and_rejects_late_review(compiler, monkeypatch):
    clock = [time.monotonic()]
    monkeypatch.setattr(admission, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    compiler.config = replace(compiler.config, turn_timeout_seconds=10)
    compiler.after_request = lambda: clock.__setitem__(0, clock[0] + 6)
    compiler.replies = [response(business_plan()), response(coverage(compiler.run.message))]
    with pytest.raises(CodexBindingError) as error:
        compiler.compile()
    assert error.value.code == "goal_admission_timeout"
    assert len(compiler.requests) == 2
    assert compiler.requests[0].extensions["timeout"]["read"] <= 10
    assert compiler.requests[1].extensions["timeout"]["read"] <= 4
    assert compiler.risk_plans == []


def test_compiler_respects_inherited_invocation_budget(compiler):
    from app.application.tool_execution_deadline import invocation_deadline

    compiler.replies = [response(business_plan()), response(coverage(compiler.run.message))]
    with invocation_deadline(time.monotonic() + 5):
        assert compiler.compile().plan is not None
    assert all(0 < request.extensions["timeout"]["read"] <= 5 for request in compiler.requests)
