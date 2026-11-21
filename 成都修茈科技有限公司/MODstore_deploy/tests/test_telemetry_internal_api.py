"""telemetry_internal_api 鉴权与 ingest。"""

import logging
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


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


@pytest.fixture
def scan_client(telemetry_secret):
    from modstore_server.telemetry_internal_api import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def market_scan(monkeypatch):
    from modstore_server import telemetry_backlog_loop as loop

    monkeypatch.setenv("XCAGI_TELEMETRY_BACKLOG_ENABLED", "1")
    for name in (
        "_scan_employee_execution_metrics",
        "_scan_coverage_trend",
        "_scan_ci_failure_rate",
        "_scan_auto_merge_metrics",
        "_scan_security_scan_metrics",
        "_scan_coverage_ratchet_gap",
        "_scan_workflow_drift",
    ):
        monkeypatch.setattr(loop, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(
        loop,
        "_scan_market_signals",
        lambda _: [{"type": "market_signal", "payload": {"description": "Market feedback"}}],
    )
    monkeypatch.setattr("modstore_server.incident_bus.publish", lambda *args, **kwargs: None)
    return loop


@pytest.mark.parametrize(
    "failure_kind,error_type,error_code,ingested",
    [
        ("telemetry_backlog", "market_signal", "telemetry_signal_ingest_failed", 0),
        ("release_planning", "release_planning", "telemetry_release_planning_failed", 1),
    ],
)
def test_scan_failure_keeps_error_class_without_private_database_diagnostics(
    scan_client,
    telemetry_secret,
    market_scan,
    monkeypatch,
    caplog,
    failure_kind,
    error_type,
    error_code,
    ingested,
):
    diagnostic = "private-db-host /srv/private/schema.sql SELECT private_account_data"
    operations = []

    def create_suggestion(**kwargs):
        operations.append(kwargs["kind"])
        if kwargs["kind"] == failure_kind:
            raise SQLAlchemyError(diagnostic)
        return {"ok": True, "suggestion_id": len(operations)}

    monkeypatch.setattr(
        "modstore_server.employee_autonomy_service.create_employee_suggestion",
        create_suggestion,
    )
    with caplog.at_level(logging.WARNING, logger=market_scan.__name__):
        response = scan_client.post(
            "/api/internal/telemetry/scan", headers={"X-Telemetry-Secret": telemetry_secret}
        )

    assert response.status_code == 200
    assert diagnostic not in response.text
    assert diagnostic not in caplog.text
    assert "SQLAlchemyError" in caplog.text
    assert operations == ["telemetry_backlog", "release_planning"]
    assert response.json() == {
        "ok": False,
        "signals_found": 1,
        "signals_ingested": ingested,
        "signals_failed": 1,
        "errors": [{"type": error_type, "error": error_code}],
        "release_planning": {"ok": True, "suggestion_id": 2} if ingested == 0 else {},
    }


def test_scan_success_keeps_original_counts_and_release_receipt(
    scan_client,
    telemetry_secret,
    market_scan,
    monkeypatch,
):
    operations = []

    def create_suggestion(**kwargs):
        operations.append(kwargs["kind"])
        return {"ok": True, "suggestion_id": len(operations)}

    monkeypatch.setattr(
        "modstore_server.employee_autonomy_service.create_employee_suggestion",
        create_suggestion,
    )
    response = scan_client.post(
        "/api/internal/telemetry/scan", headers={"X-Telemetry-Secret": telemetry_secret}
    )
    assert response.status_code == 200
    assert operations == ["telemetry_backlog", "release_planning"]
    assert response.json() == {
        "ok": True,
        "signals_found": 1,
        "signals_ingested": 1,
        "signals_failed": 0,
        "errors": [],
        "release_planning": {"ok": True, "suggestion_id": 2},
    }


@pytest.mark.parametrize("authorization", ["missing", "invalid", "unconfigured"])
def test_scan_rejects_authorization_before_starting_work(
    scan_client,
    telemetry_secret,
    monkeypatch,
    authorization,
):
    scan = Mock(side_effect=AssertionError("unauthorized scan executed"))
    monkeypatch.setattr("modstore_server.telemetry_backlog_loop.run_telemetry_scan", scan)
    if authorization == "unconfigured":
        monkeypatch.delenv("XCAGI_TELEMETRY_INGEST_SECRET")
    headers = {} if authorization == "missing" else {"X-Telemetry-Secret": "wrong-secret"}
    response = scan_client.post("/api/internal/telemetry/scan", headers=headers)
    assert response.status_code == (503 if authorization == "unconfigured" else 401)
    scan.assert_not_called()


def test_disabled_scan_keeps_original_skipped_response(scan_client, telemetry_secret, monkeypatch):
    monkeypatch.setenv("XCAGI_TELEMETRY_BACKLOG_ENABLED", "0")
    scanner = Mock(side_effect=AssertionError("disabled scan executed"))
    monkeypatch.setattr(
        "modstore_server.telemetry_backlog_loop._scan_employee_execution_metrics", scanner
    )
    response = scan_client.post(
        "/api/internal/telemetry/scan", headers={"X-Telemetry-Secret": telemetry_secret}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "skipped": True}
    scanner.assert_not_called()


@pytest.mark.parametrize("stage", ["ingest", "planning"])
def test_scan_reports_failed_stage_without_internal_error_text(
    telemetry_secret, monkeypatch, stage, caplog
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
                "telemetry_release_planning_failed"
                if stage == "planning"
                else "telemetry_signal_ingest_failed"
            ),
        }
    ]
    assert "private-token-sentinel" not in response.text
    assert "/private/database/path" not in response.text
    assert "private-token-sentinel" not in caplog.text
    assert "/private/database/path" not in caplog.text
    assert "ValueError" in caplog.text
