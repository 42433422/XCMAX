"""telemetry_internal_api 鉴权与 ingest。"""

import os

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
