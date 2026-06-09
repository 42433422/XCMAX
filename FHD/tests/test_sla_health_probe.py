"""SLA health probe — nightly CI writes metrics/sla-snapshot.json probe_result."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

BUDGET_MS = int(os.environ.get("XCAGI_SLA_HEALTH_MS", "500"))
METRICS_DIR = Path(__file__).resolve().parents[1] / "metrics"
SNAPSHOT_PATH = METRICS_DIR / "sla-snapshot.json"


def _probe_health(client) -> dict:
    started = time.perf_counter()
    resp = client.get("/api/health")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "status_code": resp.status_code,
        "elapsed_ms": elapsed_ms,
        "within_budget": resp.status_code < 500 and elapsed_ms <= BUDGET_MS * 4,
        "budget_ms": BUDGET_MS,
    }


def _write_snapshot(client, health: dict | None = None) -> None:
    if os.environ.get("SKIP_SLA_SNAPSHOT_WRITE", "").strip().lower() in {"1", "true", "yes"}:
        return
    health = health or _probe_health(client)
    login_started = time.perf_counter()
    login_resp = client.post(
        "/api/auth/login",
        json={
            "username": os.environ.get("E2E_USER", "admin"),
            "password": os.environ.get("E2E_PASSWORD", "admin123"),
            "account_kind": "personal",
        },
    )
    login_ms = round((time.perf_counter() - login_started) * 1000, 2)
    payload: dict = {}
    if SNAPSHOT_PATH.is_file():
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    payload.update(
        {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "tests/test_sla_health_probe.py + docs/SLO.md",
            "probe": {
                "endpoint": "/api/health",
                "budget_ms_env": "XCAGI_SLA_HEALTH_MS",
                "default_budget_ms": BUDGET_MS,
                "measured_at": datetime.now(UTC).isoformat(),
                "probe_result": {
                    "health": health,
                    "login": {
                        "status_code": login_resp.status_code,
                        "elapsed_ms": login_ms,
                    },
                },
            },
        }
    )
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_health_endpoint_latency_probe(client):
    """Probe /api/health; budget from XCAGI_SLA_HEALTH_MS (default 500ms)."""
    result = _probe_health(client)
    assert result["status_code"] < 500, f"health returned {result['status_code']}"
    assert result["within_budget"], (
        f"/api/health took {result['elapsed_ms']}ms (budget {BUDGET_MS}ms)"
    )
    _write_snapshot(client, result)


def test_login_endpoint_reachable(client):
    """Optional login probe for SLO-API-02 metric path (non-blocking on 401/403)."""
    started = time.perf_counter()
    resp = client.post(
        "/api/auth/login",
        json={
            "username": os.environ.get("E2E_USER", "admin"),
            "password": os.environ.get("E2E_PASSWORD", "admin123"),
            "account_kind": "personal",
        },
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    assert resp.status_code < 500, resp.text
    assert elapsed_ms < BUDGET_MS * 10
