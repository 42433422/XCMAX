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
    qualification = tmp_path / "fixture-qualification.json"
    qualification.write_text(
        json.dumps(
            {
                "schema": "xcmax.runtime-qualification.v1",
                "route_identity": route.identity,
                "codex_version": CODEX_VERSION,
                "model_kind": "real",
                "evidence_refs": ["test-only-fixture"],
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
    monkeypatch.setattr(
        AgentOrchestrator, "start_run", lambda *a, **kw: pytest.fail("retired native entry")
    )

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


@pytest.fixture
def compiled_chat_runtime(runtime_entry, monkeypatch):
    """Real host compilation/SQL/MCP, with explicit Responses and SDK fixtures.

    Callers supply each planner and independent review response. This exercises
    the fixed entry without representing scripted model I/O as qualification.
    """
    import copy

    import httpx
    import openai

    from app.application.agent_runtime import codex_runtime, goal_admission

    state = runtime_entry
    state.model_requests, state.admissions, state.transports, state.receipts = [], [], [], []
    state.on_turn = lambda binding: None
    state.completion = lambda **kwargs: pytest.fail("fixture must specify its model response")
    actual_openai, actual_compile = openai.OpenAI, goal_admission.compile_runtime_goal

    def response(request):
        body = json.loads(request.content)
        assert body["tools"] == [] and body["store"] is False
        assert str(request.url) == state.model_config.provider_url + "/responses"
        assert request.headers["authorization"] == "Bearer " + state.model_config.provider_token
        prompt = json.loads(body["input"][-1]["content"])
        state.model_requests.append(prompt)
        result = state.completion(messages=body["input"], context=prompt.get("context", {}))
        return httpx.Response(
            200,
            json={
                "id": "resp_compiled_fixture",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_compiled_fixture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": result["choices"][0]["message"]["content"],
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
            },
        )

    def client(**kwargs):
        kwargs.pop("http_client").close()
        return actual_openai(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(response))
        )

    def compile_goal(binding, config):
        state.model_config = config
        state.admissions.append(copy.deepcopy(binding.run))
        return actual_compile(binding, config)

    class Transport:
        def __init__(self, config):
            self.config = config
            state.transports.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, *, developer_instructions):
            return "compiled-chat-fixture"

        async def resume_thread(self, thread_id, *, developer_instructions):
            return thread_id

        async def interrupt(self):
            return None

        async def stream_turn(self, _text):
            bridge = state.servers[-1].state.codex_tool_bridge
            binding = bridge.store.authenticate(self.config.mcp_token)
            state.on_turn(binding)
            if binding.run.metadata["runtime_goal_mode"] == "business":
                operation = binding.run.metadata["runtime_expected_operations"][0]
                state.receipts.append(
                    bridge.invoke(
                        self.config.mcp_token,
                        "execute_plan",
                        {"call_id": "compiled-fixture-plan", **operation["params"]},
                    )
                )
            reply = binding.run.metadata.get("_codex_goal_reply") or "本轮模型已结束。"
            for method, payload in (
                ("turn/started", {"turn": {"status": "inProgress"}}),
                ("item/completed", {"item": {"type": "agentMessage", "text": reply}}),
                ("turn/completed", {"turn": {"status": "completed"}}),
            ):
                yield {
                    "method": method,
                    "payload": payload,
                    "thread_id": "compiled-chat-fixture",
                    "turn_id": "compiled-fixture-turn",
                }

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(goal_admission, "compile_runtime_goal", compile_goal)
    monkeypatch.setattr(gateway, "run_codex_agent", codex_runtime.run_codex_agent)
    monkeypatch.setattr("app.infrastructure.codex.CodexTransport", Transport)
    monkeypatch.setattr(
        "app.application.agent_runtime.chat.runtime_settings", lambda: state.settings
    )
    return state
