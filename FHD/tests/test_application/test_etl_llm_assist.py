from __future__ import annotations

import threading
import time

import pytest

from app.application.etl.llm_assist import (
    LlmAssistResult,
    advise_field_mappings,
    clear_etl_llm_circuit,
)
from app.application.etl.llm_session_provider import (
    SessionMarketProvider,
    bind_etl_llm_owner,
    current_etl_llm_owner,
    reset_etl_llm_owner,
)
from app.infrastructure.llm.structured_output import StructuredResult


@pytest.fixture(autouse=True)
def _clear_etl_llm_circuit_between_tests():
    clear_etl_llm_circuit()
    yield
    clear_etl_llm_circuit()


def test_etl_structured_assist_uses_software_conversation_provider(monkeypatch):
    software_service = object()
    captured = {}
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, software_service, None),
    )

    def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return StructuredResult(
            data={
                "mappings": [
                    {
                        "source": "货品",
                        "target": "name",
                        "transform": "trim",
                        "confidence": 0.93,
                        "reason": "货品列是产品名称",
                    }
                ]
            },
            attempts=1,
            repaired=False,
            model="software-model",
        )

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        fake_complete,
    )

    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": ["品名"],
            }
        ],
    )

    assert result.used_llm is True
    assert result.model == "software-model"
    assert result.data["mappings"][0]["target"] == "name"
    assert captured["conversation_service"] is software_service
    assert captured["provider"] is None
    assert captured["profile"] == "etl"
    assert captured["max_repairs"] == 0


def test_llm_mapping_rejects_invented_source_and_target(monkeypatch):
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            data={
                "mappings": [
                    {
                        "source": "不存在列",
                        "target": "name",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                    {
                        "source": "货品",
                        "target": "dangerous_field",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                ]
            },
        ),
    )

    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    )

    assert result.data["mappings"] == []


def test_etl_uses_only_current_owner_market_session(monkeypatch):
    captured = {}
    owner_token = bind_etl_llm_owner(42)
    try:
        monkeypatch.setattr(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            lambda: object(),
        )

        def fake_latest_session_market_token(*, user_id):
            captured["user_id"] = user_id
            return "owner-market-token"

        monkeypatch.setattr(
            "app.fastapi_routes.market_account.latest_session_market_token",
            fake_latest_session_market_token,
        )
        from app.application.etl.llm_assist import _active_software_llm

        configured, conversation_service, provider = _active_software_llm()
    finally:
        reset_etl_llm_owner(owner_token)

    assert configured is True
    assert conversation_service is None
    assert isinstance(provider, SessionMarketProvider)
    assert captured["user_id"] == 42


def test_etl_owner_context_resets():
    token = bind_etl_llm_owner(7)
    assert current_etl_llm_owner() == 7
    reset_etl_llm_owner(token)
    assert current_etl_llm_owner() is None


def test_etl_reports_stable_quota_degradation(monkeypatch):
    calls = 0
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )

    def quota_exhausted(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream 429 quota exhausted")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        quota_exhausted,
    )
    kwargs = {
        "headers": ["货品"],
        "samples": {"货品": ["底漆"]},
        "target_fields": [
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    }
    first = advise_field_mappings(**kwargs)
    second = advise_field_mappings(**kwargs)

    assert first.used_llm is True
    assert first.degraded is True
    assert first.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"
    # One quota response must end the structured attempt and make every later
    # mapping/region/row advisory phase fall back immediately for this owner.
    assert calls == 1
    assert second.used_llm is False
    assert second.degraded is True
    assert second.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"


def test_etl_llm_timeout_returns_deterministic_fallback_without_repeat(monkeypatch):
    calls = 0
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )
    monkeypatch.setattr(
        "app.application.etl.llm_assist.etl_llm_timeout_seconds",
        lambda: 0.05,
    )

    def slow_complete(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=1.0)
        return StructuredResult(data={"mappings": []}, attempts=1, repaired=False)

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        slow_complete,
    )
    kwargs = {
        "headers": ["货品"],
        "samples": {"货品": ["底漆"]},
        "target_fields": [
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    }
    started_at = time.monotonic()
    try:
        first = advise_field_mappings(**kwargs)
        elapsed = time.monotonic() - started_at
        second = advise_field_mappings(**kwargs)
    finally:
        release.set()

    assert entered.is_set()
    assert elapsed < 0.25
    assert first.used_llm is True
    assert first.degraded is True
    assert first.degradation_code == "ETL_LLM_UNAVAILABLE"
    assert calls == 1
    assert second.used_llm is False
    assert second.degradation_code == "ETL_LLM_UNAVAILABLE"


def test_owner_circuit_collapses_concurrent_quota_advice(monkeypatch):
    calls = 0
    first_request_started = threading.Event()
    release_first_request = threading.Event()
    results = []
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )

    def quota_exhausted(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        first_request_started.set()
        release_first_request.wait(timeout=1.0)
        raise RuntimeError("upstream 429 quota exhausted")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        quota_exhausted,
    )
    kwargs = {
        "headers": ["货品"],
        "samples": {"货品": ["底漆"]},
        "target_fields": [
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    }

    def advise() -> None:
        results.append(advise_field_mappings(**kwargs))

    first = threading.Thread(target=advise)
    second = threading.Thread(target=advise)
    first.start()
    assert first_request_started.wait(timeout=0.5)
    second.start()
    try:
        # The second preview can reach _complete while the first provider call
        # is pending; it must wait for the owner gate, then see the breaker.
        time.sleep(0.03)
    finally:
        release_first_request.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == 1
    assert len(results) == 2
    assert all(result.degraded for result in results)
    assert {result.degradation_code for result in results} == {"ETL_LLM_QUOTA_EXHAUSTED"}
