from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mounts.health import register_health_routes
from app.mod_sdk.deliverable_status import build_deliverable_status
from app.runtime_integrity import (
    clear_runtime_issue,
    neuro_degraded_reasons,
    record_runtime_component,
    record_runtime_issue,
    runtime_integrity_snapshot,
)


def test_required_runtime_failure_degrades_health_and_blocks_delivery(monkeypatch):
    app = FastAPI(version="1.0.0")
    record_runtime_component(
        app,
        "desktop_runtime_routes",
        ok=False,
        required=True,
        detail="module missing",
    )
    register_health_routes(app)

    body = TestClient(app).get("/api/health", params={"lite": True}).json()
    assert body["status"] == "unhealthy"
    assert "module missing" in body["degradedReasons"]

    monkeypatch.setattr("app.mod_sdk.deliverable_status._mods_routes_loaded", lambda _app: True)
    data = build_deliverable_status([], app=app)
    assert data["deliverable"] is False
    assert any(b["code"] == "RUNTIME_COMPONENT_UNAVAILABLE" for b in data["blockers"])


def test_optional_process_issue_is_degraded_not_blocking():
    key = "test:optional-runtime"
    try:
        record_runtime_issue(key, "optional integration unavailable", ttl_seconds=30)
        state = runtime_integrity_snapshot()
        assert state["status"] == "degraded"
        assert state["blockers"] == []
    finally:
        clear_runtime_issue(key)


def test_neuro_llm_and_evolution_unavailable_are_not_reported_healthy():
    reasons = neuro_degraded_reasons(
        {
            "status": "healthy",
            "running": True,
            "cognition": {
                "cognition": {"llm_port_available": False},
                "evolution": {"error": "unavailable"},
            },
        }
    )
    assert "LLM_RUNTIME_UNAVAILABLE" in reasons
    assert "NEURO_EVOLUTION_UNAVAILABLE" in reasons


def test_background_llm_readiness_takes_precedence_over_legacy_alias():
    reasons = neuro_degraded_reasons(
        {
            "status": "healthy",
            "running": True,
            "cognition": {
                "cognition": {
                    "background_llm_available": True,
                    "llm_port_available": False,
                }
            },
        }
    )
    assert "LLM_RUNTIME_UNAVAILABLE" not in reasons
