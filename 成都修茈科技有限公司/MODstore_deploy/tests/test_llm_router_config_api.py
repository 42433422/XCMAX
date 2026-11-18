"""管理端 LLM Router 配置测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from modstore_server import llm_router_config as config
from modstore_server import llm_router_config_api as api
from modstore_server.api.deps import get_current_user

PATH = "/api/llm/admin/llm-router-config"


def _payload(**overrides):
    data = {
        "enabled": True,
        "routing_strategy": "simple-shuffle",
        "num_retries": 2,
        "cooldown_seconds": 60,
        "allowed_fails": 2,
        "max_parallel": 0,
        "mid_stream_fallback": False,
        "request_timeout_seconds": 60,
        "stream_timeout_seconds": 180,
        "platform_fallbacks": ["minimax/MiniMax-M2.7"],
    }
    data.update(overrides)
    return data


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_LLM_ROUTER_CONFIG_PATH", str(tmp_path / "router.json"))
    config.reset_cache()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/llm")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, is_admin=True)
    with TestClient(app) as client:
        yield client
    config.reset_cache()


def test_admin_gate(client):
    def identity():
        raise HTTPException(401, "请登录")

    client.app.dependency_overrides[get_current_user] = identity
    assert client.get(PATH).status_code == 401
    assert client.put(PATH, json=_payload()).status_code == 401
    assert not config.config_path().exists()


def test_save_and_readback(client):
    response = client.put(PATH, json=_payload(num_retries=3, routing_strategy="least-busy"))
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["num_retries"] == 3
    assert body["config"]["routing_strategy"] == "least-busy"
    assert body["config"]["revision"]
    assert body["effective"]["num_retries"] == 3

    saved = client.get(PATH).json()
    assert saved["config"]["platform_fallbacks"] == ["minimax/MiniMax-M2.7"]
    assert saved["config"]["revision"] == body["config"]["revision"]


def test_invalid_strategy_rejected(client):
    response = client.put(PATH, json=_payload(routing_strategy="unknown"))
    assert response.status_code == 400
    assert "routing_strategy" in response.text


def test_invalid_fallback_format_rejected(client):
    response = client.put(PATH, json=_payload(platform_fallbacks=["minimax"]))
    assert response.status_code == 400


def test_env_overrides_stored_config(client, monkeypatch):
    assert client.put(PATH, json=_payload(routing_strategy="least-busy")).status_code == 200
    monkeypatch.setenv("MODSTORE_LLM_ROUTER_STRATEGY", "latency-based-routing")

    body = client.get(PATH).json()

    assert body["config"]["routing_strategy"] == "least-busy"
    assert body["effective"]["routing_strategy"] == "latency-based-routing"


def test_disabled_switch_blocks_router(monkeypatch, tmp_path):
    from modstore_server import llm_litellm_router

    monkeypatch.setenv("MODSTORE_LLM_ROUTER_CONFIG_PATH", str(tmp_path / "router.json"))
    config.save_state(_payload(enabled=False), actor="test")
    monkeypatch.setattr(llm_litellm_router, "_load_litellm", lambda: SimpleNamespace())

    assert llm_litellm_router.available() is False
