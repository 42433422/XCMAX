from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.fastapi_routes.knowledge_v2 import create_v2_router
from app.infrastructure.memory_graph_store import MemoryGraphStore


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


def _ingest(client, **overrides) -> str:
    payload = {
        "type": "constraint",
        "title": "默认约束",
        "content": "默认内容",
        "scope": "project",
        "scope_id": "XCMAX",
    }
    payload.update(overrides)
    resp = client.post("/api/knowledge/v2/nodes", json=payload)
    assert resp.status_code == 200
    return resp.json()["node_id"]


def test_get_node_returns_detail(client):
    node_id = _ingest(client, title="单节点详情")
    resp = client.get(f"/api/knowledge/v2/nodes/{node_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["node"]["node_id"] == node_id
    assert data["node"]["title"] == "单节点详情"


def test_get_node_returns_not_found_for_unknown_id(client):
    resp = client.get("/api/knowledge/v2/nodes/non-existent-id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "node_not_found"


def test_get_backlinks_returns_edges(client):
    # 先建目标约定节点
    client.post(
        "/api/knowledge/v2/nodes",
        json={
            "type": "convention",
            "title": "目标约定",
            "content": "被引用的目标",
            "scope": "project",
            "scope_id": "XCMAX",
        },
    )
    # 再建带 wiki-link 的来源约束；AppService 自动建立双向边
    resp = client.post(
        "/api/knowledge/v2/nodes",
        json={
            "type": "constraint",
            "title": "来源约束",
            "content": "参见 [[目标约定]]",
            "scope": "project",
            "scope_id": "XCMAX",
        },
    )
    source_id = resp.json()["node_id"]

    # 查目标约定的 backlinks
    active = client.get(
        "/api/knowledge/v2/nodes/active",
        params={"scope": "project", "scope_id": "XCMAX", "type": "convention"},
    ).json()
    target_id = active["nodes"][0]["node_id"]

    resp = client.get(f"/api/knowledge/v2/nodes/{target_id}/backlinks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    backlink = data["backlinks"][0]
    assert backlink["source_node_id"] == source_id
    assert backlink["source_title"] == "来源约束"
    assert backlink["type"] == "relates_to"
    assert backlink["bidirectional"] is True


def test_get_backlinks_empty_for_isolated_node(client):
    node_id = _ingest(client, title="孤立节点")
    resp = client.get(f"/api/knowledge/v2/nodes/{node_id}/backlinks")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_export_returns_markdown_for_scope(client):
    _ingest(client, type="constraint", title="约束 A", content="A")
    _ingest(client, type="convention", title="约定 B", content="B")
    resp = client.get(
        "/api/knowledge/v2/export",
        params={"scope": "project", "scope_id": "XCMAX", "format": "markdown"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["format"] == "markdown"
    md = data["markdown"]
    assert "## constraint (1)" in md
    assert "## convention (1)" in md
    assert "### [active] 约束 A" in md
    assert "### [active] 约定 B" in md


def test_export_filters_by_type(client):
    _ingest(client, type="constraint", title="约束 A", content="A")
    _ingest(client, type="convention", title="约定 B", content="B")
    resp = client.get(
        "/api/knowledge/v2/export",
        params={"scope": "project", "scope_id": "XCMAX", "type": "convention"},
    )
    assert resp.status_code == 200
    md = resp.json()["markdown"]
    assert "## convention (1)" in md
    assert "约束 A" not in md


def test_export_rejects_unsupported_format(client):
    resp = client.get(
        "/api/knowledge/v2/export",
        params={"scope": "project", "scope_id": "XCMAX", "format": "pdf"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "unsupported_format"


def test_confirm_node_activates_pending(client):
    # needs_confirm 创建 pending 节点；但 v2 API 默认 auto_active，所以直接 ingest 是 active。
    # 这里改用直接构造 pending 节点的 Store 路径不便；改为：先 ingest（active），再 reject，再 confirm
    node_id = _ingest(client, title="待确认节点")
    # reject
    resp = client.post(f"/api/knowledge/v2/nodes/{node_id}/reject", params={"reason": "测试拒绝"})
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "rejected"
    # confirm 应重新激活
    resp = client.post(f"/api/knowledge/v2/nodes/{node_id}/confirm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["new_status"] == "active"
    assert data["previous_status"] == "rejected"


def test_reject_node_sets_rejected_status(client):
    node_id = _ingest(client, title="将被拒绝的节点")
    resp = client.post(f"/api/knowledge/v2/nodes/{node_id}/reject", params={"reason": "不符合规范"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["new_status"] == "rejected"
    assert data["reason"] == "不符合规范"


def test_confirm_unknown_node_returns_error(client):
    resp = client.post("/api/knowledge/v2/nodes/non-existent-id/confirm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "node_not_found"
