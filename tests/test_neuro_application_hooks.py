# -*- coding: utf-8 -*-
"""Application 桥接轻量单测（mock 发布，不依赖总线队列）。"""

from unittest.mock import patch


def test_neuro_trace_app_service_call_invokes_publish(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")
    with patch("app.neuro_bus.application_neuro_bridge._publish", return_value=True) as pub:
        from app.neuro_bus.application_neuro_bridge import neuro_trace_app_service_call

        neuro_trace_app_service_call("ShipmentApplicationService", "create_order", "start")
        assert pub.call_count == 1
        args, kwargs = pub.call_args
        assert args[0] == "application.service.trace"
        assert args[2] == "order"


def test_bump_domain_handler_metric_respects_flag(monkeypatch):
    from app.neuro_bus.neuro_trace_config import (
        bump_domain_handler_metric,
        clear_domain_handler_metrics,
        get_domain_handler_metrics,
    )

    clear_domain_handler_metrics()
    monkeypatch.setenv("XCAGI_NEURO_DOMAIN_METRICS", "0")
    bump_domain_handler_metric("unit.test.event")
    assert get_domain_handler_metrics() == {}

    monkeypatch.setenv("XCAGI_NEURO_DOMAIN_METRICS", "1")
    bump_domain_handler_metric("unit.test.event")
    assert get_domain_handler_metrics().get("unit.test.event") == 1
