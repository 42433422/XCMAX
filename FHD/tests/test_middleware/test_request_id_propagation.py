"""COVERAGE_RAMP C3.0: RequestId 中间件 - 透传 / 生成 / 回写响应头。

覆盖：
- 客户端未带 X-Request-ID → 生成 UUID，响应头带回
- 客户端带 X-Request-ID → 透传
- 空字符串视为未带
- 状态可读（request.state.request_id）
"""

from __future__ import annotations

import uuid

import pytest
from app.middleware.request_id import RequestIdMiddleware
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/api/echo")
    def echo(request: Request):
        return {"id": request.state.request_id}

    return app


def test_generates_uuid_when_no_header(app):
    client = TestClient(app)
    r = client.get("/api/echo")
    assert r.status_code == 200
    rid = r.headers["X-Request-ID"]
    # 是合法 UUID
    uuid.UUID(rid)
    assert r.json()["id"] == rid


def test_passes_through_client_header(app):
    client = TestClient(app)
    r = client.get("/api/echo", headers={"X-Request-ID": "client-rid-123"})
    assert r.headers["X-Request-ID"] == "client-rid-123"
    assert r.json()["id"] == "client-rid-123"


def test_empty_header_treated_as_missing(app):
    client = TestClient(app)
    r = client.get("/api/echo", headers={"X-Request-ID": "   "})
    # 空白 → 生成新 UUID
    rid = r.headers["X-Request-ID"]
    uuid.UUID(rid)
    assert r.json()["id"] == rid
