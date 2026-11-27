"""Controlled Responses SDK fixtures for original-goal and host-evidence verification.

These fixtures do not measure real-model quality."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
    goal_answers,
)
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    classify_runtime_result,
)
from app.infrastructure.xiaox.binding import XiaoxBinding
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def receipt(name="first", *, read_only=True):
    operation = {
        "tool_id": "products" if read_only else "sales",
        "action": "query" if read_only else "confirm",
        "params": {"target": name},
    }
    return {
        **operation,
        "fingerprint": canonical_digest(operation),
        "call_id": "call-" + name,
        "child_run_id": "child-" + name,
        "child_task_id": "task-" + name,
        "state": "completed",
        "read_only": read_only,
        "created_at": "2026-11-22T10:00:00Z",
        "receipt": {
            "run_id": "child-" + name,
            "task_id": "task-" + name,
            "status": "completed",
            "success": True,
            "verified": True,
            "tool_calls": [{"output": {"success": True, "data": {"target": name}}}],
        },
    }


def goal(
    source="查询first",
    *,
    goal_id="first",
    kind="read",
    status="satisfied",
    evidence_ids=None,
    source_id="request",
):
    return {
        "goal_id": goal_id,
        "source_id": source_id,
        "source": source,
        "kind": kind,
        "status": status,
        "evidence_ids": ["child-" + goal_id] if evidence_ids is None else evidence_ids,
        "reason": "按原目标核对宿主证据",
    }


def review(*goals, violations=None, feedback="", feedback_disposition="none"):
    return {
        "goals": list(goals),
        "violations": violations or [],
        "uncovered_sources": [],
        "feedback": feedback,
        "feedback_disposition": feedback_disposition,
    }


def response(payload, *, status="completed", output=None, text=None):
    return {
        "id": "resp-fixture",
        "object": "response",
        "created_at": 1,
        "model": "fixture-model",
        "status": status,
        "output": output
        if output is not None
        else [
            {
                "type": "message",
                "id": "msg-fixture",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": text
                        if text is not None
                        else json.dumps(payload, ensure_ascii=False),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 20, "output_tokens": 20, "total_tokens": 40},
    }


@pytest.fixture
def verifier(monkeypatch):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    run = AgentRun(user_id="71", message="查询first，再查询second", run_id="goal-parent")
    run.metadata.update(
        runtime_context={"user_id": "71", "tenant_id": "7"},
        _xiaox_history=[],
        _xiaox_input_data=None,
        xiaox_runtime={"deadline_at": time.time() + 30},
    )
    run.metadata["runtime_goal_contract"] = build_goal_contract(run)
    state = SimpleNamespace(
        run=run,
        rows=[receipt("first"), receipt("second")],
        output="已分别查询first与second。",
        replies=[],
        requests=[],
        client_options=[],
    )
    state.config = SimpleNamespace(
        model="fixture-model",
        provider_url="http://127.0.0.1:41111/api/agent-runtime/xiaox",
        provider_token="scoped-model-grant",
        context_window=32000,
        auto_compact_token_limit=24000,
        timeout_seconds=20,
        turn_timeout_seconds=30,
    )
    real_client = openai.OpenAI

    def handle(request):
        state.requests.append(request)
        if observer := getattr(state, "observe_request", None):
            observer(request)
        assert state.replies, "verifier exceeded its expected budget"
        result = state.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json=result)

    def client(**kwargs):
        original = kwargs.pop("http_client")
        state.client_options.append(
            {**kwargs, "trust_env": original._trust_env, "redirects": original.follow_redirects}
        )
        original.close()
        return real_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )

    def no_execution(*_args, **_kwargs):
        raise AssertionError("result verifier attempted a business action")

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(AgentToolExecutor, "execute", no_execution)

    def consume_format_retry():
        metadata = state.run.metadata["xiaox_runtime"]
        if metadata.get("goal_format_retry_used", False) is not False:
            return False
        metadata["goal_format_retry_used"] = True
        return True

    state.verify = lambda: verify_runtime_goal(
        XiaoxBinding(state.run),
        state.config,
        rows=state.rows,
        output=state.output,
        consume_format_retry=consume_format_retry,
    )

    def classify(report, *, runtime_status="completed", mode="auto"):
        result = base_runtime_result(run.run_id)
        result["output"] = state.output
        metadata = {
            **run.metadata["xiaox_runtime"],
            "goal_contract": run.metadata["runtime_goal_contract"],
            "goal_answers": goal_answers(run),
            "goal_verification": report,
        }
        status = classify_runtime_result(result, state.rows, metadata, mode, runtime_status)
        return status, result

    state.classify = classify
    return state
