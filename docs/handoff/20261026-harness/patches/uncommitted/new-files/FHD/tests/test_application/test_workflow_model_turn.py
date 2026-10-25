"""Workflow JSON decisions use real actor admission and the shared durable cursor."""

import json
from types import SimpleNamespace

import pytest
from openai import OpenAI

from tests.fixtures import backend_ci_isolation

trusted_actor = backend_ci_isolation.trusted_actor
reviewed_agent_http = backend_ci_isolation.reviewed_agent_http


@pytest.fixture
def workflow_model(monkeypatch):
    from app.infrastructure.llm.client import llm_client_scope

    monkeypatch.setenv("OPENAI_API_KEY", "workflow-fixture-model-canary")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://workflow-fixture.example/v1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    model = OpenAI(
        api_key="workflow-fixture-model-canary", base_url="https://workflow-fixture.example/v1"
    )
    with llm_client_scope(model, "workflow-fixture-model"):
        yield model


def json_model(monkeypatch, decisions):
    from openai.resources.chat.completions import Completions

    requests = []
    values = iter(decisions)

    def complete(self, **request):
        requests.append(request)
        value = next(values)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=value if isinstance(value, str) else json.dumps(value),
                        tool_calls=None,
                    ),
                )
            ],
            usage=None,
        )

    monkeypatch.setattr(Completions, "create", complete)
    return requests


def workflow_engine():
    from app.application.workflow.agentic_model_policy import registered_workflow_dispatch
    from app.application.workflow.engine import WorkflowEngine

    return WorkflowEngine(registered_workflow_dispatch)


def run_workflow(actor, registry, *, engine=None, message="workflow", turn="original"):
    from app.application.workflow.workflow_types import PlanGraph

    return (engine or workflow_engine()).run(
        PlanGraph("workflow-plan", "workflow-test"),
        agentic_loop=True,
        tool_registry=registry,
        runtime_context={
            **actor.context,
            "message": message,
            "conversation_id": "workflow",
            "turn_id": turn,
        },
    )


def test_json_read_then_done_uses_original_run_receipt_and_prompt(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = json_model(
        monkeypatch,
        [
            {
                "tool_id": "business_db",
                "action": "read",
                "params": {"entity": "customers"},
                "reasoning": "read",
            },
            {"action": "done"},
        ],
    )
    result = run_workflow(
        actor, {"business_db": {"actions": {"read": {"risk": "low", "idempotent": True}}}}
    )
    assert result.success is True, result
    assert len(result.node_results) == 1
    assert result.node_results[0].tool_id == "business_db"
    assert result.node_results[0].action == "read"
    run = http.repository.get(result.final_context["run_id"])
    assert run.metadata[STATE_KEY]["phase"] == "terminal"
    assert run.metadata[STATE_KEY]["round"] == 2
    assert run.tool_calls[0].call_id.startswith("wfa_")
    assert run.tool_calls[0].metadata["independent_verification"]["verified"] is True
    assert not any(call.metadata.get("observed") for call in run.tool_calls)
    assert len(requests) == 2
    assert all(
        request["timeout"].read == 20.0 and request["timeout"].connect == 10.0
        for request in requests
    )
    prompt = json.loads(requests[1]["messages"][1]["content"])
    assert "business_db.read" in prompt["recent_history"]
    assert "结果:" in prompt["recent_history"]
    assert "workflow-fixture-model-canary" not in json.dumps(run.metadata[STATE_KEY])
    assert "_actor_authorization" not in result.final_context


@pytest.mark.parametrize(
    "value",
    [
        "{}",
        "[]",
        '{"tool_id":"business_db","action":"read","params":[]}',
        '{"action":"done","action":"execute"}',
    ],
)
def test_invalid_json_never_creates_intent(
    trusted_actor, reviewed_agent_http, workflow_model, monkeypatch, value
):
    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = json_model(monkeypatch, [value])
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    assert result.success is False
    run = http.repository.get(result.final_context["run_id"])
    assert run.tool_calls == []
    assert len(requests) == 1


def test_anonymous_tool_does_not_dispatch_or_request_next_model(monkeypatch):
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.workflow_types import PlanGraph

    calls = []
    engine = WorkflowEngine(lambda **params: calls.append(params))
    monkeypatch.setattr(
        engine,
        "_llm_decide_next_step",
        lambda **kwargs: {
            "tool_id": "business_db",
            "action": "read",
            "params": {"entity": "customers"},
        },
    )
    result = engine.run(
        PlanGraph("anonymous", "test"),
        agentic_loop=True,
        tool_registry={"business_db": {"actions": {"read": {}}}},
    )
    assert result.success is False
    assert result.node_results == [] and calls == []
    assert result.final_context["workflow_status"]["steps"] == 1


@pytest.mark.parametrize(
    "count,final_kind", [(1, "done"), (10, "done"), (10, "execute"), (10, "invalid")]
)
def test_ten_step_boundary_and_invalid_history(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    count,
    final_kind,
):
    actor = trusted_actor()
    reviewed_agent_http(actor)
    read = {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}}
    invalid = {"tool_id": "", "action": "execute", "params": {}}
    decisions = [read] * (count - 1) + [
        {"action": "done"} if final_kind == "done" else read if final_kind == "execute" else invalid
    ]
    requests = json_model(monkeypatch, decisions)
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    assert result.success is (final_kind == "done")
    assert len(requests) == count
    assert result.final_context["workflow_status"]["steps"] == count
    if count == 10:
        prompt = json.loads(requests[-1]["messages"][1]["content"])
        assert len(prompt["recent_history"].splitlines()) == 8
        assert (
            len({node.node_id for node in result.node_results}) <= 1
        )  # Public aliases remain compatible.


def test_invalid_then_done_cannot_erase_original_error(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    from unittest.mock import Mock

    actor = trusted_actor()
    reviewed_agent_http(actor)
    engine = workflow_engine()
    engine._llm_decide_next_step = Mock(
        side_effect=[{"action": "execute", "tool_id": ""}, {"action": "done"}]
    )
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}}, engine=engine)
    assert result.success is False
    assert result.final_context["workflow_status"]["invalid_decisions"] == 1
    assert engine._llm_decide_next_step.call_args.kwargs["agent_history"][-1]["content"].startswith(
        "工具决策缺少"
    )


def test_actual_rbac_denial_and_missing_catalog_create_no_intent(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    actor = trusted_actor(role="workflow-denied", permissions=[])
    http = reviewed_agent_http(actor)
    json_model(
        monkeypatch,
        [{"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}}],
    )
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    assert result.success is False
    assert http.repository.get(result.final_context["run_id"]).tool_calls == []


def test_nonportable_write_hook_is_rejected_before_intent(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    engine = workflow_engine()
    calls = []
    monkeypatch.setattr(engine, "_run_single_tool", lambda **kwargs: calls.append(kwargs))
    json_model(
        monkeypatch,
        [
            {
                "tool_id": "business_db",
                "action": "write",
                "params": {
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "must not write"},
                },
            }
        ],
    )
    result = run_workflow(actor, {"business_db": {"actions": {"write": {}}}}, engine=engine)
    assert result.success is False and calls == []
    assert http.repository.get(result.final_context["run_id"]).tool_calls == []


def test_budget_is_derived_from_canonical_timeout_and_only_reduced_by_request():
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.agentic_model_policy import _limits

    registry = {"business_db": {"actions": {"read": {}}}}
    timeout = get_tool_action_spec("business_db", "read").timeout_seconds
    expected = min(86400, 10 * (20 + timeout * 3))
    assert _limits(registry, 2, {})["seconds"] == expected
    assert _limits(registry, 2, {"timeout_seconds": 100000})["seconds"] == expected
    assert _limits(registry, 2, {"timeout_seconds": 1})["seconds"] == 1


def inline_business_adapter(monkeypatch, dispatch):
    """Deterministic I/O only; execute() retains real actor, Mod and grant checks."""
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    monkeypatch.setattr(
        AgentToolExecutor,
        "execute_with_deadline",
        lambda self, step, *, runtime_context, deadline_monotonic: self.execute(
            step, runtime_context=runtime_context
        ),
    )
    monkeypatch.setattr(AgentToolExecutor, "_dispatch", dispatch)


def test_terminal_checkpoint_rebuilds_read_only_after_response_crash(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = json_model(
        monkeypatch,
        [
            {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}},
            {"action": "done"},
        ],
    )
    registry = {"business_db": {"actions": {"read": {}}}}
    first = run_workflow(actor, registry)
    run = http.repository.get(first.final_context["run_id"])
    original_calls = [call.to_dict() for call in run.tool_calls]
    run.final_output.pop("workflow_result")
    http.repository.save(run)
    replay = run_workflow(actor, registry)
    assert replay.success is True and len(requests) == 2
    assert replay.final_context["run_id"] == run.run_id
    assert replay.node_results == first.node_results
    assert [call.to_dict() for call in http.repository.get(run.run_id).tool_calls] == original_calls


@pytest.mark.parametrize("extra", ["limits", "batch", "next_call_index", "request_id"])
def test_no_call_transition_cannot_mutate_authority_or_budget(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    extra,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.application.workflow.agentic_model_policy import WorkflowAgenticModelPolicy

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    json_model(monkeypatch, [{"action": "done"}])
    monkeypatch.setattr(
        WorkflowAgenticModelPolicy,
        "no_call_transition",
        lambda self, decision, state: {
            "phase": "ready_model",
            extra: 999,
        },
    )
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    run = http.repository.get(result.final_context["run_id"])
    assert run.status == "blocked" and not result.success
    assert run.metadata[STATE_KEY]["limits"]["rounds"] == 10
    assert run.metadata[STATE_KEY]["limits"]["calls"] == 10
    assert run.tool_calls == []


def test_public_hooks_preserve_projection_fields_and_inline_order(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    from app.application.workflow.workflow_types import NodeExecutionResult

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    engine = workflow_engine()
    expected = NodeExecutionResult(
        "display-alias",
        True,
        "business_db",
        "read",
        params={"entity": "customers"},
        output={"success": True, "data": []},
        retries=2,
        retryable=True,
        started_at="2026-10-26T01:00:00+00:00",
        finished_at="2026-10-26T01:00:01+00:00",
        duration_ms=1000,
        attempts=[{"attempt": 3, "success": True}],
    )
    events = []
    append, merge = engine._append_node_trace, engine._merge_state_schema
    monkeypatch.setattr(engine, "_run_single_tool", lambda **kwargs: expected)

    def trace(context, result):
        events.append("trace")
        append(context, result)

    def schema(context, result, schema):
        events.append("schema")
        merge(context, result, schema)

    def emit(result):
        events.append("emit")
        assert result == expected

    monkeypatch.setattr(engine, "_append_node_trace", trace)
    monkeypatch.setattr(engine, "_merge_state_schema", schema)
    monkeypatch.setattr(engine, "_emit_state_update", emit)
    json_model(
        monkeypatch,
        [
            {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}},
            {"action": "done"},
        ],
    )
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}}, engine=engine)
    assert result.success and result.node_results == [expected]
    assert events == ["trace", "schema", "emit"]
    assert result.final_context["node_outputs"]["agent_step_1"] == expected.output
    call = http.repository.get(result.final_context["run_id"]).tool_calls[0]
    assert call.node_id == call.call_id and call.node_id != expected.node_id


def test_admission_failure_precedes_model_and_intent(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = json_model(monkeypatch, [{"action": "done"}])
    monkeypatch.setattr(
        http.repository,
        "claim_first_task_run",
        lambda run: (_ for _ in ()).throw(ValueError("storage admission failed")),
    )
    with pytest.raises(ValueError, match="storage admission failed"):
        run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    assert requests == []


@pytest.mark.parametrize("field", ["user_id", "tenant_id", "active_mod_id"])
def test_real_actor_scope_cannot_be_changed_before_admission(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    field,
):
    from app.application.workflow.workflow_types import PlanGraph

    actor = trusted_actor()
    reviewed_agent_http(actor)
    requests = json_model(monkeypatch, [{"action": "done"}])
    with pytest.raises(ValueError):
        workflow_engine().run(
            PlanGraph("scope", "test"),
            agentic_loop=True,
            runtime_context={**actor.context, field: "unrelated-scope"},
            tool_registry={"business_db": {"actions": {"read": {}}}},
        )
    assert requests == []


def test_market_account_binding_uses_bounded_copy_without_mutating_original_client(
    trusted_actor,
    reviewed_agent_http,
    monkeypatch,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.db.models.user import Session as UserSession
    from app.domain.shared_services.conversation.modstore_adapter import (
        ModstoreOpenAICompatibleClient,
        ModstorePlatformAdapter,
    )
    from app.infrastructure.llm.client import llm_client_scope

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    token = "workflow-market-session-canary"
    with actor.factory.begin() as db:
        row = db.get(UserSession, actor.session_row_id)
        row.market_user_id = 77
        row.market_access_token = token
    adapter = ModstorePlatformAdapter(
        platform_url="https://market-fixture.example",
        auth_token=token,
        user_id=77,
        default_provider="fixture",
        default_model="same-account-model",
        timeout=60,
    )
    calls = []

    def complete(self, **request):
        calls.append((self.timeout, self.auth_token, request["model"]))
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"action":"done"}', "tool_calls": None},
                }
            ],
            "usage": None,
        }

    monkeypatch.setattr(ModstorePlatformAdapter, "chat_completion_sync", complete)
    client = ModstoreOpenAICompatibleClient(adapter)
    with llm_client_scope(client, "fixture/same-account-model"):
        result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    assert result.success is True
    assert calls == [(20.0, token, "fixture/same-account-model")]
    assert adapter.timeout == 60 and adapter.auth_token == token
    state = http.repository.get(result.final_context["run_id"]).metadata[STATE_KEY]
    assert state["model_reference"]["kind"] == "market_session"
    assert state["model_reference"]["market_user_id"] == 77
    assert token not in json.dumps(state)


def test_sdk_timeout_suspends_original_inflight_decision_without_retry(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    import httpx
    from openai import APITimeoutError
    from openai.resources.chat.completions import Completions

    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = []

    def timeout(self, **request):
        requests.append(request)
        raise APITimeoutError(request=httpx.Request("POST", "https://workflow-fixture.example/v1"))

    monkeypatch.setattr(Completions, "create", timeout)
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    run = http.repository.get(result.final_context["run_id"])
    assert not result.success and run.status == "blocked"
    assert run.metadata[STATE_KEY]["blocked_model_recovery"] is True
    assert run.metadata[STATE_KEY]["round"] == 1 and run.tool_calls == []
    assert len(requests) == 1
