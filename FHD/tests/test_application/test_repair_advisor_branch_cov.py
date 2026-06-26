"""Branch-coverage tests for app.application.agent_orchestrator.repair_advisor.

Targets branches in:
* ``is_llm_repair_enabled`` — plan_metadata vs runtime_context, policy dict vs non-dict,
  llm_repair/llm_repair_enabled True, mode in {llm, hybrid, auto}, container-level flag.
* ``llm_repair_attempt_limit`` — node_policy vs policy vs container, coercion paths,
  fallback to step.max_repair_attempts.
* ``request_llm_repair`` — non-dict response, empty content, invalid JSON, no params_patch,
  success path, confidence coercion.
* ``_plan_metadata`` — plan not dict, metadata not dict.
* ``_extract_content`` — choices list empty, choices[0] not dict, message not dict,
  text fallback, content/text fallback.
* ``_extract_json_object`` — empty, code fence, json prefix, valid JSON, invalid JSON,
  substring extraction, non-dict JSON.
* ``_extract_params_patch`` — params_patch, patch_params, set_params, params, none.
* ``_llm_call_from_response`` — usage dict, provider_id resolution, total_tokens fallback.
* ``_coerce_positive_int`` / ``_coerce_int`` / ``_coerce_float`` — None, invalid, valid.
* ``_run_async`` — no running loop vs running loop.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.agent_orchestrator.repair_advisor import (
    _coerce_float,
    _coerce_int,
    _coerce_positive_int,
    _extract_content,
    _extract_json_object,
    _extract_params_patch,
    _llm_call_from_response,
    _plan_metadata,
    _repair_messages,
    _run_async,
    is_llm_repair_enabled,
    llm_repair_attempt_limit,
    request_llm_repair,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep

# ---------------------------------------------------------------------------
# helpers for building test fixtures
# ---------------------------------------------------------------------------


def _make_run(metadata: dict[str, Any] | None = None) -> AgentRun:
    return AgentRun(user_id="u1", message="do thing", metadata=metadata or {})


def _make_step(**overrides: Any) -> AgentStep:
    defaults: dict[str, Any] = {
        "node_id": "n1",
        "tool_id": "tool-1",
        "action": "run",
        "params": {"q": "x"},
        "risk": "low",
        "idempotent": True,
        "max_repair_attempts": 2,
    }
    defaults.update(overrides)
    return AgentStep(**defaults)


# ---------------------------------------------------------------------------
# is_llm_repair_enabled
# ---------------------------------------------------------------------------


class TestIsLlmRepairEnabled:
    def test_disabled_when_no_policy(self) -> None:
        run = _make_run()
        assert is_llm_repair_enabled(run, {}) is False

    def test_plan_metadata_llm_repair_true(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"llm_repair": True}}}})
        assert is_llm_repair_enabled(run, {}) is True

    def test_plan_metadata_llm_repair_enabled_true(self) -> None:
        run = _make_run(
            {"plan": {"metadata": {"repair_policy": {"llm_repair_enabled": True}}}}
        )
        assert is_llm_repair_enabled(run, {}) is True

    def test_plan_metadata_mode_llm(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"mode": "llm"}}}})
        assert is_llm_repair_enabled(run, {}) is True

    def test_plan_metadata_mode_hybrid(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"mode": "hybrid"}}}})
        assert is_llm_repair_enabled(run, {}) is True

    def test_plan_metadata_mode_auto(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"mode": "auto"}}}})
        assert is_llm_repair_enabled(run, {}) is True

    def test_plan_metadata_mode_with_whitespace_and_case(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"mode": "  LLM  "}}}})
        assert is_llm_repair_enabled(run, {}) is True

    def test_plan_metadata_mode_other_value(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"mode": "manual"}}}})
        assert is_llm_repair_enabled(run, {}) is False

    def test_runtime_context_llm_repair_true(self) -> None:
        run = _make_run()
        assert is_llm_repair_enabled(run, {"repair_policy": {"llm_repair": True}}) is True

    def test_runtime_context_container_level_flag(self) -> None:
        run = _make_run()
        assert is_llm_repair_enabled(run, {"llm_repair_enabled": True}) is True

    def test_policy_not_dict_ignored(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": "not-a-dict"}}})
        assert is_llm_repair_enabled(run, {}) is False

    def test_plan_not_dict(self) -> None:
        run = _make_run({"plan": "not-a-dict"})
        assert is_llm_repair_enabled(run, {}) is False

    def test_plan_metadata_not_dict(self) -> None:
        run = _make_run({"plan": {"metadata": "not-a-dict"}})
        assert is_llm_repair_enabled(run, {}) is False

    def test_runtime_context_none(self) -> None:
        run = _make_run()
        assert is_llm_repair_enabled(run, None) is False  # type: ignore[arg-type]

    def test_runtime_context_takes_precedence_when_plan_false(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"llm_repair": False}}}})
        assert is_llm_repair_enabled(run, {"repair_policy": {"llm_repair": True}}) is True


# ---------------------------------------------------------------------------
# llm_repair_attempt_limit
# ---------------------------------------------------------------------------


class TestLlmRepairAttemptLimit:
    def test_node_policy_llm_max_attempts(self) -> None:
        run = _make_run()
        step = _make_step(node_id="n1")
        ctx = {"repair_policy": {"n1": {"llm_max_attempts": 5}}}
        assert llm_repair_attempt_limit(run, step, ctx) == 5

    def test_node_policy_max_attempts(self) -> None:
        run = _make_run()
        step = _make_step(node_id="n1")
        ctx = {"repair_policy": {"n1": {"max_attempts": 3}}}
        assert llm_repair_attempt_limit(run, step, ctx) == 3

    def test_policy_level_llm_max_attempts(self) -> None:
        run = _make_run()
        step = _make_step(node_id="n1")
        ctx = {"repair_policy": {"llm_max_attempts": 4}}
        assert llm_repair_attempt_limit(run, step, ctx) == 4

    def test_policy_level_max_attempts(self) -> None:
        run = _make_run()
        step = _make_step(node_id="n1")
        ctx = {"repair_policy": {"max_attempts": 7}}
        assert llm_repair_attempt_limit(run, step, ctx) == 7

    def test_container_level_llm_repair_max_attempts(self) -> None:
        run = _make_run()
        step = _make_step(node_id="n1")
        ctx = {"llm_repair_max_attempts": 6}
        assert llm_repair_attempt_limit(run, step, ctx) == 6

    def test_falls_back_to_step_max_repair_attempts(self) -> None:
        run = _make_run()
        step = _make_step(max_repair_attempts=9)
        assert llm_repair_attempt_limit(run, step, {}) == 9

    def test_falls_back_to_default_1_when_step_zero(self) -> None:
        run = _make_run()
        step = _make_step(max_repair_attempts=0)
        assert llm_repair_attempt_limit(run, step, {}) == 1

    def test_node_policy_not_dict_ignored(self) -> None:
        run = _make_run()
        step = _make_step(node_id="n1")
        ctx = {"repair_policy": {"n1": "not-a-dict", "max_attempts": 2}}
        assert llm_repair_attempt_limit(run, step, ctx) == 2

    def test_zero_value_skipped(self) -> None:
        run = _make_run()
        step = _make_step(max_repair_attempts=8)
        ctx = {"repair_policy": {"llm_max_attempts": 0, "max_attempts": 0}}
        # both 0 → _coerce_positive_int returns 0 → skipped → fallback
        assert llm_repair_attempt_limit(run, step, ctx) == 8

    def test_invalid_value_skipped(self) -> None:
        run = _make_run()
        step = _make_step(max_repair_attempts=8)
        ctx = {"repair_policy": {"llm_max_attempts": "invalid"}}
        assert llm_repair_attempt_limit(run, step, ctx) == 8

    def test_plan_metadata_policy_checked(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"max_attempts": 11}}}})
        step = _make_step(max_repair_attempts=1)
        assert llm_repair_attempt_limit(run, step, {}) == 11

    def test_runtime_context_checked_before_plan_metadata(self) -> None:
        run = _make_run({"plan": {"metadata": {"repair_policy": {"max_attempts": 11}}}})
        step = _make_step(max_repair_attempts=1)
        ctx = {"repair_policy": {"max_attempts": 3}}
        assert llm_repair_attempt_limit(run, step, ctx) == 3


# ---------------------------------------------------------------------------
# request_llm_repair
# ---------------------------------------------------------------------------


class TestRequestLlmRepair:
    def test_non_dict_response_returns_failure(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value="not-a-dict",
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is False
        assert "no response" in result["message"]
        assert result["llm_call"].status == "failed"

    def test_empty_content_returns_failure(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={"choices": [{"message": {"content": ""}}]},
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is False
        # Empty content → _extract_json_object returns None → "not valid JSON"
        assert "not valid JSON" in result["message"]
        assert result["llm_call"].status == "failed"

    def test_invalid_json_returns_failure(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={"choices": [{"message": {"content": "not json"}}]},
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is False
        assert "not valid JSON" in result["message"]
        assert result["llm_call"].status == "failed"

    def test_no_params_patch_returns_failure(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {"message": {"content": '{"reason": "no patch here"}'}}
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is False
        assert "no params_patch" in result["message"]

    def test_success_path(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": '{"params_patch": {"q": "fixed"}, "reason": "ok", "confidence": 0.9}'
                        }
                    }
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"q": "fixed"}
        assert result["reason"] == "ok"
        assert result["confidence"] == 0.9

    def test_success_with_message_field(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": '{"params_patch": {"q": "x"}, "message": "because"}'
                        }
                    }
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["reason"] == "because"

    def test_confidence_none_coerced_to_zero(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {"message": {"content": '{"params_patch": {"q": "x"}, "confidence": null}'}}
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["confidence"] == 0.0

    def test_params_patch_from_patch_params_key(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {"message": {"content": '{"patch_params": {"alt": 1}}'}}
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"alt": 1}

    def test_params_patch_from_set_params_key(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {"message": {"content": '{"set_params": {"alt": 2}}'}}
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"alt": 2}

    def test_params_patch_from_params_key(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [{"message": {"content": '{"params": {"alt": 3}}'}}]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"alt": 3}

    def test_json_with_code_fence(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"params_patch\": {\"q\": \"fenced\"}}\n```"
                        }
                    }
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"q": "fenced"}

    def test_json_with_plain_code_fence(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "```\n{\"params_patch\": {\"q\": \"plain\"}}\n```"
                        }
                    }
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"q": "plain"}

    def test_json_embedded_in_text(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": 'Here is the patch: {"params_patch": {"q": "embedded"}} done'
                        }
                    }
                ]
            },
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is True
        assert result["params_patch"] == {"q": "embedded"}

    def test_json_array_not_dict_returns_failure(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.repair_advisor._run_async",
            return_value={"choices": [{"message": {"content": "[1, 2, 3]"}}]},
        ):
            result = request_llm_repair(run, step, {})
        assert result["success"] is False
        assert "not valid JSON" in result["message"]


# ---------------------------------------------------------------------------
# _plan_metadata
# ---------------------------------------------------------------------------


class TestPlanMetadata:
    def test_no_metadata_returns_empty(self) -> None:
        run = _make_run()
        assert _plan_metadata(run) == {}

    def test_plan_not_dict_returns_empty(self) -> None:
        run = _make_run({"plan": "not-dict"})
        assert _plan_metadata(run) == {}

    def test_metadata_not_dict_returns_empty(self) -> None:
        run = _make_run({"plan": {"metadata": "not-dict"}})
        assert _plan_metadata(run) == {}

    def test_metadata_none_returns_empty(self) -> None:
        run = _make_run({"plan": {"metadata": None}})
        assert _plan_metadata(run) == {}

    def test_valid_metadata_returns_dict(self) -> None:
        run = _make_run({"plan": {"metadata": {"key": "value"}}})
        assert _plan_metadata(run) == {"key": "value"}


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_choices_with_message_content(self) -> None:
        resp = {"choices": [{"message": {"content": "hello"}}]}
        assert _extract_content(resp) == "hello"

    def test_choices_with_first_not_dict(self) -> None:
        resp = {"choices": ["not-a-dict"]}
        assert _extract_content(resp) == ""

    def test_choices_with_message_not_dict(self) -> None:
        resp = {"choices": [{"message": "not-a-dict", "text": "from-text"}]}
        assert _extract_content(resp) == "from-text"

    def test_choices_empty_list(self) -> None:
        resp = {"choices": []}
        assert _extract_content(resp) == ""

    def test_choices_not_list(self) -> None:
        resp = {"choices": "not-a-list"}
        assert _extract_content(resp) == ""

    def test_no_choices_uses_content(self) -> None:
        resp = {"content": "from-content"}
        assert _extract_content(resp) == "from-content"

    def test_no_choices_uses_text(self) -> None:
        resp = {"text": "from-text"}
        assert _extract_content(resp) == "from-text"

    def test_no_choices_no_content_no_text(self) -> None:
        resp = {}
        assert _extract_content(resp) == ""

    def test_content_none(self) -> None:
        resp = {"choices": [{"message": {"content": None}}]}
        assert _extract_content(resp) == ""


# ---------------------------------------------------------------------------
# _extract_json_object
# ---------------------------------------------------------------------------


class TestExtractJsonObject:
    def test_empty_string_returns_none(self) -> None:
        assert _extract_json_object("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _extract_json_object("   ") is None

    def test_none_returns_none(self) -> None:
        assert _extract_json_object(None) is None  # type: ignore[arg-type]

    def test_valid_json_dict(self) -> None:
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_valid_json_array_returns_none(self) -> None:
        assert _extract_json_object("[1, 2, 3]") is None

    def test_invalid_json_no_braces_returns_none(self) -> None:
        assert _extract_json_object("not json at all") is None

    def test_code_fence_with_json_prefix(self) -> None:
        assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_code_fence_without_json_prefix(self) -> None:
        assert _extract_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_code_fence_with_invalid_json(self) -> None:
        assert _extract_json_object('```json\nnot json\n```') is None

    def test_substring_extraction(self) -> None:
        assert _extract_json_object('prefix {"a": 1} suffix') == {"a": 1}

    def test_substring_invalid_json_returns_none(self) -> None:
        assert _extract_json_object('prefix {not json} suffix') is None

    def test_no_braces_in_text(self) -> None:
        assert _extract_json_object("just text") is None

    def test_only_open_brace(self) -> None:
        # start=0, end=-1 (rfind returns -1) → end <= start → None
        assert _extract_json_object("{no closing") is None

    def test_close_before_open(self) -> None:
        # text = "}{" → start=1, end=0 → end <= start → None
        assert _extract_json_object("}{") is None


# ---------------------------------------------------------------------------
# _extract_params_patch
# ---------------------------------------------------------------------------


class TestExtractParamsPatch:
    def test_params_patch_key(self) -> None:
        assert _extract_params_patch({"params_patch": {"a": 1}}) == {"a": 1}

    def test_patch_params_key(self) -> None:
        assert _extract_params_patch({"patch_params": {"a": 1}}) == {"a": 1}

    def test_set_params_key(self) -> None:
        assert _extract_params_patch({"set_params": {"a": 1}}) == {"a": 1}

    def test_params_key(self) -> None:
        assert _extract_params_patch({"params": {"a": 1}}) == {"a": 1}

    def test_no_matching_key_returns_empty(self) -> None:
        assert _extract_params_patch({"other": {"a": 1}}) == {}

    def test_non_dict_value_skipped(self) -> None:
        assert _extract_params_patch({"params_patch": "not-a-dict"}) == {}

    def test_priority_params_patch_first(self) -> None:
        result = _extract_params_patch(
            {"params_patch": {"first": 1}, "params": {"second": 2}}
        )
        assert result == {"first": 1}

    def test_returns_copy(self) -> None:
        original = {"a": 1}
        result = _extract_params_patch({"params_patch": original})
        result["b"] = 2
        assert "b" not in original


# ---------------------------------------------------------------------------
# _llm_call_from_response
# ---------------------------------------------------------------------------


class TestLlmCallFromResponse:
    def test_basic_response(self) -> None:
        resp = {
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "provider": "openai",
            "model": "gpt-4",
        }
        call = _llm_call_from_response(resp, 100.0)
        assert call.prompt_tokens == 10
        assert call.completion_tokens == 5
        assert call.total_tokens == 15
        assert call.latency_ms == 100.0
        assert call.provider == "openai"
        assert call.model == "gpt-4"
        assert call.status == "completed"

    def test_provider_id_default_openai_compatible(self) -> None:
        resp = {"provider": "deepseek"}
        call = _llm_call_from_response(resp, 0)
        assert call.provider_id == "openai_compatible"

    def test_provider_id_xcauto(self) -> None:
        resp = {"provider": "xcauto"}
        call = _llm_call_from_response(resp, 0)
        assert call.provider_id == "openai_compatible"

    def test_provider_id_xiuci(self) -> None:
        resp = {"provider": "xiuci"}
        call = _llm_call_from_response(resp, 0)
        assert call.provider_id == "openai_compatible"

    def test_provider_id_explicit(self) -> None:
        resp = {"provider": "custom", "provider_id": "custom-id"}
        call = _llm_call_from_response(resp, 0)
        assert call.provider_id == "custom-id"

    def test_provider_id_for_unknown_provider(self) -> None:
        resp = {"provider": "unknown-provider"}
        call = _llm_call_from_response(resp, 0)
        assert call.provider_id == "unknown-provider"

    def test_total_tokens_fallback_to_sum(self) -> None:
        resp = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        call = _llm_call_from_response(resp, 0)
        assert call.total_tokens == 15

    def test_usage_not_dict(self) -> None:
        resp = {"usage": "not-a-dict"}
        call = _llm_call_from_response(resp, 0)
        assert call.prompt_tokens == 0
        assert call.completion_tokens == 0
        assert call.total_tokens == 0

    def test_usage_none(self) -> None:
        resp = {}
        call = _llm_call_from_response(resp, 0)
        assert call.prompt_tokens == 0
        assert call.completion_tokens == 0
        assert call.total_tokens == 0

    def test_failed_status(self) -> None:
        resp = {}
        call = _llm_call_from_response(resp, 0, status="failed", error="boom")
        assert call.status == "failed"
        assert call.error == "boom"

    def test_invalid_status_defaults_completed(self) -> None:
        resp = {}
        call = _llm_call_from_response(resp, 0, status="invalid")
        assert call.status == "completed"

    def test_billing_status_metered_when_cost_units(self) -> None:
        resp = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        call = _llm_call_from_response(resp, 0)
        # cost_units computed from estimate_llm_cost_units
        if call.cost_units > 0:
            assert call.billing_status == "metered"
        else:
            assert call.billing_status == "unmetered"

    def test_model_falls_back_to_resolve_default(self) -> None:
        with patch(
            "app.application.agent_orchestrator.repair_advisor.resolve_default_chat_model",
            return_value="default-model",
        ):
            call = _llm_call_from_response({}, 0)
            assert call.model == "default-model"

    def test_provider_falls_back_to_resolve_default(self) -> None:
        with patch(
            "app.application.agent_orchestrator.repair_advisor.resolve_default_openai_provider",
            return_value="default-provider",
        ):
            call = _llm_call_from_response({}, 0)
            assert call.provider == "default-provider"


# ---------------------------------------------------------------------------
# _coerce_positive_int / _coerce_int / _coerce_float
# ---------------------------------------------------------------------------


class TestCoercePositiveInt:
    def test_valid_int(self) -> None:
        assert _coerce_positive_int(5) == 5

    def test_zero(self) -> None:
        assert _coerce_positive_int(0) == 0

    def test_negative_clamped_to_zero(self) -> None:
        assert _coerce_positive_int(-5) == 0

    def test_none(self) -> None:
        assert _coerce_positive_int(None) == 0

    def test_string_valid(self) -> None:
        assert _coerce_positive_int("7") == 7

    def test_string_invalid(self) -> None:
        assert _coerce_positive_int("abc") == 0

    def test_float(self) -> None:
        assert _coerce_positive_int(3.7) == 3


class TestCoerceInt:
    def test_valid_int(self) -> None:
        assert _coerce_int(5) == 5

    def test_none(self) -> None:
        assert _coerce_int(None) == 0

    def test_string_valid(self) -> None:
        assert _coerce_int("7") == 7

    def test_string_invalid(self) -> None:
        assert _coerce_int("abc") == 0

    def test_zero(self) -> None:
        assert _coerce_int(0) == 0


class TestCoerceFloat:
    def test_valid_float(self) -> None:
        assert _coerce_float(3.14) == 3.14

    def test_int(self) -> None:
        assert _coerce_float(5) == 5.0

    def test_none(self) -> None:
        assert _coerce_float(None) == 0.0

    def test_string_valid(self) -> None:
        assert _coerce_float("3.14") == 3.14

    def test_string_invalid(self) -> None:
        assert _coerce_float("abc") == 0.0


# ---------------------------------------------------------------------------
# _run_async
# ---------------------------------------------------------------------------


class TestRunAsync:
    def test_no_running_loop_uses_asyncio_run(self) -> None:
        async def _coro() -> str:
            return "result"

        # No running loop in test thread
        result = _run_async(_coro())
        assert result == "result"

    def test_running_loop_uses_thread_pool(self) -> None:
        async def _coro() -> str:
            return "from-thread"

        async def _outer() -> str:
            # We're inside a running loop
            return _run_async(_coro())

        result = asyncio.run(_outer())
        assert result == "from-thread"


# ---------------------------------------------------------------------------
# _repair_messages
# ---------------------------------------------------------------------------


class TestRepairMessages:
    def test_basic_structure(self) -> None:
        run = _make_run()
        step = _make_step()
        messages = _repair_messages(run, step, {"source": "test", "extra": "ignored"})
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # runtime_hint should only include allowed keys
        assert "source" in messages[1]["content"]
        assert "ignored" not in messages[1]["content"]

    def test_with_observations(self) -> None:
        run = _make_run()
        step = _make_step(observations=[{"obs": "first"}, {"obs": "last"}])
        messages = _repair_messages(run, step, {})
        assert "last" in messages[1]["content"]

    def test_no_observations_uses_empty(self) -> None:
        run = _make_run()
        step = _make_step(observations=[])
        messages = _repair_messages(run, step, {})
        # should not raise; latest_observation = {}
        assert len(messages) == 2

    def test_tool_spec_import_failure_uses_empty(self) -> None:
        run = _make_run()
        step = _make_step()
        with patch(
            "app.application.agent_orchestrator.tool_spec.get_tool_action_spec",
            side_effect=ImportError("no module"),
        ):
            messages = _repair_messages(run, step, {})
        assert len(messages) == 2

    def test_runtime_context_none(self) -> None:
        run = _make_run()
        step = _make_step()
        messages = _repair_messages(run, step, None)  # type: ignore[arg-type]
        assert len(messages) == 2

    def test_runtime_context_filters_to_allowed_keys(self) -> None:
        run = _make_run()
        step = _make_step()
        messages = _repair_messages(
            run,
            step,
            {
                "source": "s",
                "task_id": "t",
                "dataset_id": "d",
                "workspace": "w",
                "tenant_id": "ti",
                "ignored_key": "x",
            },
        )
        content = messages[1]["content"]
        assert "s" in content
        assert "t" in content
        assert "d" in content
        assert "w" in content
        assert "ti" in content
        assert "ignored_key" not in content
