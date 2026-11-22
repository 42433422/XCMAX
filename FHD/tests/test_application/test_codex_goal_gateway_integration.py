"""Real CLI -> scoped HTTP/MCP -> host admission -> durable graph receipts.

The model and business data are explicit synthetic fixtures. The pinned SDK/CLI,
planner, independent goal review, authorization, LangGraph, SQL and billing run
normally. Local tool execution opts into the existing in-process test boundary;
this is neither real-provider qualification nor subprocess business acceptance.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import gateway
from app.domain.task_lifecycle.agent_runtime_contract import frozen_workflow_operation
from app.infrastructure.codex.binding import canonical_digest
from app.infrastructure.codex.local_server import LocalRuntimeServer
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_codex_gateway_integration import _events


def _tool_target(tools, name):
    for tool in tools:
        if tool.get("type") == "function" and str(tool.get("name", "")).endswith(name):
            return {"name": tool["name"]}
        if tool.get("type") == "namespace":
            for child in tool.get("tools", []):
                if child.get("name") == name:
                    return {"namespace": tool["name"], "name": child["name"]}
    raise AssertionError(f"The real CLI did not discover controlled tool {name}")


def _message(index, text):
    return {
        "type": "message",
        "id": f"msg-goal-fixture-{index}",
        "status": "completed",
        "role": "assistant",
        "phase": "final_answer",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


@pytest.mark.integration
@pytest.mark.parametrize("queued", [False, True])
def test_real_cli_auto_goal_admission_executes_one_frozen_graph_and_settles_parent(
    trusted_actor, tmp_path, monkeypatch, local_tools, queued
):
    pytest.importorskip("openai_codex")
    cli = pytest.importorskip("codex_cli_bin")
    binary = Path(cli.bundled_codex_path())
    version = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, timeout=10, check=True
    )
    if CODEX_VERSION not in version.stdout.split():
        pytest.skip("This integration requires the exact pinned CLI")

    from app.application.agent_orchestrator import task_dispatcher
    from app.application.agent_orchestrator.business_write_guard import capture_worker_claim
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_runtime import queued_runtime
    from app.infrastructure.billing import model_usage as ledger

    actor = trusted_actor(permissions=["product.view"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    monkeypatch.setattr(gateway, "get_agent_run_repository", lambda: repository)
    monkeypatch.setattr(queued_runtime, "get_task_execution_repository", lambda: queue)
    monkeypatch.setattr(task_dispatcher, "notify_agent_task_dispatcher", lambda: None)
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    monkeypatch.setenv("CODEX_GOAL_FIXTURE_KEY", "synthetic-upstream-key")
    monkeypatch.setattr(
        "app.infrastructure.llm.model_admission.admit_model_call", lambda *args, **kwargs: None
    )
    ledger.set_model_wallet_balance(str(actor.user_id), 100)
    dispatched = []

    def dispatch(tool, action, params):
        assert bool(capture_worker_claim()) is queued
        dispatched.append((tool, action, params["keyword"]))
        return {"success": True, "data": [{"model_number": params["keyword"]}]}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    task = "先查询 first 产品，再查询 second 产品"
    proposal = {
        "mode": "workflow",
        "intent": "products.query",
        "nodes": [
            {
                "node_id": "first",
                "tool_id": "products",
                "action": "query",
                "params": {"keyword": "first"},
            },
            {
                "node_id": "second",
                "tool_id": "products",
                "action": "query",
                "params": {"keyword": "second"},
                "depends_on": ["first"],
            },
        ],
    }
    review = {
        "goals": [
            {
                "goal_id": "first_goal",
                "source": "先查询 first 产品",
                "outcome": "execute",
                "node_ids": ["first"],
            },
            {
                "goal_id": "second_goal",
                "source": "再查询 second 产品",
                "outcome": "execute",
                "node_ids": ["second"],
                "depends_on": ["first_goal"],
            },
        ],
        "violations": [],
    }
    upstream = FastAPI()
    requests = []
    observed_parents = []

    @upstream.post("/v1/responses")
    async def respond(request: Request):
        assert request.headers["authorization"] == "Bearer synthetic-upstream-key"
        body = await request.json()
        requests.append(body)
        index = len(requests)
        if index <= 2:
            assert not body.get("stream") and body["tools"] == []
            assert dispatched == [], "The compiler executed business before freezing the graph"
            content = proposal if index == 1 else review
            return JSONResponse(
                {
                    "id": f"resp-goal-fixture-{index}",
                    "object": "response",
                    "created_at": 1,
                    "model": body["model"],
                    "status": "completed",
                    "output": [_message(index, json.dumps(content, ensure_ascii=False))],
                    "usage": {"input_tokens": 128, "output_tokens": 32, "total_tokens": 160},
                }
            )
        assert body.get("stream") is True
        if index == 3:
            parents = repository.list_recent()
            assert len(parents) == 1 and dispatched == []
            parent = parents[0]
            observed_parents.append(parent.run_id)
            assert parent.metadata["runtime_goal_admitted"] is True
            assert parent.metadata["runtime_goal_mode"] == "business"
            plan = parent.metadata["runtime_frozen_plan"]
            assert parent.metadata["runtime_expected_operations"] == [
                frozen_workflow_operation(plan)
            ]
            assert len(plan["nodes"]) == 2
            item = {
                "type": "function_call",
                "id": "fc-goal-fixture",
                "call_id": "call-goal-fixture",
                **_tool_target(body["tools"], "execute_plan"),
                "arguments": json.dumps(
                    {"call_id": "whole-graph", "plan_digest": canonical_digest(plan)}
                ),
                "status": "completed",
            }
        else:
            assert index == 4, "Unexpected extra model request or planner fallback"
            assert dispatched == [("products", "query", "first"), ("products", "query", "second")]
            outputs = [row for row in body["input"] if row.get("type") == "function_call_output"]
            assert outputs, "The real CLI did not return the host's MCP receipt to its model"
            item = _message(index, "已按顺序查询两个产品，并核对原任务回执。")
        return StreamingResponse(
            iter(_events(index, item, body["model"])), media_type="text/event-stream"
        )

    with LocalRuntimeServer(upstream) as server:
        route = ModelRoute(
            base_url=server.url + "/v1",
            model="goal-integration-fixture-model",
            provider_id="goal-integration-fixture",
            upstream_vendor="test-fixture",
            api_key_env="CODEX_GOAL_FIXTURE_KEY",
            context_window=32000,
            max_output_tokens=4000,
        )
        qualification = tmp_path / "test-only-qualification.json"
        qualification.write_text(
            json.dumps(
                {
                    "schema": "xcmax.runtime-qualification.v1",
                    "route_identity": route.identity,
                    "codex_version": CODEX_VERSION,
                    "model_kind": "real",
                    "evidence_refs": ["synthetic-goal-protocol-fixture-only"],
                    "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
                }
            ),
            encoding="utf-8",
        )
        settings = RuntimeSettings(
            engine="codex",
            route=route,
            runtime_root=tmp_path / "runtime",
            codex_bin=str(binary),
            qualification_file=qualification,
            turn_timeout_seconds=45,
        )
        monkeypatch.setattr(gateway, "runtime_settings", lambda: settings)
        result = gateway.run_runtime_task(
            task=task,
            system_prompt="使用宿主冻结的完整业务图，完成后核对真实回执。",
            runtime_context={
                **actor.context,
                "turn_id": f"real-cli-host-goal-fixture-{queued}",
                "ai_cost_budget_units": 96,
            },
            allowed_actions=["products.query"],
            completion_mode="auto",
            admit_goal=True,
            start_queued=queued,
            settings=settings,
        )
        if queued:
            assert result["execution_state"] == "queued" and requests == [] and dispatched == []
            run_id = result["run_id"]
            execution = queue.claim("integration-worker", lease_seconds=120)
            assert execution is not None and execution.run_id == run_id
            task_dispatcher.AgentTaskDispatcher(
                execution_repository=queue,
                run_repository=repository,
            )._execute_claim(execution, "integration-worker")
            result = repository.get(run_id).final_output["codex_result"]
            assert queue.get(run_id).state == "succeeded", result

    assert result["ok"] is True and result["business_completed"] is True, result
    assert result["runtime_completed"] is True and result["exit_status"] == "completed"
    assert observed_parents == [result["run_id"]]
    parent = repository.get(result["run_id"])
    metadata = parent.metadata["codex_runtime"]
    assert len([event for event in parent.events if event.event_type == "runtime.goal.frozen"]) == 1
    assert set(metadata["calls"]) == {"whole-graph"}
    receipt = metadata["calls"]["whole-graph"]["receipt"]
    assert receipt["verified"] is True
    child = repository.get(receipt["run_id"])
    assert child.status == "completed" and len(child.tool_calls) == 2
    assert [record.params["keyword"] for record in child.tool_calls] == ["first", "second"]
    assert len(repository.list_recent()) == 2
    assert dispatched == [("products", "query", "first"), ("products", "query", "second")]
    assert len(requests) == len(parent.llm_calls) == 4
    assert all(body["model"] == route.model and body["store"] is False for body in requests)
    assert {record.provider_id for record in parent.llm_calls} == {route.provider_id}
    assert {row["state"] for row in metadata["model_requests"].values()} == {"completed"}
    assert parent.metadata["reserved_cost_units"] == 0
    assert metadata["coordinator_active"] is False and metadata["revoked"] is True
    assert parent.final_output["business_result"]["success"] is True
    total = sum(record.cost_units for record in parent.llm_calls + child.tool_calls)
    assert parent.metadata["ai_cost_units_total"] == total
    assert ledger.get_model_wallet(str(actor.user_id))["balance_units"] == 100 - total
