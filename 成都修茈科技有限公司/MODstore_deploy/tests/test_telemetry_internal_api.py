"""telemetry_internal_api 鉴权与 ingest。"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def telemetry_secret(monkeypatch):
    monkeypatch.setenv("XCAGI_TELEMETRY_INGEST_SECRET", "unit-test-secret")
    return "unit-test-secret"


def test_ingest_requires_secret(telemetry_secret):
    from fastapi import FastAPI

    from modstore_server.telemetry_internal_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post(
        "/api/internal/telemetry/ingest",
        json={"signal_type": "market_signal", "payload": {"description": "x"}},
    )
    assert r.status_code == 401


def test_ingest_accepts_valid_signal(telemetry_secret, monkeypatch):
    monkeypatch.setattr(
        "modstore_server.telemetry_backlog_loop.ingest_telemetry_signal",
        lambda st, payload, source="": {"ok": True, "signal_type": st},
    )
    from fastapi import FastAPI

    from modstore_server.telemetry_internal_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post(
        "/api/internal/telemetry/ingest",
        json={"signal_type": "coverage_drop", "payload": {"description": "low"}},
        headers={"X-Telemetry-Secret": telemetry_secret},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


@pytest.mark.parametrize("stage", ["ingest", "planning"])
def test_scan_reports_failed_stage_without_internal_error_text(
    telemetry_secret, monkeypatch, stage
):
    from fastapi import FastAPI

    from modstore_server import telemetry_backlog_loop as loop
    from modstore_server.telemetry_internal_api import router

    monkeypatch.setenv("XCAGI_TELEMETRY_BACKLOG_ENABLED", "1")
    for name in (
        "_scan_employee_execution_metrics",
        "_scan_coverage_trend",
        "_scan_ci_failure_rate",
        "_scan_market_signals",
        "_scan_auto_merge_metrics",
        "_scan_security_scan_metrics",
        "_scan_coverage_ratchet_gap",
        "_scan_workflow_drift",
    ):
        monkeypatch.setattr(loop, name, lambda *args, **kwargs: [])
    kind = "market_signal" if stage == "planning" else "coverage_drop"
    monkeypatch.setattr(loop, "_scan_coverage_trend", lambda: [{"type": kind, "payload": {}}])

    def fail(*args, **kwargs):
        raise ValueError("private-token-sentinel /private/database/path")

    monkeypatch.setattr(
        loop,
        "ingest_telemetry_signal",
        fail if stage == "ingest" else lambda **kwargs: {"ok": True},
    )
    monkeypatch.setattr(loop, "plan_release_candidate_from_market", fail)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(
        "/api/internal/telemetry/scan", headers={"X-Telemetry-Secret": telemetry_secret}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False and data["signals_failed"] == 1
    assert data["signals_ingested"] == int(stage == "planning")
    assert data["errors"] == [
        {
            "type": "release_planning" if stage == "planning" else kind,
            "error": (
                "release_planning_failed"
                if stage == "planning"
                else "telemetry_signal_ingest_failed"
            ),
        }
    ]
    assert "private-token-sentinel" not in response.text
    assert "/private/database/path" not in response.text
