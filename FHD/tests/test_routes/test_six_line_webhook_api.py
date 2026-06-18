"""Tests for app.fastapi_routes.six_line_webhook_api."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.six_line_webhook_api import (
    _normalize_body,
    _normalize_github,
    _normalize_grafana,
    _verify_secret,
)


class TestVerifySecret:
    def test_no_secret_env_returns_true(self, monkeypatch):
        monkeypatch.delenv("SIX_LINE_WEBHOOK_SECRET", raising=False)
        monkeypatch.delenv("XCAGI_TELEMETRY_INGEST_SECRET", raising=False)
        assert _verify_secret(MagicMock(), b"body", "sig") is True

    def test_no_signature_returns_false(self, monkeypatch):
        monkeypatch.setenv("SIX_LINE_WEBHOOK_SECRET", "mysecret")
        assert _verify_secret(MagicMock(), b"body", None) is False

    def test_valid_signature(self, monkeypatch):
        monkeypatch.setenv("SIX_LINE_WEBHOOK_SECRET", "mysecret")
        body = b'{"test": true}'
        expected = hmac.new(b"mysecret", body, hashlib.sha256).hexdigest()
        assert _verify_secret(MagicMock(), body, f"sha256={expected}") is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setenv("SIX_LINE_WEBHOOK_SECRET", "mysecret")
        assert _verify_secret(MagicMock(), b"body", "sha256=invalid") is False

    def test_fallback_env_var(self, monkeypatch):
        monkeypatch.delenv("SIX_LINE_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("XCAGI_TELEMETRY_INGEST_SECRET", "othersecret")
        body = b"test"
        expected = hmac.new(b"othersecret", body, hashlib.sha256).hexdigest()
        assert _verify_secret(MagicMock(), body, f"sha256={expected}") is True


class TestNormalizeGithub:
    def test_failed_workflow(self):
        payload = {"workflow_run": {"conclusion": "failure", "id": 12345}}
        result = _normalize_github(payload)
        assert result is not None
        assert result["event_type"] == "ci.failed"
        assert result["status"] == "anomaly"
        assert result["payload"]["source"] == "github"

    def test_successful_workflow_returns_none(self):
        payload = {"workflow_run": {"conclusion": "success", "id": 12345}}
        result = _normalize_github(payload)
        assert result is None

    def test_no_workflow_run_returns_none(self):
        result = _normalize_github({})
        assert result is None


class TestNormalizeGrafana:
    def test_alerts_list(self):
        payload = {"alerts": [{"state": "alerting"}]}
        result = _normalize_grafana(payload)
        assert result is not None
        assert result["event_type"] == "security.alert"
        assert result["payload"]["alerts"] == 1

    def test_alerting_state(self):
        payload = {"state": "alerting"}
        result = _normalize_grafana(payload)
        assert result is not None
        assert result["event_type"] == "security.alert"

    def test_no_alerts_returns_none(self):
        result = _normalize_grafana({})
        assert result is None

    def test_empty_alerts_list_returns_none(self):
        result = _normalize_grafana({"alerts": []})
        assert result is None


class TestNormalizeBody:
    def test_already_normalized(self):
        body = {"event_type": "ci.failed", "step_id": "P3", "status": "anomaly"}
        result = _normalize_body(body)
        assert result == body

    def test_github_payload(self):
        body = {"workflow_run": {"conclusion": "failure", "id": 1}}
        result = _normalize_body(body)
        assert result["event_type"] == "ci.failed"

    def test_grafana_payload(self):
        body = {"alerts": [{"state": "alerting"}]}
        result = _normalize_body(body)
        assert result["event_type"] == "security.alert"

    def test_unknown_payload_defaults(self):
        body = {"some_key": "some_value"}
        result = _normalize_body(body)
        assert result["event_type"] == "ops.intake.task.queued"
        assert result["step_id"] == "O7"
        assert result["status"] == "progress"

    def test_partial_fields(self):
        body = {"event_type": "custom.event"}
        result = _normalize_body(body)
        assert result["step_id"] == "O7"
