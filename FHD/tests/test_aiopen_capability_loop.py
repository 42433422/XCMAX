"""AIOPEN 全调用闭环：白名单前缀匹配、seed、capability_loop。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.aiopen.service import (
    AIOPEN_STATE,
    is_path_whitelisted,
    normalize_api_path,
    seed_capability_whitelist,
)
from app.fastapi_routes.ai_open import router as ai_open_router


@pytest.fixture()
def client():
    app = FastAPI()

    @app.get("/api/products/list")
    def products_list():
        return {"success": True, "items": [{"id": 1}]}

    @app.post("/api/ai/unified_chat")
    def unified_chat(body: dict):
        return {"success": True, "reply": f"echo:{body.get('message', '')}"}

    app.include_router(ai_open_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_whitelist_and_keys():
    original = dict(AIOPEN_STATE.get("whitelist") or {})
    AIOPEN_STATE["runtime_keys"] = {}
    AIOPEN_STATE["whitelist"] = {
        "/api/products": True,
        "/api/ai/unified_chat": True,
    }
    yield
    AIOPEN_STATE["whitelist"] = original
    AIOPEN_STATE["runtime_keys"] = {}


def test_normalize_and_prefix_whitelist():
    assert normalize_api_path("/api/products/list?x=1") == "/api/products/list"
    assert is_path_whitelisted("/api/products")
    assert is_path_whitelisted("/api/products/list")
    assert is_path_whitelisted("/api/products/list?limit=1")
    assert not is_path_whitelisted("/api/product")
    assert not is_path_whitelisted("/api/customers")


def test_seed_capability_whitelist_enables_full_set():
    out = seed_capability_whitelist(enable=True, merge=False)
    assert out["success"] is True
    assert out["enabled_count"] >= 10
    assert is_path_whitelisted("/api/im/conversations")
    assert is_path_whitelisted("/api/mod/xcagi-erp-domain-bridge/products/list")


def test_api_call_allows_prefix_child(client):
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "api_call", "args": {"path": "/api/products/list", "method": "GET"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status_code"] == 200
    assert data["data"]["items"][0]["id"] == 1


def test_whitelist_seed_and_loop_verify(client):
    seeded = client.post("/api/aiopen/whitelist/seed", json={"enabled": True, "merge": True})
    assert seeded.status_code == 200
    assert seeded.json()["success"] is True

    loop = client.post(
        "/api/aiopen/loop/verify",
        json={"probe_path": "/api/products/list", "message": "loop-ok"},
    )
    assert loop.status_code == 200
    body = loop.json()
    assert body["success"] is True
    assert body["closed_loop"] is True
    steps = {s["step"]: s for s in body["steps"]}
    assert steps["api_catalog"]["ok"] is True
    assert steps["api_call"]["ok"] is True
    assert steps["chat"]["ok"] is True


def test_manifest_includes_capability_loop(client):
    names = {t["name"] for t in client.get("/api/aiopen/manifest").json()["tools"]}
    assert "capability_loop" in names
