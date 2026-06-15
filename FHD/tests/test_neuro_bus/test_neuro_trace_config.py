"""neuro_bus neuro_trace_config 单测。"""

from __future__ import annotations

from unittest.mock import patch

from app.neuro_bus.neuro_trace_config import (
    bump_domain_handler_metric,
    clear_domain_handler_metrics,
    clear_neuro_trace_config_cache,
    get_domain_handler_metrics,
    is_neuro_domain_metrics_enabled,
    is_neuro_http_trace_enabled,
    is_neuro_service_layer_trace_enabled,
    neuro_app_service_sample_rate,
    neuro_http_body_preview_max,
    neuro_http_sample_rate,
    should_sample_app_service,
    should_sample_http,
)


def setup_function():
    clear_neuro_trace_config_cache()
    clear_domain_handler_metrics()


def teardown_function():
    clear_neuro_trace_config_cache()
    clear_domain_handler_metrics()


def test_http_trace_flag(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_HTTP_TRACE", "1")
    clear_neuro_trace_config_cache()
    assert is_neuro_http_trace_enabled() is True


def test_http_sample_rate_clamped(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_HTTP_SAMPLE", "2.5")
    assert neuro_http_sample_rate() == 1.0
    monkeypatch.setenv("XCAGI_NEURO_HTTP_SAMPLE", "bad")
    assert neuro_http_sample_rate() == 0.0


def test_http_body_preview_max(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_HTTP_BODY_MAX", "512")
    assert neuro_http_body_preview_max() == 512
    monkeypatch.setenv("XCAGI_NEURO_HTTP_BODY_MAX", "x")
    assert neuro_http_body_preview_max() == 0


def test_app_service_sample_default():
    assert neuro_app_service_sample_rate() == 1.0


def test_should_sample_http_disabled(monkeypatch):
    monkeypatch.delenv("XCAGI_NEURO_HTTP_TRACE", raising=False)
    clear_neuro_trace_config_cache()
    assert should_sample_http() is False


def test_should_sample_http_always(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_HTTP_TRACE", "1")
    monkeypatch.setenv("XCAGI_NEURO_HTTP_SAMPLE", "1")
    clear_neuro_trace_config_cache()
    assert should_sample_http() is True


def test_should_sample_app_service_zero(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_APP_SAMPLE", "0")
    assert should_sample_app_service() is False


def test_should_sample_app_service_random(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_APP_SAMPLE", "0.5")
    with patch("app.neuro_bus.neuro_trace_config.random.random", return_value=0.1):
        assert should_sample_app_service() is True
    with patch("app.neuro_bus.neuro_trace_config.random.random", return_value=0.9):
        assert should_sample_app_service() is False


def test_service_layer_trace_default_on():
    assert is_neuro_service_layer_trace_enabled() is True


def test_service_layer_trace_off(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_SERVICE_TRACE", "0")
    assert is_neuro_service_layer_trace_enabled() is False


def test_domain_handler_metrics(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_DOMAIN_METRICS", "1")
    clear_domain_handler_metrics()
    assert is_neuro_domain_metrics_enabled() is True
    bump_domain_handler_metric("a.b")
    bump_domain_handler_metric("a.b")
    assert get_domain_handler_metrics()["a.b"] == 2
