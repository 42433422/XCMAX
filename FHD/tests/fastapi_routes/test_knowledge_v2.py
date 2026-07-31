from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.infrastructure.memory_graph_store import MemoryGraphStore
from app.application.memory_update_engine import MemoryUpdateEngine
from app.application.memory_graph_app_service import MemoryGraphAppService
from app.fastapi_routes.knowledge_v2 import create_v2_router


@pytest.fixture()
def client():
    # FastAPI TestClient 在独立线程跑请求；:memory: 默认每线程一个库，
    # 用 StaticPool 强制共享同一连接，确保建表与请求看到同一个 in-memory DB。
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    app_service = MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))
    app = FastAPI()
    app.include_router(create_v2_router(app_service))
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/knowledge/v2/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "v2"


def test_ingest_constraint(client):
    resp = client.post(
        "/api/knowledge/v2/nodes",
        json={
            "type": "constraint",
            "title": "Ruff 唯一格式化工具",
            "content": "禁止 black/isort",
            "scope": "project",
            "scope_id": "XCMAX",
            "tags": ["ruff"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["action"] == "ADD"
    assert data["node_id"]


def test_get_active_constraints(client):
    client.post(
        "/api/knowledge/v2/nodes",
        json={
            "type": "constraint",
            "title": "Ruff 唯一格式化工具",
            "content": "禁止 black/isort",
            "scope": "project",
            "scope_id": "XCMAX",
        },
    )
    resp = client.get(
        "/api/knowledge/v2/nodes/active",
        params={"scope": "project", "scope_id": "XCMAX", "type": "constraint"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["nodes"][0]["title"] == "Ruff 唯一格式化工具"


def test_search(client):
    client.post(
        "/api/knowledge/v2/nodes",
        json={
            "type": "constraint",
            "title": "Ruff 唯一格式化工具",
            "content": "禁止 black/isort",
            "scope": "project",
            "scope_id": "XCMAX",
        },
    )
    resp = client.post(
        "/api/knowledge/v2/search",
        json={
            "query": "Ruff",
            "scope": "project",
            "scope_id": "XCMAX",
            "top_k": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert "Ruff" in data["results"][0]["title"]
