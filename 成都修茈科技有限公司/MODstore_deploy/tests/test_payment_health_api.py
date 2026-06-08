"""payment_health_api 单测（无网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from modstore_server.payment_health_api import compute_payment_health


def test_compute_payment_health_python_backend(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", "http://127.0.0.1:8080")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"status": "UP"}

    with patch("modstore_server.payment_health_api.httpx.get", return_value=mock_resp):
        data = compute_payment_health()

    assert data["payment_backend"] == "python"
    assert data["java_service_healthy"] is True
    assert data["ready_for_java_cutover"] is True


def test_compute_payment_health_java_backend_unreachable(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")

    with patch(
        "modstore_server.payment_health_api.httpx.get",
        side_effect=OSError("connection refused"),
    ):
        data = compute_payment_health()

    assert data["payment_backend"] == "java"
    assert data["java_payment_reachable"] is False
    assert data["ready_for_java_cutover"] is False
