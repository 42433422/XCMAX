"""Browser decisions keep the common gateway's model and revision boundaries."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import browser_loop, browser_loop_model
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.domain.shared_services.conversation_service import ConversationRevisionError
from app.infrastructure.llm import model_context_windows as windows


def _browser(monkeypatch, *, window=16384, revision_change=""):
    run = AgentRun(user_id="71", message="读取页面结果")
    run.metadata["browser_loop"] = {
        "tool_id": "mcp__budget_browser",
        "deadline_at": time.time() + 30,
        "decisions": 0,
        "phase": "observe",
    }
    run.steps = [
        AgentStep(
            node_id="snapshot",
            tool_id="mcp__budget_browser",
            action="browser_snapshot",
            status="completed",
            output={
                "success": True,
                "session_id": "original-browser-generation",
                "content": "### Snapshot\n```yaml\n- generic: 页面已加载\n```",
            },
        )
    ]
    run.status = "running"
    requests, reserves, revision = [], [], [1]

    def guard():
        if revision[0] != 1:
            raise ConversationRevisionError("conversation changed while awaiting the model")

    async def resolve(*args, **kwargs):
        await asyncio.sleep(0)
        if revision_change == "routing":
            revision[0] = 2
            guard()
        return windows.ModelLimits(
            model="small-browser-model",
            context_window=window,
            max_output_tokens=2048,
            source="controlled-provider-capabilities",
            request_guard=guard,
        )

    async def complete(**kwargs):
        requests.append(kwargs)
        await asyncio.sleep(0)
        if revision_change == "completion":
            revision[0] = 2
        return {
            "model": "small-browser-model",
            "choices": [
                {"message": {"content": json.dumps({"mode": "wait", "reason": "确认页面"})}}
            ],
        }

    def reserve(**kwargs):
        reserves.append(kwargs)
        return 1

    monkeypatch.setattr(windows, "resolve_model_limits", resolve)
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider",
        lambda **kwargs: SimpleNamespace(chat_completion=complete),
    )
    monkeypatch.setattr(browser_loop_model, "get_ai_conversation_service", lambda: None)
    monkeypatch.setattr(browser_loop_model, "estimate_llm_cost_units", reserve)
    monkeypatch.setattr(browser_loop_model, "budget_exceeded_payload", lambda *a, **k: {})
    monkeypatch.setattr(browser_loop, "browser_server_config", lambda _: object())
    monkeypatch.setattr(browser_loop, "_actions", lambda _: [])
    usage = SimpleNamespace(refresh_llm_metadata=lambda _: None)
    return run, usage, requests, reserves


@pytest.mark.parametrize("default", [1024, 4096])
def test_browser_system_default_adapts_to_2048_output_capability(monkeypatch, default):
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", str(default))
    run, usage, requests, reserves = _browser(monkeypatch)
    decision = browser_loop_model.request_browser_decision(
        run, {}, observation={"page": "页面已加载"}, actions=[], usage=usage
    )
    assert decision is not None and decision.mode == "wait"
    assert len(requests) == 1 and requests[0]["max_tokens"] == min(default, 2048)
    assert reserves[0]["completion_tokens"] == default


def test_browser_keeps_context_budget_rejection_without_a_clarification(monkeypatch):
    run, usage, requests, _ = _browser(monkeypatch, window=1024)
    assert browser_loop.advance_browser_run(run, {}, usage) is True
    assert run.status == "blocked" and run.error == "browser_context_budget_exceeded"
    assert run.metadata["browser_loop"]["context_budget"]["reason"]
    assert requests == [] and len(run.steps) == 1


@pytest.mark.parametrize("during", ["routing", "completion"])
def test_browser_rejects_revision_changed_across_gateway_await(monkeypatch, during):
    run, usage, requests, _ = _browser(monkeypatch, revision_change=during)
    assert browser_loop.advance_browser_run(run, {}, usage) is True
    assert run.status == "blocked" and run.error == "browser_conversation_revision_changed"
    assert len(requests) == (during == "completion")
    assert len(run.steps) == 1 and run.steps[0].action == "browser_snapshot"


@pytest.mark.parametrize("prefix", ["browser_driver_failure", "browser_model_budget_exceeded"])
def test_browser_exception_details_never_become_public_error_codes(monkeypatch, caplog, prefix):
    run, usage, requests, _ = _browser(monkeypatch)
    detail = f"{prefix}: private-credential in /internal/browser/session"

    def fail(*args, **kwargs):
        raise RuntimeError(detail)

    monkeypatch.setattr(browser_loop, "request_browser_decision", fail)
    assert browser_loop.advance_browser_run(run, {}, usage) is True
    assert run.status == "blocked" and run.error == "browser_decision_invalid"
    assert run.final_output["error_code"] == "browser_decision_invalid"
    assert detail not in str(run.to_dict())
    assert detail in caplog.text
    assert requests == [] and len(run.steps) == 1
