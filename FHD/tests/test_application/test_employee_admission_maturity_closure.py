"""Original employee consumers preserve pre-I/O refusals and transport uncertainty."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.application.employee_runtime import agent_runner, executor
from app.application.employee_runtime.chat_results import (
    build_collaboration_context_result,
    build_interactive_chat_fallback_result,
)
from app.application.employee_runtime.result_builders import build_cognition_failed_result
from app.domain.model_admission_errors import (
    ModelCircuitOpenError,
    ModelConcurrencyLimitError,
    ModelRateLimitError,
)
from app.infrastructure.llm import model_admission
from app.infrastructure.llm.providers import registry


@pytest.mark.parametrize(
    "error_type", [ModelRateLimitError, ModelConcurrencyLimitError, ModelCircuitOpenError]
)
def test_admission_refusal_survives_original_cognition_and_all_results(monkeypatch, error_type):
    error = error_type(17)
    network_calls = []

    async def network(*_args, **_kwargs):
        network_calls.append(True)
        raise AssertionError("admission must precede provider I/O")

    def refuse(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(model_admission, "admit_model_call", refuse)
    monkeypatch.setattr(model_admission, "_MODEL_BREAKERS", {})
    monkeypatch.setattr(model_admission, "_MODEL_INFLIGHT", 0)
    provider = model_admission.RateLimitedProvider(
        SimpleNamespace(provider_id="fixture", chat_completion=network)
    )
    monkeypatch.setattr(registry, "get_active_provider", lambda: provider)
    reasoning = executor._cognition_fhd({}, {"normalized_input": {}}, {}, "question")
    pack = {"pack_id": "fixture", "version": "1"}
    results = [
        reasoning,
        build_cognition_failed_result("fixture", pack, "question", ["llm_md"], reasoning, 0),
        build_interactive_chat_fallback_result(
            "fixture", pack, {}, "question", ["llm_md"], reasoning, 0
        ),
        build_collaboration_context_result(
            "fixture",
            pack,
            {},
            "question",
            ["llm_md"],
            reasoning,
            0,
            SimpleNamespace(has_content=False),
            degraded=True,
        ),
    ]
    for result in results:
        assert result["error_code"] == error.code
        assert result["retry_after"] == 17
        assert result["retryable"] is True
        assert result["outcome"] == "not_started"
        assert result["reconciliation_required"] is False
        assert "重新登录" not in result["error"]
    assert all(result["success"] is False for result in results[1:])
    assert network_calls == []


def test_actual_concurrency_guard_does_not_become_missing_configuration(monkeypatch):
    monkeypatch.setenv("XCAGI_MODEL_MAX_INFLIGHT", "1")
    monkeypatch.setattr(model_admission, "_MODEL_INFLIGHT", 0)
    monkeypatch.setattr(model_admission, "_MODEL_BREAKERS", {})
    inner = SimpleNamespace(provider_id="fixture")
    monkeypatch.setattr(
        registry, "get_active_provider", lambda: model_admission.RateLimitedProvider(inner)
    )
    with model_admission.model_call_slot(inner):
        result = asyncio.run(agent_runner._chat_completion([]))
    assert result["error_code"] == "model_concurrency_limited"
    assert result["outcome"] == "not_started"
    assert result["retry_after"] == 1
    assert model_admission._MODEL_INFLIGHT == 0


@pytest.mark.parametrize(
    ("error_type", "kind", "retryable", "outcome"),
    [
        (httpx.ConnectTimeout, "transport_unavailable", True, "not_started"),
        (httpx.ReadTimeout, "transport_unknown", False, "unknown"),
    ],
)
def test_network_failure_keeps_safe_retry_boundary(
    monkeypatch, error_type, kind, retryable, outcome
):
    async def network(*_args, **_kwargs):
        raise error_type("do-not-expose-provider-secret")

    monkeypatch.setattr(
        registry, "get_active_provider", lambda: SimpleNamespace(chat_completion=network)
    )
    result = asyncio.run(agent_runner._chat_completion([]))
    assert result["error_code"] == kind
    assert result["retryable"] is retryable
    assert result["outcome"] == outcome
    assert result["reconciliation_required"] is (outcome == "unknown")
    assert "do-not-expose" not in str(result)


def test_missing_provider_still_reports_configuration(monkeypatch):
    monkeypatch.setattr(registry, "get_active_provider", lambda: None)
    result = asyncio.run(agent_runner._chat_completion([]))
    assert result["error_code"] == "employee_llm_not_configured"
    assert result["retryable"] is False
