"""AIOPEN 系统地图（全知层）测试：目录、资源、检索与覆盖度。

覆盖 P0 契约：路由自动生成目录、控制面排除、风险分级、语义 overlay、
MCP resources/list|read 与 knowledge_search / operation_describe。
"""

from __future__ import annotations

import json

import pytest
from fastapi import APIRouter, FastAPI, Query
from fastapi.testclient import TestClient

from app.fastapi_routes.ai_open import router as ai_open_router

_KEY = "fixture-catalog-key"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", _KEY)
    app = FastAPI()
    business = APIRouter()

    @business.get("/api/products", summary="商品列表")
    def list_products(page: int = Query(default=1)):
        return {"items": [], "page": page}

    @business.get("/api/products/search", summary="商品检索")
    def search_products(keyword: str = ""):
        return {"items": [], "keyword": keyword}

    @business.post("/api/products", summary="创建商品")
    def create_product(payload: dict):
        return {"success": True, "payload": payload}

    @business.delete("/api/products/{product_id}", summary="删除商品")
    def delete_product(product_id: str):
        return {"success": True, "product_id": product_id}

    @business.post("/api/products/batch", summary="批量创建商品")
    def batch_products(payload: dict):
        return {"success": True, "payload": payload}

    @business.post("/api/products/batch-delete", summary="批量删除商品")
    def batch_delete_products(payload: dict):
        return {"success": True, "payload": payload}

    @business.post("/api/customers", summary="Customers Create")
    def create_customer(payload: dict):
        return {"success": True, "payload": payload}

    @business.get("/api/widgets", summary="Widgets All")
    def list_widgets():
        return {"items": []}

    @business.get("/api/admin/overview", summary="内部总览")
    def admin_overview():
        return {"success": True}

    @business.get("/api/xcmax/admin/action-items", summary="管理端待办")
    def xcmax_admin_action_items():
        return {"success": True}

    app.include_router(business)
    app.include_router(ai_open_router)
    return TestClient(app, headers={"X-AIOPEN-Key": _KEY})


def _rpc(client: TestClient, method: str, params: dict | None = None) -> dict:
    response = client.post(
        "/api/aiopen/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _catalog(client: TestClient) -> dict[str, dict]:
    body = client.get("/api/aiopen/catalog/operations", params={"limit": 200}).json()
    assert body["success"] is True
    return {item["operation_id"]: item for item in body["items"]}


def test_catalog_is_generated_from_routes_with_risk_levels(client):
    operations = _catalog(client)
    assert operations["products.list"]["risk"] == "read"
    assert operations["products.create"]["risk"] == "write"
    assert operations["products.delete"]["risk"] == "danger"
    assert operations["products.batch_delete"]["risk"] == "danger"
    assert operations["products.batch"]["risk"] == "write"
    assert operations["products.list"]["scope"] == "read:products"
    assert operations["products.delete"]["scope"] == "danger:products"


def test_catalog_excludes_control_plane_routes(client):
    operations = _catalog(client)
    for entry in operations.values():
        segments = {part.lower() for part in entry["path"].split("/")}
        assert not segments & {"admin", "internal", "xcmax", "desktop"}
        assert not entry["path"].startswith("/api/aiopen")


def test_catalog_applies_semantic_overlay(client):
    operations = _catalog(client)
    semantics = operations["products.list"].get("semantics") or {}
    assert semantics.get("when_to_use")
    assert operations["products.list"]["described"] is True
    assert operations["widgets.list"]["described"] is False
    assert "semantics" not in operations["widgets.list"]


def test_catalog_filters_by_risk_and_keyword(client):
    danger = client.get("/api/aiopen/catalog/operations", params={"risk": "danger"}).json()
    assert {item["operation_id"] for item in danger["items"]} == {
        "products.delete",
        "products.batch_delete",
    }
    keyword = client.get("/api/aiopen/catalog/operations", params={"q": "检索"}).json()
    assert "products.search" in {item["operation_id"] for item in keyword["items"]}


def test_catalog_requires_key(client):
    response = client.get("/api/aiopen/catalog/operations", headers={"X-AIOPEN-Key": "invalid-key"})
    assert response.status_code == 401


def test_mcp_initialize_advertises_resources(client):
    body = _rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test"}},
    )
    capabilities = body["result"]["capabilities"]
    assert capabilities["tools"]["listChanged"] is False
    assert "resources" in capabilities


def test_mcp_resources_list_and_read(client):
    listed = _rpc(client, "resources/list")["result"]["resources"]
    assert [item["uri"] for item in listed] == ["xcmax://catalog/operations"]

    templates = _rpc(client, "resources/templates/list")["result"]["resourceTemplates"]
    assert {item["uriTemplate"] for item in templates} == {
        "xcmax://catalog/operation/{operation_id}",
        "xcmax://catalog/schema/{entity}",
    }

    catalog = _rpc(client, "resources/read", {"uri": "xcmax://catalog/operations"})
    payload = json.loads(catalog["result"]["contents"][0]["text"])
    assert payload["count"] >= 5

    card = _rpc(client, "resources/read", {"uri": "xcmax://catalog/operation/products.list"})
    operation = json.loads(card["result"]["contents"][0]["text"])
    assert operation["operation_id"] == "products.list"
    assert operation["semantics"]["when_to_use"]


def test_mcp_resources_read_unknown_uri_returns_error(client):
    body = _rpc(client, "resources/read", {"uri": "xcmax://catalog/operation/nope.none"})
    assert body["error"]["code"] == -32602


def test_knowledge_search_returns_relevant_operations(client):
    body = _rpc(
        client,
        "tools/call",
        {"name": "knowledge_search", "arguments": {"query": "商品", "limit": 5}},
    )
    text = body["result"]["content"][0]["text"]
    assert "products.list" in text
    assert body["result"]["isError"] is False


def test_operation_describe_returns_semantic_card(client):
    body = _rpc(
        client,
        "tools/call",
        {"name": "operation_describe", "arguments": {"operation_id": "products.list"}},
    )
    text = body["result"]["content"][0]["text"]
    assert "何时用" in text
    assert "read:products" in text


def test_knowledge_search_matches_chinese_intent_via_glossary(client):
    """路由摘要是英文时，中文意图仍应命中正确业务域。"""
    body = _rpc(
        client,
        "tools/call",
        {"name": "knowledge_search", "arguments": {"query": "创建客户", "limit": 3}},
    )
    lines = body["result"]["content"][0]["text"].splitlines()
    assert "customers.create" in lines[1]


def test_coverage_reports_ratios(client):
    body = client.get("/api/aiopen/coverage").json()
    assert body["operations"]["total"] >= 5
    assert body["operations"]["described"] >= 1
    assert 0 < body["ratios"]["described"] <= 1
    assert body["operations"]["by_risk"]["danger"] == 2
