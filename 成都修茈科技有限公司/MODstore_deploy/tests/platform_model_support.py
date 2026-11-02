"""Synthetic platform configuration, account storage, and outbound transport fixtures."""

import gzip
import json
import os

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import platform_model_config as config

KEY = "opaque-platform-test-key-alpha"
NEXT_KEY = "opaque-platform-test-key-beta"
BASE = "https://gateway.example.com/compatible/v1"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("MODSTORE_DATA_DIR", raising=False)
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MODSTORE_LLM_RUNTIME_ROUTE_PATH", str(tmp_path / "runtime-route.json"))
    monkeypatch.setenv("MODSTORE_EMPLOYEE_PLATFORM_FALLBACK_ENABLED", "0")
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", raising=False)
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_MODEL", raising=False)
    for name in list(os.environ):
        if name.endswith(("_API_KEY", "_BASE_URL")) or name in {
            "XIAOMI_MIMO_API_KEY",
            "MINIMAX_CODING_PLAN_API_KEY",
        }:
            monkeypatch.delenv(name, raising=False)


def payload(**changes):
    return {
        "base_url": BASE,
        "model": "custom-model",
        "display_name": "平台对话模型",
        "api_key": KEY,
        "expected_revision": None,
        **changes,
    }


def save(provider="openai", **changes):
    body = payload(**changes)
    if body.get("api_key") is not None:
        body["api_key"] = SecretStr(body["api_key"])
    return config.save_config(provider, body, actor="admin:7")


@pytest.fixture
def database(tmp_path, monkeypatch):
    from modstore_server import models

    engine = create_engine(
        f"sqlite:///{tmp_path / 'users.db'}", connect_args={"check_same_thread": False}
    )
    models.User.__table__.create(engine)
    models.UserLlmCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(models, "get_session_factory", lambda: factory)
    with factory() as db:
        db.add_all(
            [models.User(id=i, username=f"user-{i}", password_hash="test-only") for i in (1, 2)]
        )
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def upstream(monkeypatch):
    from modstore_server import openapi_connector_runtime as outbound
    from modstore_server import platform_model_transport as transport

    real_client = httpx.AsyncClient
    observed = {
        "requests": [],
        "pinned": [],
        "options": [],
        "status": 200,
        "stream": False,
        "gzip": False,
    }

    def pin(url):
        observed["pinned"].append(url)
        parsed = httpx.URL(url)
        return outbound.PinnedOutboundTarget(
            str(parsed.copy_with(host="93.184.216.34")), parsed.host, parsed.host
        )

    def respond(request):
        observed["requests"].append(request)
        if observed["status"] != 200:
            return httpx.Response(observed["status"], text=f"header echoed: {KEY}")
        if observed["stream"]:
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n',
            )
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}]})
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
        if request.url.path.endswith("/token_plan/remains"):
            return httpx.Response(
                200,
                json={
                    "model_remains": [
                        {
                            "model_name": "general",
                            "current_interval_remaining_percent": 80,
                        }
                    ]
                },
            )
        if observed["gzip"]:
            return httpx.Response(
                200,
                content=gzip.compress(
                    json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
                ),
                headers={"Content-Encoding": "gzip"},
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "OK"}}], "debug": {KEY: KEY}}
        )

    def client(**kwargs):
        observed["options"].append(kwargs)
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(outbound, "pin_url_outbound_safe", pin)
    monkeypatch.setattr(transport.httpx, "AsyncClient", client)
    return observed
