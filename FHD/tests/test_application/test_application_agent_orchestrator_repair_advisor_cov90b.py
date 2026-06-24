"""Behavior tests for agent_orchestrator.repair_advisor (cov90b wave).

Targets previously-uncovered branches: enablement flags, attempt-limit
fallthrough, request_llm_repair error/empty/no-patch paths, plan-metadata
guards, _repair_messages recoverable-error fallback, _run_async running-loop
path, content/json extraction edge cases, params-patch fallback, and the
coerce helper except branches.

Everything external (the LLM call) is patched at its use-site inside the
module; no network, no DB, no event loop assumptions.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.application.agent_orchestrator import repair_advisor as ra
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, LLMCall

MOD = "app.application.agent_orchestrator.repair_advisor"


def _run(metadata: dict[str, Any] | None = None) -> AgentRun:
    return AgentRun(user_id="u1", message="hello", metadata=dict(metadata or {}))


def _step(**kwargs: Any) -> AgentStep:
    base: dict[str, Any] = {
        "node_id": "n1",
        "tool_id": "tool.read",
        "action": "fetch",
    }
    base.update(kwargs)
    return AgentStep(**base)


# --------------------------------------------------------------------------- #
# is_llm_repair_enabled
# --------------------------------------------------------------------------- #


def test_enabled_by_policy_llm_repair_flag():
    # line 28-29: policy.get("llm_repair") is True -> True (from plan_metadata)
    run = _run({"plan": {"metadata": {"repair_policy": {"llm_repair": True}}}})
    assert ra.is_llm_repair_enabled(run, {}) is True


def test_enabled_by_policy_llm_repair_enabled_flag():
    run = _run({"plan": {"metadata": {"repair_policy": {"llm_repair_enabled": True}}}})
    assert ra.is_llm_repair_enabled(run, {}) is True


def test_enabled_by_policy_mode_keyword():
    # line 30-31: mode in {llm,hybrid,auto}
    run = _run()
    assert ra.is_llm_repair_enabled(run, {"repair_policy": {"mode": "Hybrid"}}) is True


def test_enabled_by_container_flag():
    # line 32-33: container.get("llm_repair_enabled") is True
    run = _run()
    assert ra.is_llm_repair_enabled(run, {"llm_repair_enabled": True}) is True


def test_disabled_when_nothing_set():
    run = _run()
    assert ra.is_llm_repair_enabled(run, {"repair_policy": {"mode": "manual"}}) is False


def test_disabled_when_policy_not_a_dict():
    # policy normalized to {} when not a dict
    run = _run()
    assert ra.is_llm_repair_enabled(run, {"repair_policy": "nope"}) is False


# --------------------------------------------------------------------------- #
# llm_repair_attempt_limit
# --------------------------------------------------------------------------- #


def test_attempt_limit_from_node_policy():
    run = _run()
    step = _step()
    ctx = {"repair_policy": {"n1": {"llm_max_attempts": 4}}}
    assert ra.llm_repair_attempt_limit(run, step, ctx) == 4


def test_attempt_limit_from_container_repair_max():
    run = _run()
    step = _step()
    ctx = {"repair_policy": {}, "llm_repair_max_attempts": 7}
    assert ra.llm_repair_attempt_limit(run, step, ctx) == 7


def test_attempt_limit_fallback_to_step_max():
    # line 57: nothing positive -> step.max_repair_attempts or 1
    run = _run()
    step = _step(max_repair_attempts=3)
    assert ra.llm_repair_attempt_limit(run, step, {}) == 3


def test_attempt_limit_fallback_to_one():
    run = _run()
    step = _step(max_repair_attempts=0)
    assert ra.llm_repair_attempt_limit(run, step, {}) == 1


# --------------------------------------------------------------------------- #
# _plan_metadata
# --------------------------------------------------------------------------- #


def test_plan_metadata_non_dict_plan_returns_empty():
    # line 118-119: plan is not a dict
    run = _run({"plan": "not-a-dict"})
    assert ra._plan_metadata(run) == {}


def test_plan_metadata_non_dict_metadata_returns_empty():
    run = _run({"plan": {"metadata": "nope"}})
    assert ra._plan_metadata(run) == {}


def test_plan_metadata_returns_copy():
    inner = {"repair_policy": {"mode": "llm"}}
    run = _run({"plan": {"metadata": inner}})
    out = ra._plan_metadata(run)
    assert out == inner
    out["mutated"] = 1
    assert "mutated" not in inner  # returned a copy


# --------------------------------------------------------------------------- #
# request_llm_repair (patch _run_async + the LLM coroutine factory)
# --------------------------------------------------------------------------- #


def _patch_llm(response: Any):
    """Patch chat_completion_openai_format (returns a sentinel, never awaited
    because _run_async is also patched) and _run_async (returns the chosen
    response). Using a sync stub avoids an un-awaited-coroutine warning."""

    def _fake_chat(*_args: Any, **_kwargs: Any):
        return "unused-coroutine-placeholder"

    return (
        patch(f"{MOD}.chat_completion_openai_format", _fake_chat),
        patch(f"{MOD}._run_async", return_value=response),
    )


def test_request_repair_non_dict_response():
    # line 76-83: response is not a dict
    run = _run()
    step = _step()
    p1, p2 = _patch_llm("not a dict")
    with p1, p2:
        out = ra.request_llm_repair(run, step, {})
    assert out["success"] is False
    assert out["message"] == "LLM repair returned no response"
    assert isinstance(out["llm_call"], LLMCall)
    assert out["llm_call"].status == "failed"
    assert out["llm_call"].error == "empty response"


def test_request_repair_invalid_json_content():
    # line 88-96: parsed is not a dict (content is not JSON)
    run = _run()
    step = _step()
    resp = {"choices": [{"message": {"content": "this is not json at all"}}]}
    p1, p2 = _patch_llm(resp)
    with p1, p2:
        out = ra.request_llm_repair(run, step, {})
    assert out["success"] is False
    assert out["message"] == "LLM repair response is not valid JSON"
    assert out["raw"] == "this is not json at all"
    assert out["llm_call"].status == "failed"


def test_request_repair_no_params_patch():
    # line 99-105: parsed dict but no params_patch
    run = _run()
    step = _step()
    resp = {"choices": [{"message": {"content": '{"reason": "x", "confidence": 0.5}'}}]}
    p1, p2 = _patch_llm(resp)
    with p1, p2:
        out = ra.request_llm_repair(run, step, {})
    assert out["success"] is False
    assert out["message"] == "LLM repair returned no params_patch"
    assert "raw" in out


def test_request_repair_success():
    run = _run()
    step = _step()
    content = '{"params_patch": {"limit": 5}, "reason": "retry smaller", "confidence": 0.9}'
    resp = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "model": "gpt-x",
        "provider": "openai",
    }
    p1, p2 = _patch_llm(resp)
    with p1, p2:
        out = ra.request_llm_repair(run, step, {})
    assert out["success"] is True
    assert out["params_patch"] == {"limit": 5}
    assert out["reason"] == "retry smaller"
    assert out["confidence"] == 0.9
    assert out["llm_call"].status == "completed"
    assert out["llm_call"].model == "gpt-x"
    assert out["llm_call"].total_tokens == 30


# --------------------------------------------------------------------------- #
# _repair_messages
# --------------------------------------------------------------------------- #


def test_repair_messages_spec_recoverable_error_falls_back():
    # line 135-136: get_tool_action_spec raises a RECOVERABLE error -> spec={}
    run = _run()
    step = _step(observations=[{"k": "v"}], params={"a": 1})
    with patch(
        "app.application.agent_orchestrator.tool_spec.get_tool_action_spec",
        side_effect=ValueError("boom"),
    ):
        messages = ra._repair_messages(run, step, {"source": "cli", "extra": "drop"})
    assert isinstance(messages, list) and len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    # tool_spec absent in payload (fell back to {})
    assert '"tool_spec": {}' in messages[1]["content"]
    # runtime_hint filtered to allowed keys only
    assert '"source": "cli"' in messages[1]["content"]
    assert "extra" not in messages[1]["content"]


def test_repair_messages_with_spec_none():
    run = _run()
    step = _step()
    with patch(
        "app.application.agent_orchestrator.tool_spec.get_tool_action_spec",
        return_value=None,
    ):
        messages = ra._repair_messages(run, step, {})
    assert '"tool_spec": {}' in messages[1]["content"]


# --------------------------------------------------------------------------- #
# _run_async
# --------------------------------------------------------------------------- #


def test_run_async_no_running_loop():
    async def coro():
        return 42

    assert ra._run_async(coro()) == 42


async def test_run_async_with_running_loop():
    # line 185-186: a loop is already running -> ThreadPoolExecutor path
    async def coro():
        return "threaded"

    assert ra._run_async(coro()) == "threaded"


# --------------------------------------------------------------------------- #
# _extract_content
# --------------------------------------------------------------------------- #


def test_extract_content_from_message():
    resp = {"choices": [{"message": {"content": "hi"}}]}
    assert ra._extract_content(resp) == "hi"


def test_extract_content_from_choice_text():
    # line 197: first has no message dict -> first.get("text")
    resp = {"choices": [{"text": "legacy completion"}]}
    assert ra._extract_content(resp) == "legacy completion"


def test_extract_content_top_level_fallback():
    # line 198: no usable choices -> response content/text
    assert ra._extract_content({"content": "topc"}) == "topc"
    assert ra._extract_content({"text": "topt"}) == "topt"
    assert ra._extract_content({}) == ""


def test_extract_content_empty_choices_list():
    assert ra._extract_content({"choices": [], "text": "fallback"}) == "fallback"


# --------------------------------------------------------------------------- #
# _extract_json_object
# --------------------------------------------------------------------------- #


def test_extract_json_empty_returns_none():
    # line 203-204
    assert ra._extract_json_object("   ") is None
    assert ra._extract_json_object("") is None


def test_extract_json_fenced_block():
    # line 205-208: ```json fence stripped
    assert ra._extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_fenced_plain():
    assert ra._extract_json_object('```\n{"b": 2}\n```') == {"b": 2}


def test_extract_json_direct_object():
    assert ra._extract_json_object('{"x": 9}') == {"x": 9}


def test_extract_json_non_dict_top_level_returns_none():
    # line 211: parsed JSON is a list, not a dict
    assert ra._extract_json_object("[1, 2, 3]") is None


def test_extract_json_embedded_object():
    # line 212-222: leading json decode fails, then brace-scan succeeds
    text = 'Sure, here you go: {"k": "v"} -- done'
    assert ra._extract_json_object(text) == {"k": "v"}


def test_extract_json_no_braces_returns_none():
    # line 214-217: start<0
    assert ra._extract_json_object("no object here") is None


def test_extract_json_embedded_invalid_returns_none():
    # line 218-221: brace-scan candidate is invalid JSON
    assert ra._extract_json_object("prefix {not: valid json} suffix") is None


def test_extract_json_embedded_object_after_prose():
    # line 214-222: leading json.loads fails, brace-scan slice decodes to dict
    assert ra._extract_json_object('text {"only": true} tail') == {"only": True}


# --------------------------------------------------------------------------- #
# _extract_params_patch
# --------------------------------------------------------------------------- #


def test_extract_params_patch_aliases():
    assert ra._extract_params_patch({"patch_params": {"q": 1}}) == {"q": 1}
    assert ra._extract_params_patch({"set_params": {"q": 2}}) == {"q": 2}
    assert ra._extract_params_patch({"params": {"q": 3}}) == {"q": 3}


def test_extract_params_patch_returns_copy():
    inner = {"a": 1}
    out = ra._extract_params_patch({"params_patch": inner})
    out["b"] = 2
    assert inner == {"a": 1}


def test_extract_params_patch_no_match_returns_empty():
    # line 230
    assert ra._extract_params_patch({"reason": "x"}) == {}
    assert ra._extract_params_patch({"params_patch": "not-a-dict"}) == {}


# --------------------------------------------------------------------------- #
# _llm_call_from_response (provider_id derivation)
# --------------------------------------------------------------------------- #


def test_llm_call_provider_id_openai_compatible():
    call = ra._llm_call_from_response({"provider": "deepseek"}, 12.5)
    assert call.provider_id == "openai_compatible"
    assert call.provider == "deepseek"
    assert call.latency_ms == 12.5


def test_llm_call_provider_id_explicit_passthrough():
    call = ra._llm_call_from_response({"provider": "custom_x", "provider_id": "explicit_id"}, 1.0)
    assert call.provider_id == "explicit_id"


def test_llm_call_billing_unmetered_when_no_tokens():
    call = ra._llm_call_from_response({}, 0.0)
    assert call.cost_units == 0
    assert call.billing_status == "unmetered"


# --------------------------------------------------------------------------- #
# coerce helpers (except branches)
# --------------------------------------------------------------------------- #


def test_coerce_positive_int_normal_and_error():
    assert ra._coerce_positive_int("5") == 5
    assert ra._coerce_positive_int(-3) == 0  # clamped
    assert ra._coerce_positive_int(None) == 0
    # line 277-278: TypeError/ValueError -> 0
    assert ra._coerce_positive_int("abc") == 0
    assert ra._coerce_positive_int(object()) == 0


def test_coerce_int_normal_and_error():
    assert ra._coerce_int("7") == 7
    assert ra._coerce_int(None) == 0
    # line 285-286
    assert ra._coerce_int("xyz") == 0
    assert ra._coerce_int(object()) == 0


def test_coerce_float_normal_and_error():
    assert ra._coerce_float("1.5") == 1.5
    assert ra._coerce_float(None) == 0.0
    # line 292-293
    assert ra._coerce_float("nope") == 0.0
    assert ra._coerce_float(object()) == 0.0
