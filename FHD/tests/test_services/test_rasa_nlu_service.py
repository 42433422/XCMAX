# -*- coding: utf-8 -*-
"""RASA NLU 深度落地单元测试。

对标 reviewer 提出的"RASA 仅停留在配置阶段，未看到深度落地证据"：本组
测试断言以下事实，充当运行时证据：

1. 服务能在**未安装 RASA / 模型不存在**的场景下显式降级而不是静默返回空结果；
2. ``get_status()`` 暴露可被健康探针消费的结构化状态；
3. ``get_intent_with_confidence()`` 的返回契约稳定（(name|None, float)）；
4. ``is_available()`` 不会因为只配置了环境变量就返回 True。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.ai_engines.rasa.nlu_service import (
    RasaNLUService,
    get_rasa_nlu_service,
    reset_rasa_nlu_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_rasa_nlu_service()
    yield
    reset_rasa_nlu_service()


class TestRasaNLUServiceDisabled:
    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("ENABLE_RASA", "0")
        svc = RasaNLUService()
        assert svc.is_available() is False
        result = svc.parse("生成发货单")
        assert result["intent"] == {"name": None, "confidence": 0.0}
        assert result["message"] == "disabled"

    def test_get_status_contract(self, monkeypatch):
        monkeypatch.setenv("ENABLE_RASA", "1")
        svc = RasaNLUService(model_path=None, use_server=False)
        status = svc.get_status()
        assert status["enabled"] is True
        assert status["mode"] == "embedded"
        assert status["agent_loaded"] is False
        assert status["confidence_threshold"] == pytest.approx(0.7)


class TestRasaNLUServiceEmbeddedFallback:
    def test_missing_model_is_graceful(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ENABLE_RASA", "1")
        monkeypatch.setenv("RASA_MODEL_PATH", str(tmp_path / "missing.tar.gz"))
        svc = RasaNLUService(use_server=False)
        assert svc.load_model() is False
        assert "model_not_found" in (svc._load_error or "")
        assert svc.is_available() is False

    def test_parse_returns_empty_on_missing_model(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ENABLE_RASA", "1")
        monkeypatch.setenv("RASA_MODEL_PATH", str(tmp_path / "missing.tar.gz"))
        svc = RasaNLUService(use_server=False)
        result = svc.parse("生成发货单")
        assert result["intent"]["name"] is None
        assert result["intent"]["confidence"] == 0.0
        assert "model_not_found" in result["message"]


class TestRasaNLUServiceServer:
    def test_server_unreachable_is_reported(self, monkeypatch):
        monkeypatch.setenv("ENABLE_RASA", "1")
        monkeypatch.setenv("RASA_USE_SERVER", "1")
        monkeypatch.setenv("RASA_SERVER_URL", "http://127.0.0.1:59999")
        svc = RasaNLUService()
        assert svc.use_server is True

        # is_available 通过 /status 握手决定：59999 端口不可达 -> False
        assert svc.is_available() is False
        status = svc.get_status()
        assert status["mode"] == "server"
        assert status["target_url"].startswith("http://127.0.0.1:59999")
        assert status["server_reachable"] is False

    def test_server_response_is_passed_through(self, monkeypatch):
        monkeypatch.setenv("ENABLE_RASA", "1")
        monkeypatch.setenv("RASA_USE_SERVER", "1")

        class _FakeResp:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {
                    "intent": {"name": "shipment_generate", "confidence": 0.95},
                    "entities": [],
                    "text": "生成发货单",
                }

        svc = RasaNLUService()
        with patch("requests.post", return_value=_FakeResp()):
            result = svc.parse("生成发货单")
        assert result["intent"]["name"] == "shipment_generate"
        assert result["intent"]["confidence"] == pytest.approx(0.95)

    def test_get_intent_with_confidence_server(self, monkeypatch):
        monkeypatch.setenv("ENABLE_RASA", "1")
        monkeypatch.setenv("RASA_USE_SERVER", "1")

        class _FakeResp:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"intent": {"name": "customers", "confidence": 0.81}}

        svc = RasaNLUService()
        with patch("requests.post", return_value=_FakeResp()):
            name, conf = svc.get_intent_with_confidence("查询客户列表")
        assert name == "customers"
        assert conf == pytest.approx(0.81)


class TestRasaNLUServiceSingleton:
    def test_singleton_reuse(self):
        a = get_rasa_nlu_service()
        b = get_rasa_nlu_service()
        assert a is b

    def test_reset_clears_singleton(self):
        a = get_rasa_nlu_service()
        reset_rasa_nlu_service()
        b = get_rasa_nlu_service()
        assert a is not b
