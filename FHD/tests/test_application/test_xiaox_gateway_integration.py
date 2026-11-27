"""Real pinned SDK/CLI, private HTTP and MCP; only Responses output is a fixture.

The temporary qualification document admits test-owned loopback infrastructure.
This is protocol acceptance, never a real-model deployment qualification receipt.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import gateway
from app.infrastructure.xiaox.local_server import LocalRuntimeServer
from app.infrastructure.xiaox.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
    qualification_host_identity,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_qualification import synthetic_qualification


def _events(index, item, model):
    initial = (
        {**item, "arguments": ""} if item["type"] == "function_call" else {**item, "content": []}
    )
    response = {
        "id": f"resp-fixture-{index}",
        "object": "response",
        "created_at": 1,
        "model": model,
        "status": "in_progress",
        "output": [],
    }
    events = [
        {"type": "response.created", "response": response},
        {"type": "response.output_item.added", "output_index": 0, "item": initial},
    ]
    common = {"item_id": item["id"], "output_index": 0}
    if item["type"] == "function_call":
        events.extend(
            [
                {
                    "type": "response.function_call_arguments.delta",
                    **common,
                    "delta": item["arguments"],
                },
                {
                    "type": "response.function_call_arguments.done",
                    **common,
                    "arguments": item["arguments"],
                },
            ]
        )
    else:
        part = item["content"][0]
        events.extend(
            [
                {
                    "type": "response.content_part.added",
                    **common,
                    "content_index": 0,
                    "part": {**part, "text": ""},
                },
                {
                    "type": "response.output_text.delta",
                    **common,
                    "content_index": 0,
                    "delta": part["text"],
                },
                {
                    "type": "response.output_text.done",
                    **common,
                    "content_index": 0,
                    "text": part["text"],
                },
                {"type": "response.content_part.done", **common, "content_index": 0, "part": part},
            ]
        )
    events.extend(
        [
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {
                "type": "response.completed",
                "response": {
                    **response,
                    "status": "completed",
                    "output": [item],
                    "usage": {"input_tokens": 128, "output_tokens": 32, "total_tokens": 160},
                },
            },
        ]
    )
    return [
        f"data: {json.dumps({**event, 'sequence_number': number}, ensure_ascii=False)}\n\n".encode()
        for number, event in enumerate(events)
    ]


def _request_input_target(tools):
    for tool in tools:
        if tool.get("type") == "function" and str(tool.get("name", "")).endswith("request_input"):
            return {"name": tool["name"]}
        if tool.get("type") == "namespace":
            for child in tool.get("tools", []):
                if child.get("name") == "request_input":
                    return {"namespace": tool["name"], "name": child["name"]}
    raise AssertionError("The real Xiaox runtime did not discover the controlled MCP tool")


def test_real_pinned_cli_private_gateway_clarification_resume_and_billing(
    trusted_actor, tmp_path, monkeypatch
):
    pytest.importorskip("openai_codex")
    cli = pytest.importorskip("codex_cli_bin")
    binary = Path(cli.bundled_codex_path())
    version = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, timeout=10, check=True
    )
    if CODEX_VERSION not in version.stdout.split():
        pytest.skip("This integration requires the exact pinned CLI, never a newer system binary")

    from app.infrastructure.billing import model_usage as ledger
    from app.infrastructure.xiaox import model_gateway

    actor = trusted_actor()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    monkeypatch.setattr(gateway, "get_agent_run_repository", lambda: repository)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    monkeypatch.setattr(
        "app.infrastructure.llm.model_admission.admit_model_call", lambda *args, **kwargs: None
    )
    initial_balance = 100
    task_budget = 96
    ledger.set_model_wallet_balance(str(actor.user_id), initial_balance)
    upstream = FastAPI()
    requests = []
    model_tools = []
    original_prepare = model_gateway._prepare_body

    def prepare(body, route):
        model_tools.append(
            [{key: item.get(key) for key in ("type", "name")} for item in body.get("tools", [])]
        )
        (tmp_path / "model-tools.json").write_text(
            json.dumps(body.get("tools", []), ensure_ascii=False, indent=2)
        )
        return original_prepare(body, route)

    monkeypatch.setattr(model_gateway, "_prepare_body", prepare)

    @upstream.post("/v1/responses")
    async def respond(request: Request):
        body = await request.json()
        requests.append(body)
        index = len(requests)
        if not body.get("stream"):
            from tests.test_application.test_xiaox_goal_verifier import response

            payload = json.loads(body["input"][1]["content"])
            assert payload["task"] == "verify_runtime_goal" and body["tools"] == []
            goals = [
                {
                    "goal_id": "reply",
                    "source_id": "request",
                    "source": payload["original_request"]["text"],
                    "kind": "reply",
                    "status": "satisfied",
                    "evidence_ids": ["response"],
                    "reason": "Controlled protocol fixture verifies the recorded reply",
                }
            ]
            goals.extend(
                {
                    "goal_id": "answer-" + str(number),
                    "source_id": answer["source_id"],
                    "source": answer["answer"],
                    "kind": "reply",
                    "status": "satisfied",
                    "evidence_ids": ["response"],
                    "reason": "Original answer retained",
                }
                for number, answer in enumerate(payload["answers"])
            )
            return response(
                {"goals": goals, "violations": [], "uncovered_sources": [], "feedback": ""}
            )
        if index == 1:
            item = {
                "type": "function_call",
                "id": "fc-fixture-1",
                "call_id": "call-fixture-1",
                **_request_input_target(body.get("tools", [])),
                "arguments": json.dumps({"question": "请确认月份"}, ensure_ascii=False),
                "status": "completed",
            }
        else:
            item = {
                "type": "message",
                "id": f"msg-fixture-{index}",
                "status": "completed",
                "role": "assistant",
                "phase": "final_answer",
                "content": [
                    {
                        "type": "output_text",
                        "text": "请确认月份" if index == 2 else "已收到月份回答",
                        "annotations": [],
                    }
                ],
            }
        return StreamingResponse(
            iter(_events(index, item, body["model"])), media_type="text/event-stream"
        )

    with LocalRuntimeServer(upstream) as server:
        route = ModelRoute(
            base_url=server.url + "/v1",
            model="fixture-model",
            provider_id="integration-fixture",
            upstream_vendor="test-fixture",
            context_window=32000,
            max_output_tokens=4000,
        )
        # Synthetic receipt for contract tests, never evidence of real route qualification.
        qualification = tmp_path / "test-only-qualification.json"
        qualification.write_text(json.dumps(synthetic_qualification(route, qualification.parent)))
        settings = RuntimeSettings(
            engine="xiaox",
            route=route,
            runtime_root=tmp_path / "runtime",
            codex_bin=str(binary),
            qualification_file=qualification,
            turn_timeout_seconds=45,
        )
        # Keep one complete review request reserved inside the original budget
        # while execution settles its smaller actual usage.
        context = {
            **actor.context,
            "turn_id": "cli-integration-one",
            "ai_cost_budget_units": task_budget,
        }
        events = []
        options = {
            "system_prompt": "只使用受控 MCP 工具；缺少月份时调用 request_input。",
            "settings": settings,
            "completion_mode": "reply",
            "on_event": events.append,
        }
        first = gateway.run_runtime_task(
            task="请记录我选择的月份并回复收到", runtime_context=context, **options
        )
        assert first.get("needs_user_input") is True, json.dumps(
            {
                "result": {
                    key: first.get(key) for key in ("ok", "exit_status", "error", "error_code")
                },
                "errors": [
                    event
                    for event in events
                    if event["method"] == "error"
                    or (event.get("payload", {}).get("item", {}).get("status") == "failed")
                ],
                "request_tools": model_tools,
            },
            ensure_ascii=False,
        )
        parent = repository.get(first["run_id"])
        thread_id = parent.metadata["xiaox_runtime"]["thread_id"]
        assert (
            parent.status == "waiting_user"
            and parent.metadata["xiaox_runtime"]["waiting_input"]["question"] == "请确认月份"
        )
        second = gateway.run_runtime_task(
            task="五月",
            run_id=first["run_id"],
            runtime_context={**context, "turn_id": "cli-integration-two"},
            answer_to_waiting_input=True,
            **options,
        )

    saved = repository.get(first["run_id"])
    metadata = saved.metadata if saved is not None else {}
    runtime = metadata.get("xiaox_runtime") or {}
    verification = metadata.get("runtime_goal_verification") or {}
    # A JSON string survives short traceback/JUnit formatting; a dict message
    # abbreviates the error fields. Never dump credentials or the full context.
    resume_diagnostic = json.dumps(
        {
            "second": {
                key: second.get(key)
                for key in ("ok", "error", "error_code", "exit_status", "failure_stage")
            },
            "sql_run": {
                key: getattr(saved, key, None)
                for key in ("run_id", "status", "created_at", "updated_at")
            },
            "runtime": {
                key: runtime.get(key)
                for key in (
                    "generation",
                    "runtime_status",
                    "active_seconds",
                    "active_started_at",
                    "deadline_at",
                    "model_reconciliation_required",
                )
            },
            "model_requests": {
                request_id: {
                    **{
                        key: call.get(key)
                        for key in ("state", "attempt", "started_at", "finished_at", "duration_ms")
                    },
                    "diagnostic": {
                        key: (call.get("diagnostic") or {}).get(key)
                        for key in ("failure_kind", "stage", "request_phase", "outcome")
                    },
                }
                for request_id, call in (runtime.get("model_requests") or {}).items()
            },
            "verification": {
                key: verification.get(key) for key in ("status", "error_code", "accepted")
            },
            "timeline": [[event.event_type, event.created_at] for event in saved.events]
            if saved is not None
            else [],
        },
        ensure_ascii=False,
        default=str,
    )
    if second.get("ok") is not True or second.get("exit_status") != "reply_completed":
        print("XIAOX_RESUME_DIAGNOSTIC " + resume_diagnostic)
    assert second["ok"] is True and second["exit_status"] == "reply_completed", resume_diagnostic
    assert second["business_completed"] is False and second["output"] == "已收到月份回答"
    assert saved.metadata["xiaox_runtime"]["thread_id"] == thread_id
    assert "waiting_input" not in saved.metadata["xiaox_runtime"]
    assert saved.metadata["xiaox_runtime"]["revoked"] is True
    assert saved.metadata["xiaox_runtime"]["coordinator_active"] is False
    assert len(requests) == len(saved.llm_calls) == 4
    assert {
        entry["state"] for entry in saved.metadata["xiaox_runtime"]["model_requests"].values()
    } == {"completed"}
    assert saved.metadata["reserved_cost_units"] == 0
    assert saved.metadata["ai_cost_budget_units"] == task_budget
    assert saved.metadata["xiaox_runtime"]["verification_budget"]["model_calls"] == 1
    assert saved.metadata["xiaox_runtime"]["verification_budget"]["max_model_calls"] == 2
    assert (
        sum(
            row["purpose"] == "verification"
            for row in saved.metadata["xiaox_runtime"]["model_requests"].values()
        )
        == 1
    )
    assert saved.metadata["ai_cost_units_total"] == 4
    assert ledger.get_model_wallet(str(actor.user_id))["balance_units"] == initial_balance - 4
    assert all(body["model"] == route.model and body["store"] is False for body in requests)
    assert saved.final_output["business_result"]["status"] == "reply_completed"
    assert saved.final_output["business_result"]["success"] is False
    assert len(repository.list_recent()) == 1
