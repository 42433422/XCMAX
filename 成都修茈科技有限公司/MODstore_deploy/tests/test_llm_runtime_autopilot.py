from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from modstore_server import (
    llm_quota_monitor,
    llm_runtime_autopilot,
    llm_runtime_route,
)
from modstore_server.services import llm as llm_service


@pytest.fixture(autouse=True)
def _isolated_autopilot_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("MODSTORE_LLM_AUTOPILOT_ENABLED", raising=False)
    monkeypatch.delenv("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", raising=False)
    monkeypatch.delenv("MODSTORE_LLM_AUTOPILOT_MIN_RESIDENCE_SECONDS", raising=False)


def _catalog():
    return {
        "ok": True,
        "providers": [
            {
                "provider": "xiaomi",
                "configured": True,
                "runtime_models": ["mimo-v2.5-pro"],
            },
            {
                "provider": "minimax",
                "configured": True,
                "runtime_models": ["MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
            },
        ],
    }


def _quota(*, current_state="exhausted"):
    probe_by_state = {
        "healthy": {"ok": True, "status": 200, "error": ""},
        "warning": {"ok": False, "status": 429, "error": "rate limit"},
        "exhausted": {
            "ok": False,
            "status": 429,
            "error": "quota exhausted",
        },
        "error": {"ok": False, "status": 503, "error": "upstream unavailable"},
    }
    return {
        "ok": True,
        "providers": [
            {
                "provider": "xiaomi",
                "state": current_state,
                "visibility": "usage_only",
                "remaining_percent": None,
                "probe": probe_by_state[current_state],
            },
            {
                "provider": "minimax",
                "state": "healthy",
                "visibility": "exact",
                "remaining_percent": 99,
                "probe": {"ok": True, "status": 200, "error": ""},
            },
        ],
    }


@pytest.mark.asyncio
async def test_autopilot_is_disabled_by_default(monkeypatch):
    async def unexpected_catalog(**_kwargs):
        raise AssertionError("disabled autopilot must not inspect the live catalog")

    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", unexpected_catalog)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert llm_runtime_autopilot.autopilot_enabled() is False
    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["action"] == "disabled"


@pytest.mark.asyncio
async def test_autopilot_switches_from_exhausted_route(monkeypatch):
    events = []
    probes = []

    async def probe(provider, model):
        probes.append((provider, model))
        return {"ok": True, "status": 200, "error": ""}

    async def switch(provider, model, **kwargs):
        return {"ok": True, "current": {"provider": provider, "model": model}}

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setattr(llm_runtime_autopilot, "_write_audit", events.append)
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", lambda **kwargs: None)

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota()

    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(llm_runtime_route, "probe_runtime_route", probe)
    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", switch)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert result["ok"] is True
    assert result["action"] == "switched"
    assert result["target"] == {"provider": "minimax", "model": "MiniMax-M2.7"}
    assert probes == [
        ("minimax", "MiniMax-M2.7"),
        ("minimax", "MiniMax-M2.7"),
    ]
    assert events[-1]["action"] == "switched"


@pytest.mark.asyncio
async def test_autopilot_keeps_healthy_current_route(monkeypatch):
    events = []

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota(current_state="healthy")

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setattr(llm_runtime_autopilot, "_write_audit", events.append)
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert result["action"] == "kept"
    assert result["reason"] == "current_route_healthy"


@pytest.mark.asyncio
async def test_autopilot_waits_for_failure_threshold_then_switches(monkeypatch):
    probes = []
    switches = []

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota(current_state="error")

    async def probe(provider, model):
        probes.append((provider, model))
        return {"ok": True, "status": 200, "error": ""}

    async def switch(provider, model, **kwargs):
        switches.append((provider, model, kwargs))
        return {"ok": True, "current": {"provider": provider, "model": model}}

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_MIN_RESIDENCE_SECONDS", "0")
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(
        llm_runtime_route,
        "read_runtime_route_state",
        lambda: {
            "current": {
                "provider": "xiaomi",
                "model": "mimo-v2.5-pro",
                "revision": "route-revision-1",
                "switched_at": "2020-01-01T00:00:00+00:00",
            }
        },
    )
    monkeypatch.setattr(llm_runtime_route, "probe_runtime_route", probe)
    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", switch)

    first = await llm_runtime_autopilot.reconcile_llm_route_autopilot()
    second = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert first["action"] != "switched"
    assert second["action"] != "switched"
    assert switches == []
    assert probes == []

    third = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert third["action"] == "switched"
    assert third["target"] == {"provider": "minimax", "model": "MiniMax-M2.7"}
    assert switches[0][0:2] == ("minimax", "MiniMax-M2.7")
    assert switches[0][2]["expected_revision"] == "route-revision-1"
    assert probes == [
        ("minimax", "MiniMax-M2.7"),
        ("minimax", "MiniMax-M2.7"),
    ]


@pytest.mark.asyncio
async def test_autopilot_does_not_switch_on_ordinary_rate_limit(monkeypatch):
    switches = []

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota(current_state="warning")

    async def switch(*args, **kwargs):
        switches.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", "1")
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", switch)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert result["action"] != "switched"
    assert result["current_health"]["state"] == "warning"
    assert switches == []


@pytest.mark.asyncio
async def test_autopilot_respects_minimum_route_residence(monkeypatch):
    probes = []
    switches = []

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota(current_state="error")

    async def probe(provider, model):
        probes.append((provider, model))
        return {"ok": True, "status": 200, "error": ""}

    async def switch(*args, **kwargs):
        switches.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_MIN_RESIDENCE_SECONDS", "3600")
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(
        llm_runtime_route,
        "read_runtime_route_state",
        lambda: {
            "current": {
                "provider": "xiaomi",
                "model": "mimo-v2.5-pro",
                "revision": "route-revision-1",
                "switched_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    monkeypatch.setattr(llm_runtime_route, "probe_runtime_route", probe)
    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", switch)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert result["action"] != "switched"
    assert "residence" in result["reason"]
    assert probes == []
    assert switches == []


@pytest.mark.asyncio
async def test_autopilot_surfaces_cas_conflict_without_post_probe(monkeypatch):
    probes = []
    switch_kwargs = []

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota(current_state="exhausted")

    async def probe(provider, model):
        probes.append((provider, model))
        return {"ok": True, "status": 200, "error": ""}

    async def switch(_provider, _model, **kwargs):
        switch_kwargs.append(kwargs)
        return {
            "ok": False,
            "conflict": True,
            "error": "runtime route revision conflict",
            "actual_revision": "route-revision-2",
        }

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(
        llm_runtime_route,
        "read_runtime_route_state",
        lambda: {
            "current": {
                "provider": "xiaomi",
                "model": "mimo-v2.5-pro",
                "revision": "route-revision-1",
                "switched_at": "2020-01-01T00:00:00+00:00",
            }
        },
    )
    monkeypatch.setattr(llm_runtime_route, "probe_runtime_route", probe)
    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", switch)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert result["action"] != "switched"
    assert result["switch"]["conflict"] is True
    assert switch_kwargs[0]["expected_revision"] == "route-revision-1"
    assert probes == [("minimax", "MiniMax-M2.7")]


@pytest.mark.asyncio
async def test_autopilot_rolls_back_when_post_switch_probe_fails(monkeypatch):
    probe_results = iter(
        [
            {"ok": True, "status": 200, "error": ""},
            {"ok": False, "status": 503, "error": "unavailable"},
        ]
    )
    rollbacks = []

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        return _quota()

    async def probe(_provider, _model):
        return next(probe_results)

    async def switch(provider, model, **_kwargs):
        return {
            "ok": True,
            "current": {
                "provider": provider,
                "model": model,
                "revision": "route-revision-2",
            },
        }

    async def rollback(**kwargs):
        rollbacks.append(kwargs)
        return {"ok": True}

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setattr(llm_runtime_autopilot, "_write_audit", lambda _event: None)
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(
        llm_runtime_route,
        "read_runtime_route_state",
        lambda: {
            "current": {
                "provider": "xiaomi",
                "model": "mimo-v2.5-pro",
                "revision": "route-revision-1",
                "switched_at": "2020-01-01T00:00:00+00:00",
            }
        },
    )
    monkeypatch.setattr(llm_runtime_route, "probe_runtime_route", probe)
    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", switch)
    monkeypatch.setattr(llm_runtime_route, "rollback_runtime_route", rollback)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()

    assert result["action"] == "rolled_back"
    assert rollbacks and rollbacks[0]["force"] is True
    assert rollbacks[0]["expected_revision"] == "route-revision-2"


@pytest.mark.asyncio
async def test_autopilot_redacts_sensitive_errors_from_result_and_ledger(
    monkeypatch,
):
    fake_secret = "unit-test-autopilot-secret-never-persist"

    async def catalog(**_kwargs):
        return _catalog()

    async def quota(**_kwargs):
        result = _quota(current_state="error")
        result["providers"][0]["probe"][
            "error"
        ] = f"upstream rejected Authorization: Bearer {fake_secret}"
        return result

    async def failed_probe(_provider, _model):
        return {
            "ok": False,
            "status": 503,
            "error": f"candidate request contained api_key={fake_secret}",
        }

    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("MODSTORE_LLM_AUTOPILOT_MIN_RESIDENCE_SECONDS", "0")
    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", catalog)
    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("xiaomi", "mimo-v2.5-pro"),
    )
    monkeypatch.setattr(llm_runtime_route, "probe_runtime_route", failed_probe)

    result = await llm_runtime_autopilot.reconcile_llm_route_autopilot()
    serialized = json.dumps(result, ensure_ascii=False)
    ledger = llm_runtime_autopilot.autopilot_ledger_path().read_text(encoding="utf-8")

    assert result["action"] == "degraded_no_candidate"
    assert fake_secret not in serialized
    assert fake_secret not in ledger
