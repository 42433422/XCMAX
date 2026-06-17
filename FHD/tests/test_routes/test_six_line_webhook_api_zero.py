"""Tests for app.fastapi_routes.six_line_webhook_api."""
from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.six_line_webhook_api import (
    _normalize_body,
    _normalize_github,
    _normalize_grafana,
    _verify_secret,
)


class TestVerifySecret:
    """Tests for _verify_secret."""

    def test_returns_true_when_no_secret_configured(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = _verify_secret(MagicMock(), b"body", None)
            assert result is True

    def test_returns_false_when_secret_set_but_no_signature(self) -> None:
        with patch.dict("os.environ", {"SIX_LINE_WEBHOOK_SECRET": "mysecret"}):
            result = _verify_secret(MagicMock(), b"body", None)
            assert result is False

    def test_returns_true_for_valid_signature(self) -> None:
        secret = "mysecret"
        body = b'{"test": true}'
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch.dict("os.environ", {"SIX_LINE_WEBHOOK_SECRET": secret}):
            result = _verify_secret(MagicMock(), body, f"sha256={expected}")
            assert result is True

    def test_returns_false_for_invalid_signature(self) -> None:
        with patch.dict("os.environ", {"SIX_LINE_WEBHOOK_SECRET": "mysecret"}):
            result = _verify_secret(MagicMock(), b"body", "sha256=invalidsig")
            assert result is False

    def test_uses_xcagi_telemetry_secret_as_fallback(self) -> None:
        secret = "telemetrysecret"
        body = b"payload"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch.dict("os.environ", {"XCAGI_TELEMETRY_INGEST_SECRET": secret}, clear=True):
            result = _verify_secret(MagicMock(), body, f"sha256={expected}")
            assert result is True


class TestNormalizeGithub:
    """Tests for _normalize_github."""

    def test_returns_event_for_failed_workflow(self) -> None:
        payload = {
            "workflow_run": {"conclusion": "failure", "id": 12345}
        }
        result = _normalize_github(payload)
        assert result is not None
        assert result["event_type"] == "ci.failed"
        assert result["step_id"] == "P3"
        assert result["status"] == "anomaly"
        assert result["payload"]["source"] == "github"
        assert result["payload"]["run_id"] == 12345

    def test_returns_none_for_successful_workflow(self) -> None:
        payload = {
            "workflow_run": {"conclusion": "success", "id": 12345}
        }
        result = _normalize_github(payload)
        assert result is None

    def test_returns_none_for_no_workflow_run(self) -> None:
        result = _normalize_github({})
        assert result is None


class TestNormalizeGrafana:
    """Tests for _normalize_grafana."""

    def test_returns_event_for_alerts_list(self) -> None:
        payload = {"alerts": [{"status": "firing"}]}
        result = _normalize_grafana(payload)
        assert result is not None
        assert result["event_type"] == "security.alert"
        assert result["step_id"] == "R4"
        assert result["payload"]["alerts"] == 1

    def test_returns_event_for_alerting_state(self) -> None:
        payload = {"state": "alerting"}
        result = _normalize_grafana(payload)
        assert result is not None
        assert result["event_type"] == "security.alert"

    def test_returns_none_for_normal_state(self) -> None:
        payload = {"state": "ok"}
        result = _normalize_grafana(payload)
        assert result is None

    def test_returns_none_for_empty_alerts(self) -> None:
        payload = {"alerts": []}
        result = _normalize_grafana(payload)
        assert result is None

    def test_returns_none_for_no_alerts(self) -> None:
        result = _normalize_grafana({})
        assert result is None


class TestNormalizeBody:
    """Tests for _normalize_body."""

    def test_passes_through_complete_event(self) -> None:
        body = {"event_type": "ci.failed", "step_id": "P3", "status": "anomaly", "payload": {"x": 1}}
        result = _normalize_body(body)
        assert result == body

    def test_normalizes_github_payload(self) -> None:
        body = {"workflow_run": {"conclusion": "failure", "id": 1}}
        result = _normalize_body(body)
        assert result["event_type"] == "ci.failed"

    def test_normalizes_grafana_payload(self) -> None:
        body = {"alerts": [{"status": "firing"}]}
        result = _normalize_body(body)
        assert result["event_type"] == "security.alert"

    def test_fallback_for_unknown_payload(self) -> None:
        body = {"some_key": "some_value"}
        result = _normalize_body(body)
        assert result["event_type"] == "ops.intake.task.queued"
        assert result["step_id"] == "O7"
        assert result["status"] == "progress"

    def test_fallback_preserves_payload_dict(self) -> None:
        body = {"payload": {"key": "val"}}
        result = _normalize_body(body)
        assert result["payload"] == {"key": "val"}

    def test_fallback_uses_body_as_payload_when_not_dict(self) -> None:
        body = {"payload": "not a dict"}
        result = _normalize_body(body)
        assert result["payload"] == body
