"""Real CLI -> scoped HTTP/MCP -> dynamic actions -> independent corrective review.

Only the upstream model and business data are synthetic. The pinned SDK/CLI,
authorization, LangGraph action execution, SQL, original thread and billing run
normally. This is protocol acceptance, not real-provider qualification or a
measurement of the user's original exam.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.agent_runtime import gateway
from app.infrastructure.codex.local_server import LocalRuntimeServer
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
    qualification_host_identity,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_qualification import synthetic_qualification
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
def test_real_cli_corrects_missing_goal_in_original_thread_and_settles_parent(
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
    from app.infrastructure.billing import model_usage as ledger
    from app.infrastructure.codex import queued_runtime

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
    upstream = FastAPI()
    requests = []
    observed_parents = []

    @upstream.post("/v1/responses")
    async def respond(request: Request):
        assert request.headers["authorization"] == "Bearer synthetic-upstream-key"
        body = await request.json()
        requests.append(body)
        index = len(requests)
        if not body.get("stream"):
            assert index in {4, 7} and body["tools"] == []
            prompt = json.loads(body["input"][1]["content"])
            assert prompt["task"] == "verify_runtime_goal"
            assert prompt["original_request"]["text"] == task
            by_keyword = {row["params"]["keyword"]: row for row in prompt["evidence"]}
            assert set(by_keyword) == ({"first"} if index == 4 else {"first", "second"})
            goals = []
            for keyword, source in (
                ("first", "先查询 first 产品"),
                ("second", "再查询 second 产品"),
            ):
                evidence = by_keyword.get(keyword)
                goals.append(
                    {
                        "goal_id": keyword,
                        "source_id": "request",
                        "source": source,
                        "kind": "read",
                        "status": "satisfied" if evidence else "unmet",
                        "evidence_ids": [evidence["evidence_id"]] if evidence else [],
                        "reason": "Synthetic independent judgement over actual SQL action receipts",
                    }
                )
            content = {
                "goals": goals,
                "violations": [],
                "uncovered_sources": [],
                "feedback": "还缺少 second 产品查询" if index == 4 else "两个原始查询均有实际回执",
            }
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
        if index == 1:
            parents = repository.list_recent()
            assert len(parents) == 1 and dispatched == []
            parent = parents[0]
            observed_parents.append(parent.run_id)
            assert parent.metadata["runtime_goal_contract"]["request"]["text"] == task
            assert "runtime_frozen_plan" not in parent.metadata
            action, params = "capability_describe", {"tool_id": "products", "action": "query"}
        elif index in {2, 5}:
            if index == 2:
                outputs = [
                    row for row in body["input"] if row.get("type") == "function_call_output"
                ]
                assert "schema_digest" in json.dumps(outputs), "CLI must return the actual ToolSpec"
            else:
                assert "还缺少 second 产品查询" in json.dumps(body["input"], ensure_ascii=False)
                assert dispatched == [("products", "query", "first")]
            keyword = "first" if index == 2 else "second"
            action, params = (
                "execute_action",
                {
                    "call_id": keyword + "-product",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": keyword},
                    "schema_digest": get_tool_action_spec("products", "query").schema_digest,
                },
            )
        else:
            assert index in {3, 6}, "Unexpected model call or retired planner fallback"
            outputs = [row for row in body["input"] if row.get("type") == "function_call_output"]
            assert outputs, "CLI must return original action receipts to the model"
            expected = [("products", "query", "first")]
            if index == 6:
                expected.append(("products", "query", "second"))
            assert dispatched == expected
            item = _message(
                index, "已查询 first。" if index == 3 else "已按顺序查询 first 和 second。"
            )
            return StreamingResponse(
                iter(_events(index, item, body["model"])), media_type="text/event-stream"
            )
        item = {
            "type": "function_call",
            "id": f"fc-goal-fixture-{index}",
            "call_id": f"call-goal-fixture-{index}",
            **_tool_target(body["tools"], action),
            "arguments": json.dumps(params),
            "status": "completed",
        }
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
        # Synthetic receipt for contract tests, never evidence of real route qualification.
        qualification = tmp_path / "test-only-qualification.json"
        qualification.write_text(
            json.dumps(synthetic_qualification(route, qualification.parent)),
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
            system_prompt="发现已授权能力，观察实际结果后逐步完成原任务，再独立核验。",
            runtime_context={
                **actor.context,
                "turn_id": f"real-cli-host-goal-fixture-{queued}",
                "ai_cost_budget_units": 96,
            },
            allowed_actions=["products.query"],
            completion_mode="auto",
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
    assert len([event for event in parent.events if event.event_type == "runtime.goal.bound"]) == 1
    assert set(metadata["calls"]) == {"first-product", "second-product"}
    children = []
    for keyword in ("first", "second"):
        receipt = metadata["calls"][keyword + "-product"]["receipt"]
        assert receipt["verified"] is True
        child = repository.get(receipt["run_id"])
        assert child.status == "completed" and len(child.tool_calls) == 1
        assert child.tool_calls[0].params["keyword"] == keyword
        children.append(child)
    assert len(repository.list_recent()) == 3
    assert dispatched == [("products", "query", "first"), ("products", "query", "second")]
    assert result["rounds"] == 2
    assert [
        event.data["status"]
        for event in parent.events
        if event.event_type == "runtime.goal.verified"
    ] == ["needs_work", "verified"]
    assert len(requests) == len(parent.llm_calls) == result["model_request_attempts"] == 7
    assert all(body["model"] == route.model and body["store"] is False for body in requests)
    assert {record.provider_id for record in parent.llm_calls} == {route.provider_id}
    assert {row["state"] for row in metadata["model_requests"].values()} == {"completed"}
    assert parent.metadata["reserved_cost_units"] == 0
    assert metadata["coordinator_active"] is False and metadata["revoked"] is True
    assert parent.final_output["business_result"]["success"] is True
    total = sum(record.cost_units for record in parent.llm_calls) + sum(
        record.cost_units for child in children for record in child.tool_calls
    )
    assert parent.metadata["ai_cost_units_total"] == total
    assert ledger.get_model_wallet(str(actor.user_id))["balance_units"] == 100 - total
