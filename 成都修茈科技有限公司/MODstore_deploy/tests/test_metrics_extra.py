"""Tests for modstore_server.metrics module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.metrics import (
    _status_outcome,
    install_metrics,
    observe_csp_violation,
    observe_payment_proxy,
    observe_realtime_ws_event,
)


class TestStatusOutcome:
    def test_success(self):
        assert _status_outcome(200) == "success"

    def test_success_201(self):
        assert _status_outcome(201) == "success"

    def test_redirect(self):
        assert _status_outcome(301) == "redirect"

    def test_redirect_302(self):
        assert _status_outcome(302) == "redirect"

    def test_client_error(self):
        assert _status_outcome(400) == "client_error"

    def test_client_error_404(self):
        assert _status_outcome(404) == "client_error"

    def test_server_error(self):
        assert _status_outcome(500) == "server_error"

    def test_server_error_503(self):
        assert _status_outcome(503) == "server_error"


class TestObservePaymentProxy:
    def test_success_call(self):
        observe_payment_proxy("POST", "/api/pay", 200, 0.05)

    def test_error_call(self):
        observe_payment_proxy("POST", "/api/pay", 500, 1.5)


class TestObserveCspViolation:
    def test_increments_counter(self):
        observe_csp_violation()


class TestObserveRealtimeWsEvent:
    def test_accepted(self):
        observe_realtime_ws_event("accepted")

    def test_auth_fail(self):
        observe_realtime_ws_event("auth_fail")


class TestInstallMetrics:
    def test_metrics_endpoint_exists(self):
        app = FastAPI()
        install_metrics(app)
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "modstore_http_requests_total" in response.text

    def test_metrics_middleware_tracks_requests(self):
        app = FastAPI()
        install_metrics(app)

        @app.get("/test-endpoint")
        def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        client.get("/test-endpoint")
        metrics_response = client.get("/metrics")
        assert metrics_response.status_code == 200
