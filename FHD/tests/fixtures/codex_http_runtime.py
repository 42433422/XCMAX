"""Natural-language HTTP tasks share the durable fixed-executor entry."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import AgentOrchestrator, set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import (
    AgentTaskDispatcher,
    set_agent_task_dispatcher_for_tests,
    stop_agent_task_dispatcher,
)
from app.application.agent_orchestrator.task_execution_repository import (
    set_task_execution_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_runtime import gateway
from app.fastapi_routes.domains.agent.agent_routes import router
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def runtime_entry(trusted_actor, tmp_path, monkeypatch):
    actor = trusted_actor(role="admin")
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(repository)
    set_task_execution_repository_for_tests(queue)
    set_agent_task_dispatcher_for_tests(None)

    route = ModelRoute(
        base_url="http://127.0.0.1:19112/v1",
        model="test-fixture-model",
        provider_id="fixture",
        upstream_vendor="test-fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    # Synthetic receipt for contract tests, never evidence of real route qualification.
    qualification = tmp_path / "fixture-qualification.json"
    qualification.write_text(
        json.dumps(
            {
                "schema": "xcmax.runtime-qualification.v1",
                "route_identity": route.identity,
                "codex_version": CODEX_VERSION,
                "model_kind": "real",
                "evidence_refs": ["synthetic-http-runtime-test-only"],
                "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
            }
        )
    )
    state = SimpleNamespace(
        actor=actor,
        repository=repository,
        queue=queue,
        calls=[],
        servers=[],
        settings=RuntimeSettings(
            engine="codex",
            route=route,
            runtime_root=tmp_path / "runtime",
            qualification_file=qualification,
        ),
    )

    class Server:
        url = "http://127.0.0.1:19113"

        def __init__(self, app):
            state.servers.append(app)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    async def runtime(**kwargs):
        # Only external runtime I/O is replaced. SQL admission, authentication,
        # generation fencing and HTTP lifecycle handlers remain production code.
        state.calls.append(kwargs)
        store, run_id = kwargs["binding_store"], kwargs["run_id"]
        grant = store.create(run_id, runtime_config=kwargs["runtime_config"])
        result = {
            "handler": "agent",
            "runtime": "codex",
            "run_id": run_id,
            "ok": True,
            "business_completed": False,
            "verified_operations": False,
            "execution_state": "completed",
            "exit_status": "completed",
            "output": "库存表示可用产品的数量。",
        }

        def complete(parent, _metadata):
            parent.status = "completed"
            parent.final_output["codex_result"] = dict(result)
            parent.add_event("run.completed", "普通说明已完成")

        store.update(run_id, complete)
        store.close(run_id, "completed", generation=grant.binding.metadata["generation"])
        return result

    monkeypatch.setattr(gateway, "runtime_settings", lambda: state.settings)
    monkeypatch.setattr(gateway, "LocalRuntimeServer", Server)
    monkeypatch.setattr(gateway, "run_codex_agent", runtime)
    assert not hasattr(AgentOrchestrator, "start_run"), "retired natural-language entry remains"

    def drain(run_id):
        owner = "http-fixture-worker"
        execution = queue.claim(owner, lease_seconds=120)
        assert execution is not None and execution.run_id == run_id
        AgentTaskDispatcher(execution_repository=queue, run_repository=repository)._execute_claim(
            execution, owner
        )
        return repository.get(run_id)

    state.drain = drain
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, headers=actor.headers) as client:
        state.client = client
        yield state
    set_agent_run_repository_for_tests(None)
    set_task_execution_repository_for_tests(None)
    stop_agent_task_dispatcher(timeout=0)
    set_agent_task_dispatcher_for_tests(None)


def fixture_goal_review(
    prompt, *, kind, source=None, evidence_ids=None, status="satisfied", feedback=""
):
    """Explicit fixture judgement; the production host still checks every proof."""
    if evidence_ids is None:
        evidence_ids = (
            ["response"]
            if kind == "reply"
            else [
                row["evidence_id"]
                for row in prompt["evidence"]
                if row["receipt"].get("verified") is True
            ]
        )
    return {
        "goals": [
            {
                "goal_id": "fixture-goal",
                "source_id": "request",
                "source": source or prompt["original_request"]["text"],
                "kind": kind,
                "status": status,
                "evidence_ids": evidence_ids,
                "reason": "Explicit synthetic model review of this test's declared original goal",
            }
        ],
        "violations": [],
        "uncovered_sources": [],
        "feedback": feedback,
    }


@pytest.fixture
def dynamic_chat_runtime(runtime_entry, monkeypatch):
    """Real prepare/SQL/MCP/verifier/gateway; only Codex SDK and upstream are fixtures."""
    import copy

    import httpx
    import openai

    from app.application.agent_runtime import codex_runtime, goal_admission
    from app.infrastructure.codex.model_gateway import MODEL_PATH

    state = runtime_entry
    state.model_requests, state.admissions, state.transports, state.receipts = [], [], [], []
    state.on_turn = lambda binding: None
    state.actions = None
    state.reply = "本轮模型已结束。"
    state.script = None
    state.review = lambda prompt: pytest.fail(
        "fixture must explicitly declare its independent review"
    )
    drain_claim = state.drain

    def drain(run_id):
        # Exercise the production coordinator's periodic receipt scan before
        # claiming a ready task, as its worker loop does after child approvals.
        dispatcher = AgentTaskDispatcher(
            execution_repository=state.queue, run_repository=state.repository
        )
        dispatcher._recover_outcomes()
        worker = dispatcher._outcome_worker
        assert worker is not None
        worker.join(timeout=10)
        assert not worker.is_alive(), "receipt recovery exceeded the fixture deadline"
        return drain_claim(run_id)

    state.drain = drain
    actual_openai, actual_prepare = openai.OpenAI, goal_admission.prepare_runtime_goal

    def upstream(request):
        body = json.loads(request.content)
        assert body["tools"] == [] and body["store"] is False
        prompt = json.loads(body["input"][1]["content"])
        assert prompt["task"] == "verify_runtime_goal"
        state.model_requests.append(prompt)
        reviewed = state.review(prompt)
        return httpx.Response(
            200,
            json={
                "id": "resp_dynamic_fixture",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_dynamic_fixture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(reviewed, ensure_ascii=False),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
            },
        )

    class Server:
        url = "http://127.0.0.1:19113"

        def __init__(self, app):
            state.servers.append(app)
            app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
                transport=httpx.MockTransport(upstream), **kwargs
            )

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    def loopback(request):
        # Route through the actual model gateway: grant authentication, debit,
        # original deadline and usage settlement are not replaced by this fixture.
        assert request.url.path == MODEL_PATH
        with TestClient(state.servers[-1]) as client:
            response = client.post(
                MODEL_PATH, content=request.content, headers=dict(request.headers)
            )
        return httpx.Response(
            response.status_code, headers=dict(response.headers), content=response.content
        )

    def client(**kwargs):
        kwargs.pop("http_client").close()
        return actual_openai(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(loopback))
        )

    def prepare_goal(binding, *, history=None):
        if not binding.run.metadata.get("runtime_goal_contract"):
            state.admissions.append(copy.deepcopy(binding.run))
        return actual_prepare(binding, history=history)

    class Transport:
        def __init__(self, config):
            self.config = config
            state.transports.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, *, developer_instructions):
            return "dynamic-chat-fixture"

        async def resume_thread(self, thread_id, *, developer_instructions):
            return thread_id

        async def interrupt(self):
            return None

        async def stream_turn(self, text):
            bridge = state.servers[-1].state.codex_tool_bridge
            binding = bridge.store.authenticate(self.config.mcp_token)
            state.bridge, state.token = bridge, self.config.mcp_token

            def execute(tool_id, action, params, call_id):
                described = bridge.invoke(
                    self.config.mcp_token,
                    "capability_describe",
                    {"tool_id": tool_id, "action": action},
                )
                receipt = bridge.invoke(
                    self.config.mcp_token,
                    "execute_action",
                    {
                        "tool_id": tool_id,
                        "action": action,
                        "params": params,
                        "call_id": call_id,
                        "schema_digest": described["capability"]["schema_digest"],
                    },
                )
                state.receipts.append(receipt)
                return receipt

            state.execute = execute
            state.on_turn(binding)
            if state.script is not None:
                reply = state.script(binding, text)
            else:
                assert state.actions is not None, (
                    "fixture must explicitly specify its Codex actions"
                )
                for operation in state.actions:
                    observed = execute(**operation)
                    if observed.get("status") in {
                        "waiting_user",
                        "blocked",
                        "unknown",
                        "running",
                        "queued",
                    }:
                        break
                reply = state.reply
            for method, payload in (
                ("turn/started", {"turn": {"status": "inProgress"}}),
                ("item/completed", {"item": {"type": "agentMessage", "text": reply}}),
                ("turn/completed", {"turn": {"status": "completed"}}),
            ):
                yield {
                    "method": method,
                    "payload": payload,
                    "thread_id": "dynamic-chat-fixture",
                    "turn_id": "dynamic-fixture-turn",
                }

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv(
        "MODEL_USAGE_LEDGER_PATH", str(state.settings.runtime_root.parent / "model-usage.json")
    )
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv(
        "XCAGI_TOOL_IDEMPOTENCY_PATH",
        str(state.settings.runtime_root.parent / "tool-idempotency.sqlite"),
    )
    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(goal_admission, "prepare_runtime_goal", prepare_goal)
    monkeypatch.setattr(gateway, "LocalRuntimeServer", Server)
    monkeypatch.setattr(gateway, "run_codex_agent", codex_runtime.run_codex_agent)
    monkeypatch.setattr("app.infrastructure.codex.CodexTransport", Transport)
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.runtime_settings", lambda: state.settings
    )
    return state
